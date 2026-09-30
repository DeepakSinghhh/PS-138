"""Prediction benchmark: Q-PHYS versus conventional models (PS objective 5).

Scenarios
    A  known ships      - per-ship chronological split (train on the past, test on the future)
    B  unseen ships     - one ship of every class held out entirely
    C  unseen classes   - whole vessel classes held out (extrapolation to new ship designs)
    D  FuelCast         - real 3-ship dataset, per-ship chronological (when data/raw/fuelcast exists)
Plus tuner convergence (QPSO vs PSO/GA/TPE/random/grid, equal budget), feature selection
(QIEA vs GA vs all features) and Wilcoxon signed-rank tests on per-ship errors.
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from greenfleet.config import DATA_DIR
from greenfleet.data.schema import add_derived, feature_columns
from greenfleet.prediction.feature_selection import select_features
from greenfleet.prediction.hybrid import QPhys
from greenfleet.prediction.models import Split, chronological_split, fit_predict, holdout_split, metrics, model_zoo
from greenfleet.prediction.tuning import LGBM_SPACE, TUNERS, tune

QPHYS = "Q-PHYS (quantum-inspired hybrid)"
QPHYS_M = "Q-PHYS-M (certified monotone)"


@dataclass
class BenchConfig:
    tune_budget: int = 12
    select_budget: int = 24
    tuner_budget: int = 15
    tuner_seeds: int = 1
    fs_seeds: int = 1
    max_train_rows: int = 15000
    classes_out: tuple[str, ...] = ("PANAMAX_C", "SUPRAMAX", "MR_TANKER")

    @classmethod
    def quick(cls) -> BenchConfig:
        return cls()

    @classmethod
    def full(cls) -> BenchConfig:
        return cls(tune_budget=30, select_budget=60, tuner_budget=30, tuner_seeds=5, fs_seeds=3,
                   max_train_rows=40000, classes_out=("FEEDER", "PANAMAX_C", "SUPRAMAX", "MR_TANKER", "ISLAND_ROPAX"))


def _cap(split: Split, n: int, seed: int = 0) -> Split:
    if len(split.train) <= n:
        return split
    return Split(split.train.sample(n, random_state=seed).reset_index(drop=True), split.val, split.cal, split.test)


def per_group_mae(df: pd.DataFrame, pred: np.ndarray, group: str = "ship_id") -> dict[str, float]:
    err = np.abs(pred - df["fuel_tpd"].to_numpy())
    return {g: float(err[idx].mean()) for g, idx in df.groupby(group).indices.items()}


def run_scenario(name: str, split: Split, feats: list[str], has_classes: bool, cfg: BenchConfig,
                 seed: int = 0) -> dict:
    split = _cap(split, cfg.max_train_rows, seed)
    y = split.test["fuel_tpd"].to_numpy()
    rows, per_ship, preds = [], {}, {}
    for mname, model in model_zoo(feats, has_classes, seed).items():
        t0 = time.perf_counter()
        try:
            p = fit_predict(model, split)
        except Exception as exc:  # a baseline failing must not kill the benchmark
            rows.append({"model": mname, "error": str(exc)})
            continue
        rows.append({"model": mname, **metrics(y, p), "seconds": time.perf_counter() - t0})
        per_ship[mname] = per_group_mae(split.test, p)
        preds[mname] = p
    t0 = time.perf_counter()
    q = QPhys(features=feats, tune_budget=cfg.tune_budget, select_budget=cfg.select_budget, seed=seed)
    q.fit(split.train, split.train["fuel_tpd"].to_numpy(), split.val, split.val["fuel_tpd"].to_numpy(),
          split.cal, split.cal["fuel_tpd"].to_numpy())
    secs = time.perf_counter() - t0
    for label, p in ((QPHYS, q.predict(split.test)), (QPHYS_M, q.predict_monotone(split.test))):
        rows.append({"model": label, **metrics(y, p), "seconds": secs})
        per_ship[label] = per_group_mae(split.test, p)
        preds[label] = p
    conformal = q.interval_coverage(split.test, y)
    by_type = {}
    if "vessel_type" in split.test:
        for t, idx in split.test.groupby("vessel_type").indices.items():
            by_type[t] = {m: metrics(y[idx], p[idx])["MAPE"] for m, p in preds.items()}
    # Wilcoxon signed-rank: Q-PHYS vs each baseline on per-ship MAE
    tests = {}
    ships = sorted(per_ship[QPHYS])
    for mname, errs in per_ship.items():
        if mname in (QPHYS, QPHYS_M) or len(ships) < 5:
            continue
        a = np.array([per_ship[QPHYS][s] for s in ships])
        b = np.array([errs.get(s, np.nan) for s in ships])
        ok = ~np.isnan(b)
        if ok.sum() >= 5 and np.any(a[ok] != b[ok]):
            res = stats.wilcoxon(a[ok], b[ok], alternative="less")
            tests[mname] = {"p_value": float(res.pvalue), "ships": int(ok.sum()),
                            "qphys_better_on": int(np.sum(a[ok] < b[ok]))}
    rows.sort(key=lambda r: r.get("MAPE", np.inf))
    return {
        "scenario": name,
        "rows": {"train": len(split.train), "test": len(split.test)},
        "ships_in_test": len(ships),
        "results": rows,
        "conformal": conformal,
        "mape_by_vessel_type": by_type,
        "wilcoxon_vs_qphys": tests,
        "qphys_report": {k: v for k, v in q.report.items() if k != "gbm_tuning"},
    }


def run_tuners(split: Split, feats: list[str], cfg: BenchConfig) -> dict:
    """Equal-budget hyperparameter search for the physics-informed booster."""
    import lightgbm as lgb

    from greenfleet.prediction.physics_model import CalibratedPrior

    split = _cap(split, cfg.max_train_rows)
    prior = CalibratedPrior().fit(split.train, split.train["fuel_tpd"].to_numpy())
    cols = feats + ["log_prior"]

    def frame(df):
        d = df.copy()
        d["log_prior"] = np.log(prior.predict(df))
        return d[cols].to_numpy(dtype=float)

    Xtr, Xva = frame(split.train), frame(split.val)
    ytr, yva = np.log(split.train["fuel_tpd"].to_numpy()), split.val["fuel_tpd"].to_numpy()

    def objective(params: dict) -> float:
        m = lgb.LGBMRegressor(n_estimators=600, verbose=-1, n_jobs=4, subsample_freq=1, **params)
        m.fit(Xtr, ytr, eval_X=(Xva,), eval_y=(np.log(yva),), callbacks=[lgb.early_stopping(40, verbose=False)])
        return float(np.mean(np.abs(np.exp(m.predict(Xva)) - yva)))

    out = {}
    for tuner in TUNERS:
        runs = [tune(tuner, LGBM_SPACE, objective, budget=cfg.tuner_budget, seed=s) for s in range(cfg.tuner_seeds)]
        hist = np.array([r.history for r in runs])
        finals = hist[:, -1]
        # convergence speed: evaluations needed to get within 1 % of the best score any tuner found
        out[tuner] = {"best_val_mae_mean": float(finals.mean()), "best_val_mae_std": float(finals.std()),
                      "mean_history": hist.mean(axis=0).tolist(), "seconds": float(np.mean([r.seconds for r in runs])),
                      "best_params": runs[int(np.argmin(finals))].best_params}
    global_best = min(v["best_val_mae_mean"] for v in out.values())
    for v in out.values():
        h = np.array(v["mean_history"])
        hit = np.nonzero(h <= global_best * 1.01)[0]
        v["evals_to_within_1pct"] = int(hit[0] + 1) if len(hit) else None
    return out


def run_feature_selection(split: Split, feats: list[str], cfg: BenchConfig) -> dict:
    from greenfleet.prediction.physics_model import CalibratedPrior

    split = _cap(split, cfg.max_train_rows)
    prior = CalibratedPrior().fit(split.train, split.train["fuel_tpd"].to_numpy())
    tr, va = split.train.copy(), split.val.copy()
    tr["log_prior"] = np.log(prior.predict(tr))
    va["log_prior"] = np.log(prior.predict(va))
    out = {}
    for method in ("QIEA", "GA", "All features"):
        runs = [select_features(method, tr, va, feats, budget=cfg.select_budget, seed=s, extra=["log_prior"])
                for s in range(cfg.fs_seeds if method != "All features" else 1)]
        best = min(runs, key=lambda r: r.score)
        out[method] = {"score_mean": float(np.mean([r.score for r in runs])), "best_features": best.features,
                       "n_features": len(best.features), "evaluations": int(np.mean([r.evaluations for r in runs])),
                       "history": best.history}
    return out


def load_synthetic() -> pd.DataFrame:
    path = DATA_DIR / "processed" / "synthetic_fleet.parquet"
    if not path.exists():
        from greenfleet.data.build import build

        build()
    return add_derived(pd.read_parquet(path))


def run(cfg: BenchConfig | None = None, log=print) -> dict:
    warnings.filterwarnings("ignore")
    cfg = cfg or BenchConfig.quick()
    t0 = time.perf_counter()
    df = load_synthetic()
    feats = feature_columns(df, include_descriptors=True)
    out: dict = {"config": cfg.__dict__, "features": feats, "scenarios": {}}

    log("[prediction] scenario A: known ships (chronological)")
    split_a = chronological_split(df)
    out["scenarios"]["A_known_ships"] = run_scenario("Known ships, future period", split_a, feats, True, cfg)

    log("[prediction] scenario B: unseen ships")
    unseen = df["ship_id"].str.endswith("-02")
    out["scenarios"]["B_unseen_ships"] = run_scenario("Unseen ships of known classes", holdout_split(df, unseen),
                                                      feats, True, cfg)

    log("[prediction] scenario C: unseen vessel classes")
    held = df["vessel_class"].isin(cfg.classes_out)
    out["scenarios"]["C_unseen_classes"] = run_scenario(f"Unseen classes {', '.join(cfg.classes_out)}",
                                                        holdout_split(df, held), feats, True, cfg)

    fc_path = DATA_DIR / "processed" / "fuelcast.parquet"
    if fc_path.exists():
        log("[prediction] scenario D: FuelCast (real data)")
        fc = add_derived(pd.read_parquet(fc_path))
        fc_feats = feature_columns(fc, include_descriptors=False)
        out["scenarios"]["D_fuelcast"] = run_scenario("FuelCast (real, 3 ships)", chronological_split(fc),
                                                      fc_feats, False, cfg)
    else:
        out["scenarios"]["D_fuelcast"] = {"skipped": "place FuelCast files in data/raw/fuelcast and run make data"}

    log("[prediction] tuner convergence")
    out["tuners"] = run_tuners(split_a, feats, cfg)
    log("[prediction] feature selection")
    out["feature_selection"] = run_feature_selection(split_a, feats, cfg)
    out["seconds"] = time.perf_counter() - t0
    return out
