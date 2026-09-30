"""Turn timestamped screencast frames into the demo MP4.

- compresses fast-forward spans, drops Chrome's DevTools pause overlay and blank report frames;
- if narration/manifest.json exists (see narrate.py), stretches scenes so each spoken line fits, mixes the
  voice-over into the audio track and loudness-normalises it; otherwise holds short captions for reading;
- writes SRT subtitles and a timed narration script that match the edited video.
"""

import json
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
FPS = 30
FF_FACTOR = 4.0  # speed-up inside fast-forward spans
CAPTION_LEAD = 0.25  # speech starts this long after a caption appears
CARD_LEAD = 0.6  # ... or after a title card has faded in
TAIL_GAP = 0.45  # silence kept after a line before the scene moves on
BANNER_BOX = (780, 14, 1140, 52)  # Chrome's "Debugger paused in another tab" overlay (not part of the app)


def patch_devtools_banner(frames: list[dict]) -> list[dict]:
    """Replace frames showing Chrome's DevTools pause overlay with the last clean frame."""
    clean, patched = None, 0
    for f in frames:
        region = np.asarray(Image.open(HERE / "frames" / f["file"]).convert("RGB").crop(BANNER_BOX)).astype(int)
        yellow = ((region[..., 0] > 235) & (region[..., 1] > 235) & (region[..., 2] < 205)).sum()
        if yellow > 1000 and clean is not None:
            # the renderer is paused and the whole page dimmed; the page itself is frozen, so reuse the last clean frame
            f["file"] = clean
            patched += 1
        elif yellow <= 1000:
            clean = f["file"]
    print(f"patched {patched} frames with the DevTools banner")
    return frames


def skip_blank_report(frames: list[dict], events: list[dict]) -> list[dict]:
    """While the report overlay loads, its iframe is briefly blank white; show the previous frame instead."""
    cap = next((e for e in events if e["type"] == "caption" and "decision report" in e["text"]), None)
    if cap is None:
        return frames
    end = next((e["t"] for e in events if e["t"] > cap["t"] and e["type"] in ("hide", "card")), cap["t"] + 30)
    last, skipped = None, 0
    for f in frames:
        if not (cap["t"] <= f["t"] <= end):
            last = f["file"]
            continue
        region = np.asarray(Image.open(HERE / "frames" / f["file"]).convert("L").crop((360, 80, 1560, 700)))
        if (region > 248).mean() > 0.995 and last is not None:
            f["file"] = last
            skipped += 1
        else:
            last = f["file"]
    print(f"replaced {skipped} blank report frames")
    return frames


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        assert w.getsampwidth() == 2, "expects 16-bit PCM"
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        if w.getnchannels() > 1:
            x = x.reshape(-1, w.getnchannels()).mean(axis=1)
        return x, w.getframerate()


def write_wav(path: Path, x: np.ndarray, sr: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def ts(s: float) -> str:
    ms = round(s * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def main(out_name: str = "Q-GreenFleet_walkthrough") -> None:
    d = json.loads((HERE / "timeline.json").read_text())
    frames, events = d["frames"], d["events"]
    t_start = next(e["t"] for e in events if e["type"] == "start")
    t_end = next(e["t"] for e in events if e["type"] == "end") + 0.3
    frames = sorted((f for f in frames if t_start - 0.05 <= f["t"] <= t_end), key=lambda f: f["t"])
    frames = patch_devtools_banner(frames)
    frames = skip_blank_report(frames, events)

    manifest_path = HERE / "narration" / "manifest.json"
    narration = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    clips = {(m["kind"], m["index"]): m for m in narration}

    spans, open_t = [], None
    for e in events:
        if e["type"] == "ff_start":
            open_t = e["t"]
        elif e["type"] == "ff_end" and open_t is not None:
            spans.append((open_t, e["t"]))
            open_t = None

    def base_time(t: float) -> float:
        total = t - t_start
        for a, b in spans:
            lo, hi = max(a, t_start), min(b, t)
            if hi > lo:
                total -= (hi - lo) * (1 - 1 / FF_FACTOR)
        return total

    # scenes to place narration in, and freezes so that each line (or caption) fits its scene
    scenes, holds = [], []
    n_cap = n_card = 0
    for i, e in enumerate(events):
        if e["type"] == "caption":
            nxt = next((x for x in events[i + 1:] if x["type"] in ("caption", "hide", "card", "end")), None)
            clip = clips.get(("caption", n_cap))
            need = max(2.8, len(e["text"]) * 0.05)
            if clip:
                need = max(need, CAPTION_LEAD + clip["duration"] + TAIL_GAP)
            scenes.append((e["t"], CAPTION_LEAD, clip, e))
            n_cap += 1
        elif e["type"] == "card":
            nxt = next((x for x in events[i + 1:] if x["type"] == "card_end"), None)
            clip = clips.get(("card", n_card))
            need = CARD_LEAD + clip["duration"] + TAIL_GAP if clip else 0.0
            scenes.append((e["t"], CARD_LEAD, clip, e))
            n_card += 1
        else:
            continue
        if nxt is not None:
            shown = base_time(nxt["t"]) - base_time(e["t"])
            if shown < need:
                holds.append((nxt["t"] - 0.02, need - shown))

    def out_time(t: float) -> float:
        return base_time(t) + sum(x for h, x in holds if h < t)

    length = out_time(t_end)

    # video: ffconcat with per-frame durations in edited time (a freeze extends the frame it falls in)
    lines = ["ffconcat version 1.0"]
    for i, f in enumerate(frames):
        t_next = frames[i + 1]["t"] if i + 1 < len(frames) else t_end
        dur = max(out_time(t_next) - out_time(f["t"]), 0.0)
        lines += [f"file 'frames/{f['file']}'", f"duration {dur:.4f}"]
    lines.append(f"file 'frames/{frames[-1]['file']}'")
    (HERE / "frames.ffconcat").write_text("\n".join(lines) + "\n")

    # audio: place every narration clip at its scene start
    placed = []
    if narration:
        sr = narration[0]["sr"]
        track = np.zeros(int((length + 1.0) * sr), dtype=np.float32)
        fade_in, fade_out = int(0.01 * sr), int(0.04 * sr)
        for t, lead, clip, e in scenes:
            if not clip:
                continue
            x, _ = read_wav(HERE / "narration" / clip["file"])
            x[:fade_in] *= np.linspace(0, 1, fade_in, dtype=np.float32)
            x[-fade_out:] *= np.linspace(1, 0, fade_out, dtype=np.float32)
            start = out_time(t) + lead
            k = int(start * sr)
            track[k:k + len(x)] += x[: len(track) - k]
            placed.append((start, start + len(x) / sr, clip["text"], e))
        write_wav(HERE / "narration_track.wav", track, sr)
        audio_in = ["-i", str(HERE / "narration_track.wav")]
        audio_filter = ["-af", "highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-ac", "2"]
    else:
        audio_in = ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        audio_filter = []

    mp4 = HERE / f"{out_name}.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(HERE / "frames.ffconcat"),
        *audio_in, "-vf", f"fps={FPS},scale=1920:1080:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-tune", "stillimage",
        *audio_filter, "-c:a", "aac", "-b:a", "160k", "-t", f"{length:.3f}", "-movflags", "+faststart", str(mp4),
    ], check=True)

    # subtitles: the spoken lines when narrated, otherwise the on-screen captions
    srt = []
    if placed:
        for n, (a, b, text, _) in enumerate(placed, 1):
            srt += [str(n), f"{ts(a)} --> {ts(b + 0.2)}", text, ""]
    else:
        caps = [(out_time(t), e) for t, _, _, e in scenes if e["type"] == "caption"]
        for n, (a, e) in enumerate(caps, 1):
            srt += [str(n), f"{ts(a)} --> {ts(a + max(2.8, len(e['text']) * 0.05))}", e["text"], ""]
    (HERE / f"{out_name}.srt").write_text("\n".join(srt), encoding="utf-8")

    # timed narration script (to re-record in your own voice, keep each line inside its window)
    vo = ["# Q-GreenFleet walkthrough: narration script", "",
          ("Timestamps match the edited video. The video already carries this narration (neural voice, Kokoro "
           "TTS); to record it in your own voice, mute the video's audio and read each line at its timestamp."), ""]
    rows = placed or [(out_time(t), None, e.get("vo", ""), e) for t, _, _, e in scenes if e["type"] == "caption"]
    section = None
    for a, b, text, e in rows:
        head = "Title card" if e["type"] == "card" else e.get("kicker")
        if head != section:
            section = head
            vo += [f"## {section}", ""]
        span = f"{mmss(a)}–{mmss(b)}" if b else mmss(a)
        vo += [f"**{span}**  {text}", ""]
    (HERE / f"{out_name}_voiceover.md").write_text("\n".join(vo) + "\n", encoding="utf-8")

    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name",
                            "-of", "compact", str(mp4)], capture_output=True, text=True, check=False).stdout
    print(probe.strip())
    print(f"frames={len(frames)} narrated_lines={len(placed)} ff_spans={len(spans)} holds={len(holds)} "
          f"(+{sum(x for _, x in holds):.1f}s) length={length:.1f}s")


if __name__ == "__main__":
    main()
