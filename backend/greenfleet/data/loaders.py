"""Loaders for public datasets, with alias-based column mapping and graceful fallback.

Each loader looks for files under ``data/raw/<dataset>/``. When the folder is empty
(e.g. the host is blocked from this environment) the loader returns ``None`` and the
caller falls back to the synthetic generator, so the pipeline always runs.

Column mapping
    Source columns are matched to canonical names through alias lists. A dataset folder
    may contain a ``columns.yaml`` (``canonical_name: "Source column"``) to override the
    automatic matching, which is also how user-supplied fleet data is onboarded.

Required inputs (PS Delivery Table, item 1): speed, load, weather, vessel type.
    * ``load`` is *cargo* load. Columns that describe *engine* load / power / rpm are
      consequences of the operating point and are excluded as target leakage; they are
      listed in the data card so the choice is transparent.
    * ``vessel_type`` comes from a column when present, otherwise from the file name
      (FuelCast ships are named ``cps_*`` = cruise passenger ship, ``oss_*`` = offshore
      supply ship).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from greenfleet.config import DATA_DIR
from greenfleet.data.schema import normalise_vessel_type

log = logging.getLogger(__name__)
RAW = DATA_DIR / "raw"

# alias lists are matched case-insensitively against normalised column names
TELEMETRY_ALIASES: dict[str, list[str]] = {
    "timestamp": ["timestamp", "time", "datetime", "date", "utc", "date_time"],
    "speed_kn": ["speed_through_water", "stw", "speed_log", "log_speed", "speed_kn", "speed",
                 "speed_over_ground", "sog", "vessel_speed"],
    "load": ["load_ratio", "cargo_load", "cargo_load_ratio", "loading_condition", "load_condition",
             "cargo_weight", "cargo_mass", "cargo_on_board", "cargo", "load", "loading"],
    "vessel_type": ["vessel_type", "ship_type", "type_of_ship", "shiptype"],
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
FUELCAST_ALIASES = TELEMETRY_ALIASES  # backwards-compatible name

# engine-side quantities: consequences of the operating point -> excluded (leakage)
LEAKAGE = re.compile(r"(engine|me|main|mcr|shaft|propulsion)_?(load|power)|power|rpm|torque|sfoc|flow_?rate")

FILE_PREFIX_TYPES = {"cps": "cruise", "oss": "offshore", "osv": "offshore", "psv": "offshore",
                     "bc": "bulk", "bulk": "bulk", "ct": "tanker", "tanker": "tanker",
                     "cs": "container", "container": "container"}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def match_columns(columns: list[str], aliases: dict[str, list[str]],
                  exclude: re.Pattern | None = None) -> dict[str, str]:
    """Map canonical names to source columns (exact alias match first, then prefix match)."""
    norm = {_norm(c): c for c in columns if not (exclude and exclude.search(_norm(c)))}
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


def leakage_columns(columns: list[str]) -> list[str]:
    return [c for c in columns if LEAKAGE.search(_norm(c))]


def _overrides(folder: Path) -> dict[str, str]:
    path = folder / "columns.yaml"
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return {k: v for k, v in (yaml.safe_load(fh) or {}).items() if v}
    return {}


def _relative_angle(direction_deg: pd.Series, heading_deg: pd.Series | None) -> pd.Series:
    """Relative angle in [0, 180]: 0 = coming from ahead (meteorological 'from' convention)."""
    rel = direction_deg % 360 if heading_deg is None else (direction_deg - heading_deg) % 360
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


def _load_to_ratio(series: pd.Series) -> pd.Series:
    """Cargo load as a fraction of full load: accepts fractions, percentages, tonnes or labels."""
    if not pd.api.types.is_numeric_dtype(series):
        text = series.astype(str).str.lower()
        labelled = text.map(lambda t: 1.0 if ("laden" in t or "loaded" in t or t == "full") and "un" not in t
                            else 0.0 if ("ballast" in t or "empty" in t or "unladen" in t) else np.nan)
        if labelled.notna().mean() > 0.5:
            return labelled
        series = pd.to_numeric(series, errors="coerce")
    series = pd.to_numeric(series, errors="coerce")
    top = series.quantile(0.99)
    if pd.isna(top) or top <= 0:
        return series * np.nan
    if top <= 1.05:
        return series.clip(0, 1)
    if top <= 105:
        return (series / 100.0).clip(0, 1)
    return (series / top).clip(0, 1)            # absolute cargo mass -> fraction of observed full load


def infer_vessel_type(stem: str) -> str:
    prefix = re.split(r"[_\-\s]", stem.lower())[0]
    return FILE_PREFIX_TYPES.get(prefix, normalise_vessel_type(stem))


def canonicalise_telemetry(df: pd.DataFrame, ship_id: str, source: str,
                           vessel_type: str | None = None,
                           overrides: dict[str, str] | None = None) -> pd.DataFrame:
    # the target is matched without the leakage filter (a fuel *flow rate* is the target itself)
    m = match_columns(list(df.columns), {"fuel": TELEMETRY_ALIASES["fuel"]})
    features = {k: v for k, v in TELEMETRY_ALIASES.items() if k != "fuel"}
    remaining = [c for c in df.columns if c not in m.values()]
    m.update(match_columns(remaining, features, exclude=LEAKAGE))
    m.update({k: v for k, v in (overrides or {}).items() if v in df.columns})
    if "speed_kn" not in m or "fuel" not in m:
        raise ValueError(f"could not identify speed/fuel columns in {list(df.columns)[:20]}")
    num = lambda key: pd.to_numeric(df[m[key]], errors="coerce")  # noqa: E731
    out = pd.DataFrame(index=df.index)
    out["ship_id"] = ship_id
    out["vessel_class"] = None
    if "vessel_type" in m:
        out["vessel_type"] = df[m["vessel_type"]].map(normalise_vessel_type)
    else:
        out["vessel_type"] = normalise_vessel_type(vessel_type) if vessel_type else "other"
    out["source"] = source
    out["timestamp"] = pd.to_datetime(df[m["timestamp"]], errors="coerce") if "timestamp" in m else pd.NaT
    out["speed_kn"] = num("speed_kn")

    if "draft" in m:
        draft = num("draft")
    elif "draft_fwd" in m and "draft_aft" in m:
        draft = (num("draft_fwd") + num("draft_aft")) / 2
    else:
        draft = pd.Series(np.nan, index=df.index)
    ref = draft.quantile(0.95) if draft.notna().any() else np.nan
    out["draft_ratio"] = draft / ref if ref and ref > 0 else np.nan
    load = _load_to_ratio(df[m["load"]]) if "load" in m else pd.Series(np.nan, index=df.index)
    if load.notna().any():
        out["load_ratio"] = load
    elif draft.notna().any():
        # no cargo-load column: estimate it from draft between its light and deep extremes
        lo, hi = draft.quantile(0.02), draft.quantile(0.98)
        out["load_ratio"] = ((draft - lo) / (hi - lo)).clip(0, 1) if hi > lo else np.nan
    else:
        out["load_ratio"] = np.nan

    if "trim_m" in m:
        out["trim_m"] = num("trim_m")
    elif "draft_fwd" in m and "draft_aft" in m:
        out["trim_m"] = num("draft_aft") - num("draft_fwd")
    else:
        out["trim_m"] = np.nan
    heading = num("heading_deg") if "heading_deg" in m else None
    out["wind_speed_ms"] = num("wind_speed_ms") if "wind_speed_ms" in m else np.nan
    out["wind_rel_deg"] = _relative_angle(num("wind_dir_deg"), heading) if "wind_dir_deg" in m else np.nan
    out["wave_height_m"] = num("wave_height_m") if "wave_height_m" in m else np.nan
    out["wave_rel_deg"] = _relative_angle(num("wave_dir_deg"), heading) if "wave_dir_deg" in m else np.nan
    if "current_speed" in m:
        cur = num("current_speed")
        if "current_dir_deg" in m and heading is not None:
            # 'towards' convention for currents: positive = pushing the ship ahead
            cur = cur * np.cos(np.deg2rad(num("current_dir_deg") - heading))
        out["current_kn"] = cur
    else:
        out["current_kn"] = np.nan
    ts = out["timestamp"]
    out["days_since_cleaning"] = (ts - ts.min()).dt.total_seconds() / 86400.0 if ts.notna().any() else np.nan

    fuel = num("fuel")
    col = _norm(m["fuel"])
    if "kg_h" in col or "kgh" in col or "kg_per_h" in col:
        fuel = fuel * 24 / 1000.0
    elif "t_h" in col or "mt_h" in col:
        fuel = fuel * 24
    out["fuel_tpd"] = fuel
    out = out[(out["speed_kn"] > 3.0) & (out["fuel_tpd"] > 0)]
    out = out.dropna(subset=["speed_kn", "fuel_tpd"]).reset_index(drop=True)
    out.attrs["column_map"] = m
    out.attrs["excluded_leakage"] = [c for c in leakage_columns(list(df.columns)) if c != m["fuel"]]
    return out


def load_telemetry_folder(folder: Path, source: str) -> pd.DataFrame | None:
    """Load every telemetry file in ``folder`` (one file per ship)."""
    files = _files(folder)
    if not files:
        return None
    overrides = _overrides(folder)
    frames, maps, excluded = [], {}, set()
    for f in files:
        try:
            part = canonicalise_telemetry(_read_any(f), ship_id=f.stem, source=source,
                                          vessel_type=infer_vessel_type(f.stem), overrides=overrides)
        except Exception as exc:  # keep going with the other files
            log.warning("skipping %s: %s", f.name, exc)
            continue
        maps[f.stem] = part.attrs.get("column_map", {})
        excluded.update(part.attrs.get("excluded_leakage", []))
        frames.append(part)
    if not frames:
        return None
    out = pd.concat(frames, ignore_index=True)
    out.attrs["column_map"] = maps
    out.attrs["excluded_leakage"] = sorted(excluded)
    return out


def load_fuelcast(folder: Path | None = None) -> pd.DataFrame | None:
    """FuelCast (huggingface.co/datasets/krohnedigital/FuelCast): one file per ship."""
    folder = folder or RAW / "fuelcast"
    out = load_telemetry_folder(folder, "fuelcast")
    if out is None:
        log.info("FuelCast not found in %s - using synthetic data only", folder)
    return out


def load_user_fleet(folder: Path | None = None) -> pd.DataFrame | None:
    """Operator-supplied noon reports / sensor logs (``data/raw/user_fleet``)."""
    return load_telemetry_folder(folder or RAW / "user_fleet", "user")


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
        out["vessel_type"] = out["ship_type"].map(normalise_vessel_type)
        for c in ("fuel_t", "co2_t", "hours_at_sea", "fuel_per_nm_kg"):
            if c in out:
                out[c] = pd.to_numeric(out[c], errors="coerce")
        if "fuel_per_nm_kg" in out and "fuel_t" in out:
            out["distance_nm"] = out["fuel_t"] * 1000 / out["fuel_per_nm_kg"]
            if "hours_at_sea" in out:
                out["avg_speed_kn"] = out["distance_nm"] / out["hours_at_sea"]
        frames.append(out)
    return pd.concat(frames, ignore_index=True) if frames else None


def mrv_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Fuel-per-distance distribution by ship type (for validating the vessel library)."""
    g = df.dropna(subset=["fuel_per_nm_kg"]).groupby("ship_type")["fuel_per_nm_kg"]
    return pd.DataFrame(
        {"ships": g.size(), "p10": g.quantile(0.1), "p50": g.median(), "p90": g.quantile(0.9)}
    ).reset_index()


# ------------------------------------------------------------------ Kaggle (Nigerian waterways)
KAGGLE_ALIASES = {
    "ship_id": ["ship_id", "vessel_id"],
    "vessel_type": ["ship_type", "vessel_type"],
    "route_id": ["route_id", "route"],
    "month": ["month"],
    "distance_nm": ["distance", "distance_nm", "distance_km"],
    "fuel_type": ["fuel_type"],
    "fuel": ["fuel_consumption", "fuel"],
    "weather": ["weather_conditions", "weather_condition", "weather"],
    "engine_efficiency": ["engine_efficiency", "efficiency"],
    "load": ["cargo_load", "load", "cargo"],
    "speed_kn": ["speed", "average_speed", "avg_speed"],
    "co2": ["co2_emissions", "co2"],
}
WEATHER_LEVELS = {"calm": 0.0, "moderate": 1.0, "rough": 2.0, "stormy": 2.0, "storm": 2.0}


def load_kaggle_ship_fuel(folder: Path | None = None) -> pd.DataFrame | None:
    """Voyage-level 'Ship Fuel Consumption & CO2 Emissions' set, canonicalised.

    Output columns: ship_id, vessel_type, route_id, month, distance_nm, fuel_type,
    weather_level (0 calm / 1 moderate / 2 stormy), engine_efficiency, load_ratio,
    speed_kn (when present) and the target ``fuel``. CO2 is kept only for reference
    (``co2_ref``) because it is a deterministic function of fuel (leakage).
    """
    folder = folder or RAW / "kaggle_ship_fuel"
    files = _files(folder, ("*.csv",))
    if not files:
        return None
    raw = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    m = match_columns(list(raw.columns), KAGGLE_ALIASES)
    m.update({k: v for k, v in _overrides(folder).items() if v in raw.columns})
    missing = {"vessel_type", "distance_nm", "fuel"} - set(m)
    if missing:
        log.warning("Kaggle file missing columns %s", missing)
        return None
    out = pd.DataFrame(index=raw.index)
    out["ship_id"] = raw[m["ship_id"]].astype(str) if "ship_id" in m else "unknown"
    out["vessel_type"] = raw[m["vessel_type"]].map(normalise_vessel_type)
    out["vessel_type_raw"] = raw[m["vessel_type"]].astype(str)
    out["route_id"] = raw[m["route_id"]].astype(str) if "route_id" in m else "unknown"
    out["month"] = raw[m["month"]] if "month" in m else np.nan
    out["distance_nm"] = pd.to_numeric(raw[m["distance_nm"]], errors="coerce")
    out["fuel_type"] = raw[m["fuel_type"]].astype(str) if "fuel_type" in m else "unknown"
    out["weather_level"] = (
        raw[m["weather"]].astype(str).str.lower().map(lambda t: next((v for k, v in WEATHER_LEVELS.items() if k in t), np.nan))
        if "weather" in m else np.nan
    )
    out["engine_efficiency"] = pd.to_numeric(raw[m["engine_efficiency"]], errors="coerce") if "engine_efficiency" in m else np.nan
    out["load_ratio"] = _load_to_ratio(raw[m["load"]]) if "load" in m else np.nan
    out["speed_kn"] = pd.to_numeric(raw[m["speed_kn"]], errors="coerce") if "speed_kn" in m else np.nan
    out["fuel"] = pd.to_numeric(raw[m["fuel"]], errors="coerce")
    if "co2" in m:
        out["co2_ref"] = pd.to_numeric(raw[m["co2"]], errors="coerce")
    out = out.dropna(subset=["distance_nm", "fuel"]).reset_index(drop=True)
    out.attrs["column_map"] = m
    return out
