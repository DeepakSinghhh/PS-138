"""Prediction model zoo with a common DataFrame interface, plus splits and metrics."""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from greenfleet.prediction.mps import MPSRegressor
from greenfleet.prediction.physics_model import CalibratedPrior, NominalPhysics, PolySpeed


# ------------------------------------------------------------------ splits
@dataclass
class Split:
    train: pd.DataFrame
    val: pd.DataFrame
    cal: pd.DataFrame
    test: pd.DataFrame


def chronological_split(df: pd.DataFrame, fracs=(0.60, 0.15, 0.10, 0.15), group: str = "ship_id") -> Split:
    """Per-ship forward-in-time split: train | validation | conformal calibration | test."""
    parts: dict[str, list[pd.DataFrame]] = {"train": [], "val": [], "cal": [], "test": []}
    edges = np.cumsum((0.0,) + tuple(fracs))
    for _, g in df.groupby(group, sort=False):
        g = g.sort_values("timestamp") if "timestamp" in g and g["timestamp"].notna().any() else g
        n = len(g)
        cuts = (edges * n).astype(int)
        for name, a, b in zip(parts, cuts[:-1], cuts[1:]):
            parts[name].append(g.iloc[a:b])
    return Split(**{k: pd.concat(v).reset_index(drop=True) for k, v in parts.items()})


def holdout_split(df: pd.DataFrame, test_mask: pd.Series, seed: int = 0) -> Split:
    """Train on ships/classes outside ``test_mask``; validation/calibration drawn from the training pool."""
    pool = df[~test_mask].sample(frac=1.0, random_state=seed).reset_index(drop=True)
    n = len(pool)
    return Split(
        train=pool.iloc[: int(0.75 * n)].reset_index(drop=True),
        val=pool.iloc[int(0.75 * n): int(0.88 * n)].reset_index(drop=True),
        cal=pool.iloc[int(0.88 * n):].reset_index(drop=True),
        test=df[test_mask].reset_index(drop=True),
    )


# ------------------------------------------------------------------ metrics
def metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    y, p = np.asarray(y, float), np.asarray(p, float)
    err = p - y
    return {
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err**2))),
        "MAPE": float(np.mean(np.abs(err) / np.maximum(np.abs(y), 1e-9)) * 100),
        "R2": float(1 - np.sum(err**2) / np.sum((y - y.mean()) ** 2)),
    }


# ------------------------------------------------------------------ wrappers
class FeatureModel:
    """Wraps an estimator trained on a feature subset, optionally on log(fuel)."""

    def __init__(self, name: str, estimator, features: list[str], log_target: bool = False):
        self.name, self.estimator, self.features, self.log_target = name, estimator, features, log_target

    def fit(self, df: pd.DataFrame, y: np.ndarray, val_df: pd.DataFrame | None = None, y_val=None):
        yt = np.log(y) if self.log_target else y
        self.fill_ = np.nan_to_num(np.nanmedian(df[self.features].to_numpy(dtype=float), axis=0))
        X = df[self.features].to_numpy(dtype=float)
        X = np.where(np.isnan(X), self.fill_, X)
        if isinstance(self.estimator, MPSRegressor) and val_df is not None:
            Xv = np.where(np.isnan(val_df[self.features].to_numpy(dtype=float)), self.fill_, val_df[self.features].to_numpy(dtype=float))
            self.estimator.fit(X, yt, Xv, np.log(y_val) if self.log_target else y_val)
        else:
            self.estimator.fit(X, yt)
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        X = df[self.features].to_numpy(dtype=float)
        X = np.where(np.isnan(X), self.fill_, X)
        p = self.estimator.predict(X)
        return np.exp(p) if self.log_target else p


class RidgeCubic(FeatureModel):
    """Linear model with a physics-motivated cubic speed term."""

    def __init__(self, features: list[str]):
        super().__init__("Ridge regression", make_pipeline(StandardScaler(), Ridge(alpha=1.0)), features)

    def _aug(self, df):
        out = df.copy()
        out["speed_cubed"] = out["speed_kn"] ** 3
        return out

    def fit(self, df, y, val_df=None, y_val=None):
        self.features = self.features + ["speed_cubed"] if "speed_cubed" not in self.features else self.features
        return super().fit(self._aug(df), y)

    def predict(self, df):
        return super().predict(self._aug(df))


def default_lgbm(**kw) -> lgb.LGBMRegressor:
    params = {"n_estimators": 400, "learning_rate": 0.05, "num_leaves": 31, "verbose": -1, "n_jobs": 4}
    params.update(kw)
    return lgb.LGBMRegressor(**params)


def model_zoo(features: list[str], has_classes: bool, seed: int = 0) -> dict[str, object]:
    """Conventional baselines + the stand-alone quantum-inspired MPS model."""
    zoo: dict[str, object] = {
        "Polynomial speed (baseline)": PolySpeed(),
        "Physics (grey-box / calibrated)": CalibratedPrior(),
    }
    if has_classes:
        zoo["Physics (nominal, IMO GHG4 + Kwon)"] = NominalPhysics()
    zoo.update({
        "Ridge regression": RidgeCubic(list(features)),
        "Random forest": FeatureModel(
            "Random forest",
            RandomForestRegressor(n_estimators=200, min_samples_leaf=3, n_jobs=4, random_state=seed),
            features,
        ),
        "LightGBM (default)": FeatureModel("LightGBM (default)", default_lgbm(random_state=seed), features),
        "MLP neural net": FeatureModel(
            "MLP neural net",
            make_pipeline(StandardScaler(), MLPRegressor(hidden_layer_sizes=(64, 64), early_stopping=True,
                                                         max_iter=300, random_state=seed)),
            features, log_target=True,
        ),
        "MPS tensor network (stand-alone)": FeatureModel(
            "MPS tensor network (stand-alone)", MPSRegressor(bond_dim=8, local_dim=5, sweeps=4, seed=seed),
            features, log_target=True,
        ),
    })
    return zoo


def fit_predict(model, split: Split, y_col: str = "fuel_tpd") -> np.ndarray:
    tr, va = split.train, split.val
    try:
        model.fit(tr, tr[y_col].to_numpy(), va, va[y_col].to_numpy())
    except TypeError:
        model.fit(tr, tr[y_col].to_numpy())
    return model.predict(split.test)
