"""Train the production Q-PHYS model: ``python -m greenfleet.prediction.train``.

Artifacts (``backend/artifacts``):
    qphys.joblib            trained model (prior + booster + MPS + conformal calibrator)
    qphys_meta.json         test metrics, conformal coverage, SHAP importance, MPS report
    fuel_surrogate.json     correction table consumed by the fleet optimizer
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import warnings

import joblib
import pandas as pd

from greenfleet.config import ARTIFACTS_DIR, DATA_DIR
from greenfleet.data.schema import add_derived, feature_columns
from greenfleet.prediction.hybrid import QPhys
from greenfleet.prediction.models import chronological_split, metrics
from greenfleet.prediction.surrogate import build_surrogate, save_surrogate

log = logging.getLogger(__name__)
MODEL_PATH = ARTIFACTS_DIR / "qphys.joblib"
META_PATH = ARTIFACTS_DIR / "qphys_meta.json"


def load_training_frame() -> pd.DataFrame:
    path = DATA_DIR / "processed" / "synthetic_fleet.parquet"
    if not path.exists():
        from greenfleet.data.build import build

        build()
    return add_derived(pd.read_parquet(path))


def train(tune_budget: int = 20, select_budget: int = 40, seed: int = 0) -> dict:
    warnings.filterwarnings("ignore", category=UserWarning)
    df = load_training_frame()
    split = chronological_split(df)
    feats = feature_columns(df, include_descriptors=True)
    t0 = time.perf_counter()
    model = QPhys(features=feats, tune_budget=tune_budget, select_budget=select_budget, seed=seed)
    model.fit(split.train, split.train["fuel_tpd"].to_numpy(), split.val, split.val["fuel_tpd"].to_numpy(),
              split.cal, split.cal["fuel_tpd"].to_numpy())
    y = split.test["fuel_tpd"].to_numpy()
    pred = model.predict(split.test)
    pred_m = model.predict_monotone(split.test)
    by_type = {
        t: metrics(y[idx], pred[idx])
        for t, idx in split.test.groupby("vessel_type").indices.items()
    }
    meta = {
        "trained_seconds": time.perf_counter() - t0,
        "rows": {"train": len(split.train), "val": len(split.val), "cal": len(split.cal), "test": len(split.test)},
        "features": feats,
        "selected_features": model.selected_,
        "test_metrics": metrics(y, pred),
        "test_metrics_monotone": metrics(y, pred_m),
        "test_metrics_by_vessel_type": by_type,
        "conformal": model.interval_coverage(split.test, y),
        "feature_importance": model.feature_importance(split.test),
        "report": model.report,
        "data_source": "synthetic (physics-informed); FuelCast used when present in data/raw/fuelcast",
    }
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    save_surrogate(build_surrogate(model))
    with open(META_PATH, "w") as fh:
        json.dump(meta, fh, indent=2, default=float)
    return meta


def load_model() -> QPhys | None:
    return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune-budget", type=int, default=20)
    ap.add_argument("--select-budget", type=int, default=40)
    args = ap.parse_args()
    m = train(args.tune_budget, args.select_budget)
    print(json.dumps({k: m[k] for k in ("test_metrics", "test_metrics_monotone", "conformal", "selected_features")},
                     indent=2, default=float))
