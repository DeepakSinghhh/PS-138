"""Loaders for public datasets, with alias-based column mapping and graceful fallback.

Each loader looks for files under ``data/raw/<dataset>/``. When the folder is empty
(e.g. the host is blocked from this environment) the loader returns ``None`` and the
caller falls back to the synthetic generator, so the pipeline always runs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from greenfleet.config import DATA_DIR

log = logging.getLogger(__name__)
RAW = DATA_DIR / "raw"

# alias lists are matched case-insensitively against normalised column names
FUELCAST_ALIASES: dict[str, list[str]] = {
    "timestamp": ["timestamp", "time", "datetime", "date", "utc", "date_time"],
    "speed_kn": ["speed_through_water", "stw", "speed_log", "log_speed", "speed_kn", "speed",
                 "speed_over_ground", "sog", "vessel_speed"],
    "draft": ["draft_mean", "mean_draft", "draft", "draught", "mean_draught", "draught_mean"],
    "draft_fwd": ["draft_fwd", "draft_fore", "draught_fore", "draft_forward"],
    "draft_aft": ["draft_aft", "draught_aft"],
    "trim_m": ["trim"],
    "wind_speed_ms": ["wind_speed", "true_wind_speed", "windspeed", "wind_speed_10m", "wind"],
    "wind_dir_deg": ["wind_direction", "true_wind_direction", "wind_dir", "winddirection"],
    "wave_height_m": ["significant_wave_height", "wave_height", "swh", "hs", "wave_significant_height"],
    "wave_dir_deg": ["wave_direction", "mean_wave_direction", "mwd", "wave_dir"],
    "current_speed": ["current_speed", "sea_current_speed", "current", "ocean_current_speed"],
    "current_dir_deg": ["current_direction", "current_dir"],
    "heading_deg": ["heading", "true_heading", "course", "cog", "course_over_ground"],
    "fuel": ["fuel_consumption", "total_fuel_consumption", "fuel_consumption_total", "fuel", "foc",
             "fuel_oil_consumption", "fc", "consumption"],
}

# columns that would leak the target (consequences of the operating point)
LEAKAGE = re.compile(r"power|rpm|torque|engine_load|shaft|sfoc|flow|consumption_me|consumption_ae")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def match_columns(columns: list[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    """Map canonical names to source columns (exact alias match first, then prefix match)."""
    norm = {_norm(c): c for c in columns}
    out: dict[str, str] = {}
    used: set[str] = set()
    for canon, names in aliases.items():
        for alias in names:
            if alias in norm and norm[alias] not in used:
                out[canon] = norm[alias]
                used.add(norm[alias])
                break
        else:
            for alias in names:
                hit = next((orig for n, orig in norm.items() if n.startswith(alias) and orig not in used), None)
                if hit:
                    out[canon] = hit
                    used.add(hit)
                    break
    return out


def _relative_angle(direction_deg: pd.Series, heading_deg: pd.Series | None) -> pd.Series:
    """Relative angle in [0, 180]: 0 = coming from ahead (meteorological 'from' convention)."""
    if heading_deg is None:
        rel = direction_deg % 360
    else:
        rel = (direction_deg - heading_deg) % 360
    return rel.where(rel <= 180, 360 - rel)


def _read_any(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def _files(folder: Path, patterns=("*.parquet", "*.csv", "*.xlsx")) -> list[Path]:
    if not folder.exists():
        return []
    files: list[Path] = []
    for pat in patterns:
        files += sorted(folder.rglob(pat))
    return files


def canonicalise_telemetry(df: pd.DataFrame, ship_id: str, source: str) -> pd.DataFrame:
    m = match_columns(list(df.columns), FUELCAST_ALIASES)
    if "speed_kn" not in m or "fuel" not in m:
        raise ValueError(f"could not identify speed/fuel columns in {list(df.columns)[:20]}")
    out = pd.DataFrame(index=df.index)
    out["ship_id"] = ship_id
    out["vessel_class"] = None
    out["source"] = source
    out["timestamp"] = pd.to_datetime(df[m["timestamp"]], errors="coerce") if "timestamp" in m else pd.NaT
    out["speed_kn"] = pd.to_numeric(df[m["speed_kn"]], errors="coerce")
    if "draft" in m:
        draft = pd.to_numeric(df[m["draft"]], errors="coerce")
    elif "draft_fwd" in m and "draft_aft" in m:
        draft = (pd.to_numeric(df[m["draft_fwd"]], errors="coerce") + pd.to_numeric(df[m["draft_aft"]], errors="coerce")) / 2
    else:
        draft = pd.Series(np.nan, index=df.index)
    ref = draft.quantile(0.95) if draft.notna().any() else np.nan
    out["draft_ratio"] = draft / ref if ref and ref > 0 else np.nan
    if "trim_m" in m:
        out["trim_m"] = pd.to_numeric(df[m["trim_m"]], errors="coerce")
    elif "draft_fwd" in m and "draft_aft" in m:
        out["trim_m"] = pd.to_numeric(df[m["draft_aft"]], errors="coerce") - pd.to_numeric(df[m["draft_fwd"]], errors="coerce")
    else:
        out["trim_m"] = np.nan
    heading = pd.to_numeric(df[m["heading_deg"]], errors="coerce") if "heading_deg" in m else None
    out["wind_speed_ms"] = pd.to_numeric(df[m["wind_speed_ms"]], errors="coerce") if "wind_speed_ms" in m else np.nan
    out["wind_rel_deg"] = (
        _relative_angle(pd.to_numeric(df[m["wind_dir_deg"]], errors="coerce"), heading) if "wind_dir_deg" in m else np.nan
    )
    out["wave_height_m"] = pd.to_numeric(df[m["wave_height_m"]], errors="coerce") if "wave_height_m" in m else np.nan
    out["wave_rel_deg"] = (
        _relative_angle(pd.to_numeric(df[m["wave_dir_deg"]], errors="coerce"), heading) if "wave_dir_deg" in m else np.nan
    )
    if "current_speed" in m:
        cur = pd.to_numeric(df[m["current_speed"]], errors="coerce")
        if "current_dir_deg" in m and heading is not None:
            # 'towards' convention for currents: positive = pushing the ship ahead
            cur = cur * np.cos(np.deg2rad(pd.to_numeric(df[m["current_dir_deg"]], errors="coerce") - heading))
        out["current_kn"] = cur
    else:
        out["current_kn"] = np.nan
    ts = out["timestamp"]
    out["days_since_cleaning"] = (ts - ts.min()).dt.total_seconds() / 86400.0 if ts.notna().any() else np.nan
    fuel = pd.to_numeric(df[m["fuel"]], errors="coerce")
    col = _norm(m["fuel"])
    if "kg_h" in col or "kgh" in col or "kg_per_h" in col:
        fuel = fuel * 24 / 1000.0
    elif "t_h" in col or "mt_h" in col:
        fuel = fuel * 24
    out["fuel_tpd"] = fuel
    out.attrs["column_map"] = m
    out = out[(out["speed_kn"] > 3.0) & (out["fuel_tpd"] > 0)]
    return out.dropna(subset=["speed_kn", "fuel_tpd"]).reset_index(drop=True)


def load_fuelcast(folder: Path | None = None) -> pd.DataFrame | None:
    """FuelCast (huggingface.co/datasets/krohnedigital/FuelCast): one file per ship."""
    folder = folder or RAW / "fuelcast"
    files = _files(folder)
    if not files:
        log.info("FuelCast not found in %s - using synthetic data only", folder)
        return None
    frames = []
    for f in files:
        try:
            frames.append(canonicalise_telemetry(_read_any(f), ship_id=f.stem, source="fuelcast"))
        except Exception as exc:  # keep going with the other files
            log.warning("skipping %s: %s", f.name, exc)
    return pd.concat(frames, ignore_index=True) if frames else None


# ------------------------------------------------------------------ EU MRV (THETIS)
MRV_ALIASES = {
    "imo": ["imo_number", "imo"],
    "ship_type": ["ship_type"],
    "year": ["reporting_period", "year"],
    "fuel_t": ["total_fuel_consumption_m_tonnes", "total_fuel_consumption"],
    "co2_t": ["total_co_emissions_m_tonnes", "total_co2_emissions_m_tonnes", "total_co2_emissions"],
    "hours_at_sea": ["annual_total_time_spent_at_sea_hours", "time_spent_at_sea"],
    "fuel_per_nm_kg": ["annual_average_fuel_consumption_per_distance_kg_n_mile", "fuel_consumption_per_distance"],
}


def load_mrv(folder: Path | None = None) -> pd.DataFrame | None:
    """EU MRV public emission reports (THETIS-MRV export)."""
    folder = folder or RAW / "mrv"
    files = _files(folder)
    if not files:
        return None
    frames = []
    for f in files:
        df = _read_any(f)
        # THETIS exports carry a few title rows above the header
        if not any("imo" in _norm(c) for c in df.columns):
            for skip in range(1, 6):
                df = pd.read_excel(f, skiprows=skip) if f.suffix in (".xlsx", ".xls") else pd.read_csv(f, skiprows=skip)
                if any("imo" in _norm(c) for c in df.columns):
                    break
        m = match_columns(list(df.columns), MRV_ALIASES)
        if "ship_type" not in m or "fuel_t" not in m:
            log.warning("MRV file %s: missing required columns", f.name)
            continue
        out = pd.DataFrame({k: df[v] for k, v in m.items()})
        for c in ("fuel_t", "co2_t", "hours_at_sea", "fuel_per_nm_kg"):
            if c in out:
                out[c] = pd.to_numeric(out[c], errors="coerce")
        if "fuel_per_nm_kg" in out and "fuel_t" in out:
            out["distance_nm"] = out["fuel_t"] * 1000 / out["fuel_per_nm_kg"]
        frames.append(out)
    return pd.concat(frames, ignore_index=True) if frames else None


def mrv_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Fuel-per-distance distribution by ship type (for validating the vessel library)."""
    g = df.dropna(subset=["fuel_per_nm_kg"]).groupby("ship_type")["fuel_per_nm_kg"]
    return pd.DataFrame(
        {"ships": g.size(), "p10": g.quantile(0.1), "p50": g.median(), "p90": g.quantile(0.9)}
    ).reset_index()


# ------------------------------------------------------------------ Kaggle (Nigerian waterways)
def load_kaggle_ship_fuel(folder: Path | None = None) -> pd.DataFrame | None:
    folder = folder or RAW / "kaggle_ship_fuel"
    files = _files(folder, ("*.csv",))
    if not files:
        return None
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df.columns = [_norm(c) for c in df.columns]
    required = {"ship_type", "distance", "fuel_consumption"}
    if not required.issubset(df.columns):
        log.warning("Kaggle file missing columns %s", required - set(df.columns))
        return None
    return df
