"""Physics priors for fuel-consumption prediction.

* ``NominalPhysics`` - engineering model from vessel-class particulars only (IMO GHG4
  power law + Kwon weather speed loss + SFOC load curve + auxiliary load). It knows
  nothing about an individual ship's hull condition or engine state.
* ``GreyBoxPhysics`` - the same physical structure, but with non-negative coefficients
  fitted per ship by NNLS. Works for datasets without ship particulars (e.g. FuelCast).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from greenfleet.config import fuel_library, vessel_classes
from greenfleet.physics.propulsion import (
    KN_TO_MS,
    kwon_speed_loss,
    propulsion_power_kw,
    sfoc_multiplier,
)

HFO_LCV = 0.0405           # MJ/g
MAIN_BSEC = 7.0            # MJ/kWh, conventional 2-stroke at optimum load
AUX_BSEC = 8.3             # MJ/kWh, 4-stroke auxiliary engines


def _direction_weights(rel_deg: float) -> tuple[float, float, float, float]:
    if rel_deg < 30:
        return (1.0, 0.0, 0.0, 0.0)
    if rel_deg < 60:
        return (0.0, 1.0, 0.0, 0.0)
    if rel_deg < 150:
        return (0.0, 0.0, 1.0, 0.0)
    return (0.0, 0.0, 0.0, 1.0)


def energy_to_hfo_tpd(power_kw: np.ndarray, aux_kw: float, mcr_kw: float) -> np.ndarray:
    main = power_kw * MAIN_BSEC * sfoc_multiplier(power_kw / mcr_kw)
    aux = aux_kw * AUX_BSEC
    return 24.0 * (main + aux) / HFO_LCV / 1e6


class NominalPhysics:
    """Class-level engineering model (needs ``vessel_class`` in the data)."""

    name = "Physics (nominal, IMO GHG4 + Kwon)"

    def fit(self, df: pd.DataFrame, y: np.ndarray | None = None) -> NominalPhysics:
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        out = np.empty(len(df))
        lib = vessel_classes()
        for cls, idx in df.groupby("vessel_class").indices.items():
            vc = lib[cls]
            sub = df.iloc[idx]
            v = sub["speed_kn"].to_numpy()
            dr = _draft_ratio(sub)
            bn = sub["beaufort"].to_numpy() if "beaufort" in sub else np.zeros(len(sub))
            rel = sub["wind_rel_deg"].fillna(90.0).to_numpy()
            laden = dr > 0.8
            wf = np.array([
                1.0 / (1.0 - kwon_speed_loss(b, s, vc, bool(ld), _direction_weights(r))) ** 3
                for b, s, ld, r in zip(bn, v, laden, rel)
            ])
            p = propulsion_power_kw(vc, v, draft_m=dr * vc.design_draft_m, weather_factor=wf)
            p = np.clip(p, 0.05 * vc.mcr_kw, 1.05 * vc.mcr_kw)
            out[idx] = energy_to_hfo_tpd(p, vc.aux_sea_kw, vc.mcr_kw)
        return out


def _draft_ratio(df: pd.DataFrame) -> np.ndarray:
    """Draft ratio, or an estimate from cargo load when draft is not recorded."""
    dr = df["draft_ratio"] if "draft_ratio" in df else pd.Series(np.nan, index=df.index)
    if "load_ratio" in df:
        dr = dr.fillna(0.55 + 0.45 * df["load_ratio"])
    return dr.fillna(1.0).clip(0.3, 1.2).to_numpy()


def physics_basis(df: pd.DataFrame) -> np.ndarray:
    """Physical basis functions: hotel load, calm water, fouling growth, wind, waves."""
    v = df["speed_kn"].to_numpy()
    v_ms = v * KN_TO_MS
    dr = _draft_ratio(df)
    days = df["days_since_cleaning"].fillna(0.0).to_numpy() if "days_since_cleaning" in df else np.zeros(len(df))
    wind = df["wind_speed_ms"].fillna(0.0).to_numpy()
    head_wind = df["head_wind_ms"].fillna(0.0).to_numpy() if "head_wind_ms" in df else np.zeros(len(df))
    wave = df["wave_height_m"].fillna(0.0).to_numpy()
    rel_w = np.deg2rad(df["wave_rel_deg"].fillna(90.0).to_numpy())
    calm = dr**0.66 * v**3
    return np.column_stack([
        np.ones(len(df)),
        calm,
        calm * days / 365.0,
        v_ms * head_wind * (wind + 2 * v_ms),
        v * wave**2 * (np.clip(np.cos(rel_w), 0, None) ** 2 + 0.15),
    ])


class GreyBoxPhysics:
    """Per-ship non-negative least squares on the physics basis."""

    name = "Physics (grey-box NNLS)"

    def __init__(self, group_col: str = "ship_id"):
        self.group_col = group_col
        self.coef_: dict[str, np.ndarray] = {}
        self.global_: np.ndarray | None = None

    def fit(self, df: pd.DataFrame, y: np.ndarray) -> GreyBoxPhysics:
        y = np.asarray(y, dtype=float)
        B = physics_basis(df)
        scale = np.maximum(np.abs(B).max(axis=0), 1e-9)
        self.scale_ = scale
        self.global_ = nnls(B / scale, y)[0]
        for g, idx in df.groupby(self.group_col).indices.items():
            if len(idx) >= 20:
                self.coef_[g] = nnls(B[idx] / scale, y[idx])[0]
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        B = physics_basis(df) / self.scale_
        out = B @ self.global_
        for g, idx in df.groupby(self.group_col).indices.items():
            if g in self.coef_:
                out[idx] = B[idx] @ self.coef_[g]
        return np.maximum(out, 1e-3)


class PolySpeed:
    """Per-ship cubic polynomial in speed: the standard speed-only baseline (FuelCast)."""

    name = "Polynomial speed (baseline)"

    def __init__(self, group_col: str = "ship_id", degree: int = 3):
        self.group_col, self.degree = group_col, degree
        self.coef_: dict[str, np.ndarray] = {}

    def fit(self, df: pd.DataFrame, y: np.ndarray) -> PolySpeed:
        y = np.asarray(y, dtype=float)
        self.global_ = np.polyfit(df["speed_kn"], y, self.degree)
        for g, idx in df.groupby(self.group_col).indices.items():
            if len(idx) > self.degree + 5:
                self.coef_[g] = np.polyfit(df["speed_kn"].to_numpy()[idx], y[idx], self.degree)
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        v = df["speed_kn"].to_numpy()
        out = np.polyval(self.global_, v)
        for g, idx in df.groupby(self.group_col).indices.items():
            if g in self.coef_:
                out[idx] = np.polyval(self.coef_[g], v[idx])
        return out


def hfo_equivalent_to_energy_mj(fuel_tpd: np.ndarray) -> np.ndarray:
    return np.asarray(fuel_tpd) * 1e6 * fuel_library().fuels["HFO"].lcv_mj_per_g
