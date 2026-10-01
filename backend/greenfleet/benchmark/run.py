"""Benchmark runner: ``python -m greenfleet.benchmark.run [--quick|--full] [--only prediction|optimization] [--resume]``.

Without a flag the optimization benchmark uses its published configuration (10 seeds); --quick is a smoke run.
"""

from __future__ import annotations

import argparse
import json

from greenfleet.benchmark import report
from greenfleet.config import REPORTS_DIR


def run_prediction(full: bool) -> dict:
    from greenfleet.benchmark import prediction_bench as pb

    cfg = pb.BenchConfig.full() if full else pb.BenchConfig.quick()
    res = pb.run(cfg)
    figs = report.prediction_figures(res)
    (REPORTS_DIR).mkdir(parents=True, exist_ok=True)
    with open(REPORTS_DIR / "prediction_benchmark.json", "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    report.write(REPORTS_DIR / "prediction_benchmark.md", report.prediction_markdown(res, figs))
    return res


def run_optimization(full: bool, quick: bool = False, resume: bool = False) -> dict:
    from greenfleet.benchmark import optimization_bench as ob

    cfg = ob.OptBenchConfig.full() if full else ob.OptBenchConfig.quick() if quick else ob.OptBenchConfig()
    partial = REPORTS_DIR / "optimization_benchmark.partial.json"
    prev = json.loads(partial.read_text()) if resume and partial.exists() else None
    res = ob.run(cfg, resume=prev)
    figs = report.optimization_figures(res)
    with open(REPORTS_DIR / "optimization_benchmark.json", "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    report.write(REPORTS_DIR / "optimization_benchmark.md", report.optimization_markdown(res, figs))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true")
    mode.add_argument("--full", action="store_true")
    ap.add_argument("--only", choices=["prediction", "optimization"])
    ap.add_argument("--resume", action="store_true", help="continue the optimization benchmark from its checkpoint")
    args = ap.parse_args()
    if args.only in (None, "prediction"):
        run_prediction(args.full)
    if args.only in (None, "optimization"):
        run_optimization(args.full, args.quick, args.resume)


if __name__ == "__main__":
    main()
