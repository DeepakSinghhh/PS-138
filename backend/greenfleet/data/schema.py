"""Canonical telemetry schema shared by every data source.

Every loader (FuelCast, the synthetic generator, user uploads) maps its columns onto
these names so the prediction module never needs to know where the data came from.

The PS Delivery Table (item 1) names the required model inputs: **speed, load, weather,
vessel type**. They map onto ``speed_kn``, ``load_ratio`` (cargo load as a fraction of
full load; ``draft_ratio`` is its physical consequence), the weather columns, and
``vessel_type`` (one-hot encoded for the models).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ID_COLS = ["ship_id", "vessel_class", "vessel_type", "timestamp", "source"]

# Exogenous / controllable inputs. Engine power, rpm or *engine* load are excluded
# because they are consequences of the operating point (target leakage), not inputs.
OPERATIONAL = ["speed_kn", "load_ratio", "draft_ratio", "trim_m", "days_since_cleaning"]
WEATHER = ["wind_speed_ms", "wind_rel_deg", "wave_height_m", "wave_rel_deg", "current_kn"]
TARGET = "fuel_tpd"

# Vessel descriptors (present for fleet data, absent for single-ship sources)
DESCRIPTORS = ["design_speed_kn", "mcr_kw", "displacement_t", "length_m", "block_coefficient", "aux_sea_kw"]

# Vessel-type vocabulary; loaders map free-text types onto it
VESSEL_TYPES = ["container", "bulk", "tanker", "pax", "cruise", "offshore", "general_cargo", "other"]
_TYPE_KEYWORDS = [
    ("container", ("container", "feeder", "teu")),
    ("bulk", ("bulk", "ore", "coal", "grain")),
    ("tanker", ("tanker", "crude", "product", "chemical", "oil")),
    ("cruise", ("cruise",)),
    ("pax", ("ro-pax", "ropax", "ro_pax", "passenger", "ferry", "pax")),
    ("offshore", ("offshore", "supply", "osv", "psv", "ahts")),
    ("general_cargo", ("general", "cargo", "multi")),
]


def normalise_vessel_type(value: object) -> str:
    """Map free-text ship types (e.g. 'Bulk carrier', 'Ro-pax ship', 'oss') onto VESSEL_TYPES."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "other"
    text = str(value).strip().lower()
    if text in VESSEL_TYPES:
        return text
    for canon, words in _TYPE_KEYWORDS:
        if any(w in text for w in words):
            return canon
    return "other"


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Physics-motivated derived features and the vessel-type one-hot encoding."""
    out = df.copy()
    wind_rad = np.deg2rad(out["wind_rel_deg"].fillna(90.0))
    wave_rad = np.deg2rad(out["wave_rel_deg"].fillna(90.0))
    wind = out["wind_speed_ms"].fillna(0.0)
    wave = out["wave_height_m"].fillna(0.0)
    out["head_wind_ms"] = wind * np.cos(wind_rad)
    out["cross_wind_ms"] = wind * np.abs(np.sin(wind_rad))
    out["head_wave_m"] = wave * np.clip(np.cos(wave_rad), 0.0, None)
    out["beaufort"] = (wind / 0.836) ** (2.0 / 3.0)
    if "load_ratio" not in out:
        out["load_ratio"] = np.nan
    if "vessel_type" in out:
        types = out["vessel_type"].map(normalise_vessel_type)
        out["vessel_type"] = types
        for t in VESSEL_TYPES:
            out[f"vt_{t}"] = (types == t).astype(float)
    return out


FEATURES_BASE = [
    "speed_kn",
    "load_ratio",
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
    "load_ratio": 1,
    "draft_ratio": 1,
    "days_since_cleaning": 1,
    "wave_height_m": 1,
    "head_wave_m": 1,
    "head_wind_ms": 1,
}


def feature_columns(df: pd.DataFrame, include_descriptors: bool = True) -> list[str]:
    """Model inputs present in ``df``: speed, load, weather (+ vessel type & particulars)."""
    cols = [c for c in FEATURES_BASE if c in df.columns and df[c].notna().any()]
    if include_descriptors:
        cols += [c for c in DESCRIPTORS if c in df.columns and df[c].notna().any() and df[c].nunique() > 1]
        cols += [f"vt_{t}" for t in VESSEL_TYPES if f"vt_{t}" in df.columns and df[f"vt_{t}"].nunique() > 1]
    return cols
