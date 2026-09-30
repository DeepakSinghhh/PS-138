"""Canonical telemetry schema shared by every data source.

Every loader (FuelCast, the synthetic generator, user uploads) maps its columns onto
these names so the prediction module never needs to know where the data came from.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ID_COLS = ["ship_id", "vessel_class", "timestamp", "source"]

# Exogenous / controllable inputs (no leakage: engine power, rpm or load are excluded
# because they are consequences of the operating point, not inputs to it).
OPERATIONAL = ["speed_kn", "draft_ratio", "trim_m", "days_since_cleaning"]
WEATHER = ["wind_speed_ms", "wind_rel_deg", "wave_height_m", "wave_rel_deg", "current_kn"]
TARGET = "fuel_tpd"

# Vessel descriptors (present for fleet data, absent for single-ship sources)
DESCRIPTORS = ["design_speed_kn", "mcr_kw", "displacement_t", "length_m", "block_coefficient", "aux_sea_kw"]


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Physics-motivated derived features (all computed from canonical columns)."""
    out = df.copy()
    wind_rad = np.deg2rad(out["wind_rel_deg"].fillna(90.0))
    wave_rad = np.deg2rad(out["wave_rel_deg"].fillna(90.0))
    wind = out["wind_speed_ms"].fillna(0.0)
    wave = out["wave_height_m"].fillna(0.0)
    out["head_wind_ms"] = wind * np.cos(wind_rad)
    out["cross_wind_ms"] = wind * np.abs(np.sin(wind_rad))
    out["head_wave_m"] = wave * np.clip(np.cos(wave_rad), 0.0, None)
    out["beaufort"] = (wind / 0.836) ** (2.0 / 3.0)
    return out


FEATURES_BASE = [
    "speed_kn",
    "draft_ratio",
    "trim_m",
    "days_since_cleaning",
    "wind_speed_ms",
    "head_wind_ms",
    "cross_wind_ms",
    "wave_height_m",
    "head_wave_m",
    "current_kn",
]

# Monotone direction of fuel consumption w.r.t. each feature (+1 non-decreasing, 0 free)
MONOTONE = {
    "speed_kn": 1,
    "draft_ratio": 1,
    "days_since_cleaning": 1,
    "wave_height_m": 1,
    "head_wave_m": 1,
    "head_wind_ms": 1,
}


def feature_columns(df: pd.DataFrame, include_descriptors: bool = True) -> list[str]:
    cols = [c for c in FEATURES_BASE if c in df.columns and df[c].notna().any()]
    if include_descriptors:
        cols += [c for c in DESCRIPTORS if c in df.columns and df[c].notna().any() and df[c].nunique() > 1]
    return cols
