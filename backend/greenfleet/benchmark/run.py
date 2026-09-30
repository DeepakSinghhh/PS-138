"""Benchmark runner: ``python -m greenfleet.benchmark.run --quick|--full [--only prediction|optimization]``."""

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


def run_optimization(full: bool) -> dict:
    from greenfleet.benchmark import optimization_bench as ob

    res = ob.run(ob.OptBenchConfig.full() if full else ob.OptBenchConfig.quick())
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
    args = ap.parse_args()
    if args.only in (None, "prediction"):
        run_prediction(args.full)
    if args.only in (None, "optimization"):
        run_optimization(args.full)


if __name__ == "__main__":
    main()
