"""Synthesize the voice-over with Kokoro TTS (offline, Apache-2.0) and write narration/manifest.json.

Run with the TTS virtualenv:  <tts-venv>/bin/python narrate.py --model <dir with kokoro-v1.0.onnx + voices-v1.0.bin>
Numbers that depend on the recorded run ({n}, {g}, {f}, {c}, {gap}, {qp}) are read from the on-screen captions.
"""

import argparse
import json
import re
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro

HERE = Path(__file__).parent


def fill(text: str, captions: list[str]) -> str:
    joined = "\n".join(captions)
    vals = {}
    if m := re.search(r"Done: (\d+) Pareto", joined):
        vals["n"] = m.group(1)
    if m := re.search(r"(\d+) % less well-to-wake GHG, (\d+) % less fuel and (\d+) % lower cost", joined):
        vals.update(g=m.group(1), f=m.group(2), c=m.group(3))
    if m := re.search(r"Annealed plan: ([\d.]+)%", joined):
        vals["gap"] = m.group(1)
    if m := re.search(r"the best plan in (\d+)% of shots", joined):
        vals["qp"] = m.group(1)
    return text.format(**vals)


def to_speech(text: str, say: dict[str, str]) -> str:
    for k in sorted(say, key=len, reverse=True):
        text = re.sub(rf"(?<![\w-]){re.escape(k)}(?![\w-])", say[k], text)
    # read decimals digit by digit ("1.52" -> "1 point 5 2"); the voice otherwise pauses at the dot
    return re.sub(r"(\d+)\.(\d+)", lambda m: f"{m.group(1)} point {' '.join(m.group(2))}", text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(HERE))
    args = ap.parse_args()
    cfg = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))
    events = json.loads((HERE / "timeline.json").read_text())["events"]
    captions = [e["text"] for e in events if e["type"] == "caption"]
    n_cards = sum(1 for e in events if e["type"] == "card")
    assert len(captions) == len(cfg["captions"]), (len(captions), len(cfg["captions"]))
    assert n_cards == len(cfg["cards"]), (n_cards, len(cfg["cards"]))

    tts = Kokoro(str(Path(args.model) / "kokoro-v1.0.onnx"), str(Path(args.model) / "voices-v1.0.bin"))
    out = HERE / "narration"
    out.mkdir(exist_ok=True)
    manifest = []
    for kind, lines in (("card", cfg["cards"]), ("caption", cfg["captions"])):
        for i, line in enumerate(lines):
            text = fill(line, captions)
            speech = to_speech(text, cfg["say"])
            samples, sr = tts.create(speech, voice=cfg["voice"], speed=cfg["speed"], lang="en-us")
            path = out / f"{kind}_{i:02d}.wav"
            sf.write(path, samples, sr)
            manifest.append({"kind": kind, "index": i, "file": path.name, "sr": sr,
                             "duration": round(len(samples) / sr, 3), "text": text, "speech": speech})
            print(f"{kind} {i:02d} {len(samples) / sr:5.1f}s  {text}")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
