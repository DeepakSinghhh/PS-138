"""Turn timestamped screencast frames into an MP4, with fast-forward spans compressed, plus SRT captions
and a voice-over script whose timestamps match the edited video."""

import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
FPS = 30
FF_FACTOR = 4.0  # speed-up inside fast-forward spans


BANNER_BOX = (780, 14, 1140, 52)  # Chrome's "Debugger paused in another tab" overlay (not part of the app)


def patch_devtools_banner(frames: list[dict]) -> list[dict]:
    """Replace frames showing Chrome's DevTools pause overlay with the last clean frame."""
    import numpy as np
    from PIL import Image

    clean, patched = None, 0
    for f in frames:
        path = HERE / "frames" / f["file"]
        im = Image.open(path).convert("RGB")
        region = np.asarray(im.crop(BANNER_BOX)).astype(int)
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
    import numpy as np
    from PIL import Image

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


def main(out_name: str = "Q-GreenFleet_walkthrough") -> None:
    d = json.loads((HERE / "timeline.json").read_text())
    frames, events = d["frames"], d["events"]
    t_start = next(e["t"] for e in events if e["type"] == "start")
    t_end = next(e["t"] for e in events if e["type"] == "end") + 0.3
    frames = sorted((f for f in frames if t_start - 0.05 <= f["t"] <= t_end), key=lambda f: f["t"])
    frames = patch_devtools_banner(frames)
    frames = skip_blank_report(frames, events)

    spans, open_t = [], None
    for e in events:
        if e["type"] == "ff_start":
            open_t = e["t"]
        elif e["type"] == "ff_end" and open_t is not None:
            spans.append((open_t, e["t"]))
            open_t = None

    def base_time(t: float) -> float:
        """Map a wall-clock time to edited-video time (fast-forward spans compressed)."""
        total = t - t_start
        for a, b in spans:
            lo, hi = max(a, t_start), min(b, t)
            if hi > lo:
                total -= (hi - lo) * (1 - 1 / FF_FACTOR)
        return total

    # freeze the picture briefly where a caption would be replaced before it can be read (~20 chars/s)
    holds = []
    for i, e in enumerate(events):
        if e["type"] != "caption":
            continue
        nxt = next((x for x in events[i + 1:] if x["type"] in ("caption", "hide", "card", "end")), None)
        if nxt is None:
            continue
        need = max(2.8, len(e["text"]) * 0.05)
        shown = base_time(nxt["t"]) - base_time(e["t"])
        if shown < need:
            holds.append((nxt["t"] - 0.02, need - shown))

    def out_time(t: float) -> float:
        return base_time(t) + sum(x for h, x in holds if h < t)

    # ffconcat with per-frame durations in edited time
    lines = ["ffconcat version 1.0"]
    for i, f in enumerate(frames):
        t_next = frames[i + 1]["t"] if i + 1 < len(frames) else t_end
        dur = max(out_time(t_next) - out_time(f["t"]), 0.0)  # includes any freeze that falls inside this frame
        lines += [f"file 'frames/{f['file']}'", f"duration {dur:.4f}"]
    lines.append(f"file 'frames/{frames[-1]['file']}'")
    (HERE / "frames.ffconcat").write_text("\n".join(lines) + "\n")

    mp4 = HERE / f"{out_name}.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(HERE / "frames.ffconcat"),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", f"fps={FPS},scale=1920:1080:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", str(mp4),
    ], check=True)

    # captions -> SRT + voice-over script
    caps = []
    for i, e in enumerate(events):
        if e["type"] != "caption":
            continue
        nxt = next((x for x in events[i + 1:] if x["type"] in ("caption", "hide", "card", "end")), None)
        caps.append((out_time(e["t"]), out_time(nxt["t"]) if nxt else out_time(t_end), e))

    def ts(s: float, sep: str = ",") -> str:
        ms = round(s * 1000)
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        sec, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{sec:02d}{sep}{ms:03d}"

    srt = []
    for n, (a, b, e) in enumerate(caps, 1):
        srt += [str(n), f"{ts(a)} --> {ts(b)}", e["text"], ""]
    (HERE / f"{out_name}.srt").write_text("\n".join(srt), encoding="utf-8")

    def mmss(s: float) -> str:
        return f"{int(s // 60)}:{int(s % 60):02d}"

    vo = ["# Q-GreenFleet walkthrough: voice-over script", "",
          ("Timestamps match the edited video. Read each line while its caption is on screen "
           "(about 150 words per minute). The on-screen captions already carry the story, so the video also "
           "works without a voice-over."), ""]
    section = None
    cards = [(out_time(e["t"]), e) for e in events if e["type"] == "card"]
    for a, b, e in caps:
        if e["kicker"] != section:
            section = e["kicker"]
            vo += [f"## {section}", ""]
        vo.append(f"**{mmss(a)}–{mmss(b)}**  {e['vo']}")
        vo.append("")
    vo += ["## Title cards", ""]
    for a, e in cards:
        text = (e["html"].replace("<br/>", " ").replace("&middot;", "·").replace("&amp;", "&").replace("&rarr;", "→"))
        text = re.sub(r"<[^>]+>", " ", text.replace("{MARK}", ""))
        vo.append(f"- {mmss(a)}: {' '.join(text.split())}")
    (HERE / f"{out_name}_voiceover.md").write_text("\n".join(vo) + "\n", encoding="utf-8")

    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_name",
                            "-of", "compact", str(mp4)], capture_output=True, text=True, check=False).stdout
    print(probe.strip())
    print(f"frames={len(frames)} captions={len(caps)} ff_spans={len(spans)} holds={[(round(h - t_start, 1), round(x, 1)) for h, x in holds]} "
          f"length={out_time(t_end):.1f}s")


if __name__ == "__main__":
    main()
