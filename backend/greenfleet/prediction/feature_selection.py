"""Quantum-inspired feature selection (QIEA) versus a binary GA and "use everything".

The PS names four mandatory model inputs (speed, load, weather, vessel type); these are
always kept. Selection runs over the remaining candidate features (draft, trim, hull age,
wind/wave components, current, vessel particulars) using a fast LightGBM on validation
MAE plus a small per-feature parsimony penalty.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from greenfleet.classical.single import BinaryGA
from greenfleet.prediction.models import default_lgbm
from greenfleet.quantum.qiea import QIEA

MANDATORY = ["speed_kn", "load_ratio", "wind_speed_ms", "wave_height_m"]


def mandatory_features(candidates: list[str]) -> list[str]:
    keep = [f for f in MANDATORY if f in candidates]
    keep += [f for f in candidates if f.startswith("vt_")]          # vessel type one-hot
    return keep


@dataclass
class SelectionResult:
    method: str
    features: list[str]
    score: float
    history: list[float] = field(default_factory=list)
    evaluations: int = 0
    seconds: float = 0.0


def make_objective(train: pd.DataFrame, val: pd.DataFrame, base: list[str], optional: list[str],
                   y_col: str = "fuel_tpd", penalty: float = 0.002, extra: list[str] | None = None):
    extra = extra or []
    ytr, yva = np.log(train[y_col].to_numpy()), val[y_col].to_numpy()
    cache: dict[bytes, float] = {}

    def score(mask: np.ndarray) -> float:
        key = np.asarray(mask, dtype=np.uint8).tobytes()
        if key in cache:
            return cache[key]
        cols = base + extra + [f for f, m in zip(optional, mask) if m]
        model = default_lgbm(n_estimators=150, learning_rate=0.1, num_leaves=31)
        model.fit(train[cols].to_numpy(dtype=float), ytr)
        pred = np.exp(model.predict(val[cols].to_numpy(dtype=float)))
        mae = float(np.mean(np.abs(pred - yva)))
        cache[key] = mae * (1 + penalty * int(np.sum(mask)))
        return cache[key]

    return score


def select_features(method: str, train: pd.DataFrame, val: pd.DataFrame, candidates: list[str],
                    budget: int = 60, seed: int = 0, extra: list[str] | None = None) -> SelectionResult:
    base = mandatory_features(candidates)
    optional = [f for f in candidates if f not in base]
    obj = make_objective(train, val, base, optional, extra=extra)
    t0 = time.perf_counter()
    if method == "QIEA" and optional:
        res = QIEA(len(optional), pop_size=8, seed=seed).minimize(obj, max_evals=budget)
        mask, score, hist, ev = res.x, res.f, res.history, res.evaluations
    elif method == "GA" and optional:
        res = BinaryGA(len(optional), pop_size=8, seed=seed).minimize(obj, max_evals=budget)
        mask, score, hist, ev = res.x, res.f, res.history, res.evaluations
    else:  # all features
        mask = np.ones(len(optional), dtype=bool)
        score, hist, ev = obj(mask), [], 1
    chosen = base + [f for f, m in zip(optional, mask) if m]
    return SelectionResult(method=method, features=chosen, score=float(score), history=list(hist),
                           evaluations=ev, seconds=time.perf_counter() - t0)
