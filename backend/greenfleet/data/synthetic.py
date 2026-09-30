"""Physics-informed synthetic fleet telemetry.

Real noon-report / sensor data for alternative-fuel ships does not exist yet, and the
public datasets cover only a handful of vessels, so this generator produces realistic
telemetry for every vessel class in ``vessels.yaml``. The "true" data-generating process
is intentionally richer than the physics prior used by the models:

* calm-water power with a speed-dependent (non-cubic) exponent and ship-specific hull factor
* hull fouling growth since the last cleaning / dry-dock
* trim penalty around a ship-specific optimum
* wind added resistance (relative wind, frontal area, drag coefficient vs angle)
* wave added resistance (ITTC STAWAVE-1 form, head-sea weighted)
* SFOC load curve with ship-specific engine condition, auxiliary load
* seasonal monsoon weather with autocorrelated wind, wind-sea + swell waves, currents
* sensor noise and sparse outliers

Every row is labelled ``source = "synthetic"`` and the UI shows this label.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from greenfleet.config import VesselClass, vessel_classes
from greenfleet.physics.propulsion import FOULING_EFFICIENCY, KN_TO_MS, froude_number, sfoc_multiplier

RHO_AIR = 1.225
RHO_SEA = 1025.0
G = 9.81
ETA_D = 0.70                  # quasi-propulsive efficiency
SFOC_BASE_G_PER_KWH = 172.0   # HFO-equivalent, conventional 2-stroke
AUX_SFOC_G_PER_KWH = 205.0
SUPERSTRUCTURE_HEIGHT = {"container": 42.0, "bulk": 26.0, "tanker": 26.0, "pax": 34.0}


def _ar1(rng: np.random.Generator, n: int, phi: float, sd: float) -> np.ndarray:
    eps = rng.normal(0.0, sd * np.sqrt(1 - phi**2), n)
    x = np.empty(n)
    x[0] = rng.normal(0.0, sd)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x


def true_fuel_tpd(
    vc: VesselClass,
    speed_kn: np.ndarray,
    draft_m: np.ndarray,
    trim_m: np.ndarray,
    days_since_cleaning: np.ndarray,
    wind_ms: np.ndarray,
    wind_rel_deg: np.ndarray,
    wave_m: np.ndarray,
    wave_rel_deg: np.ndarray,
    hull_factor: float = 1.0,
    sfoc_factor: float = 1.0,
    fouling_per_year: float = 0.08,
    trim_opt: float = 0.3,
) -> np.ndarray:
    """Ground-truth fuel rate (HFO-equivalent t/day) of the synthetic data-generating process."""
    v = np.maximum(speed_kn, 0.1)
    fn = froude_number(1.0, vc.length_m) * v
    fn_design = froude_number(vc.design_speed_kn, vc.length_m)
    # wave-making makes the speed exponent grow above the design Froude number
    exponent_boost = 1.0 + 2.5 * np.clip(fn - 0.9 * fn_design, 0.0, None)
    calm = (
        vc.p_ref_kw
        * hull_factor
        * (draft_m / vc.design_draft_m) ** 0.66
        * (v / vc.design_speed_kn) ** 3
        * exponent_boost
        / FOULING_EFFICIENCY
    )
    calm *= 1.0 + fouling_per_year * days_since_cleaning / 365.0
    calm *= 1.0 + 0.012 * (trim_m - trim_opt) ** 2

    # wind: relative wind from ship speed + true wind at relative angle (0 deg = head wind)
    v_ms = v * KN_TO_MS
    th = np.deg2rad(wind_rel_deg)
    u_rel2 = wind_ms**2 + v_ms**2 + 2 * wind_ms * v_ms * np.cos(th)
    rel_angle = np.arctan2(wind_ms * np.sin(th), v_ms + wind_ms * np.cos(th))
    beam = vc.length_m / 7.0
    frontal_area = 0.9 * beam * SUPERSTRUCTURE_HEIGHT[vc.cargo]
    cx = 0.85 * np.cos(rel_angle)
    still_air = 0.5 * RHO_AIR * 0.85 * frontal_area * v_ms**2   # already inside calm-water trials
    r_wind = 0.5 * RHO_AIR * cx * frontal_area * u_rel2 - still_air
    p_wind = r_wind * v_ms / ETA_D / 1000.0

    # waves: STAWAVE-1 style added resistance, strongest in head seas
    tw = np.deg2rad(wave_rel_deg)
    head = np.clip(np.cos(tw), 0.0, None) ** 2 + 0.15
    r_wave = (1.0 / 16.0) * RHO_SEA * G * wave_m**2 * beam * np.sqrt(beam / vc.length_m) * head
    p_wave = r_wave * v_ms / ETA_D / 1000.0

    p = np.clip(calm + p_wind + p_wave, 0.05 * vc.mcr_kw, 1.05 * vc.mcr_kw)
    load = p / vc.mcr_kw
    main_t_per_h = p * SFOC_BASE_G_PER_KWH * sfoc_factor * sfoc_multiplier(load) / 1e6
    aux_t_per_h = vc.aux_sea_kw * AUX_SFOC_G_PER_KWH / 1e6
    return 24.0 * (main_t_per_h + aux_t_per_h)


def generate_ship(
    vc: VesselClass,
    ship_idx: int,
    days: int = 365,
    step_hours: float = 3.0,
    seed: int = 0,
    start: str = "2025-01-01",
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = int(days * 24 / step_hours)
    t = pd.date_range(start, periods=n, freq=f"{int(step_hours * 60)}min")
    doy = t.dayofyear.to_numpy()

    # ship-specific hidden characteristics
    hull_factor = rng.normal(1.0, 0.06)
    sfoc_factor = rng.normal(1.0, 0.04)
    fouling_per_year = rng.uniform(0.04, 0.12)
    trim_opt = rng.uniform(-0.5, 1.0)

    # voyage structure: alternating sea passages and port stays
    at_sea = np.zeros(n, dtype=bool)
    commanded = np.zeros(n)
    load = np.zeros(n)
    i = 0
    is_laden = bool(rng.integers(0, 2))
    typical_passage_days = {"container": 4.0, "bulk": 7.0, "tanker": 5.0, "pax": 1.0}[vc.cargo]
    while i < n:
        passage = int(rng.uniform(0.5, 1.5) * typical_passage_days * 24 / step_hours) + 1
        speed = rng.uniform(0.55, 1.0) * vc.design_speed_kn
        at_sea[i : i + passage] = True
        commanded[i : i + passage] = speed
        # cargo load as a fraction of full load (PS input feature "load")
        if vc.cargo in ("bulk", "tanker"):
            voyage_load = rng.uniform(0.90, 1.0) if is_laden else 0.0
        elif vc.cargo == "container":
            voyage_load = rng.uniform(0.45, 1.0)
        else:
            voyage_load = rng.uniform(0.35, 1.0)
        load[i : i + passage] = voyage_load
        i += passage
        i += int(rng.uniform(0.3, 1.5) * 24 / step_hours)  # port stay
        is_laden = not is_laden

    speed = np.clip(commanded + _ar1(rng, n, 0.8, 0.35), vc.min_speed_kn * 0.8, vc.max_speed_kn)
    # draft follows cargo load (ballast draft at zero load, design draft at full load)
    if vc.cargo == "pax":
        draft = vc.design_draft_m * (0.93 + 0.07 * load)
    else:
        draft = vc.ballast_draft_m + (vc.design_draft_m - vc.ballast_draft_m) * load**0.9
    draft = draft * (1 + _ar1(rng, n, 0.99, 0.01))
    trim = trim_opt + _ar1(rng, n, 0.97, 0.6)

    # hull condition: days since cleaning, reset by a dry-dock when overdue
    days_clean = np.empty(n)
    d = rng.uniform(0, 700)
    for k in range(n):
        d += step_hours / 24.0
        if d > 900 and rng.random() < 0.01:
            d = 0.0
        days_clean[k] = d

    # weather: SW-monsoon season (Jun-Sep) raises wind and swell
    monsoon = np.clip(np.sin(2 * np.pi * (doy - 130) / 365.0), 0.0, None) ** 2
    wind = np.clip(6.0 + 4.0 * monsoon + _ar1(rng, n, 0.92, 2.8), 0.0, 28.0)
    wind_rel = (rng.uniform(0, 360) + np.cumsum(rng.normal(0, 8, n))) % 360.0
    wind_rel = np.where(wind_rel > 180, 360 - wind_rel, wind_rel)  # 0 = head, 180 = following
    wind_sea = np.minimum(0.0214 * wind**2, 0.55 * np.sqrt(wind) + 0.012 * wind**2 * 1.5)
    swell = np.clip(0.8 + 1.2 * monsoon + _ar1(rng, n, 0.98, 0.35), 0.1, None)
    wave = np.sqrt(wind_sea**2 + swell**2)
    wave_rel = np.clip(wind_rel + rng.normal(0, 25, n), 0, 180)
    current = _ar1(rng, n, 0.95, 0.5)

    fuel = true_fuel_tpd(
        vc, speed, draft, trim, days_clean, wind, wind_rel, wave, wave_rel,
        hull_factor=hull_factor, sfoc_factor=sfoc_factor,
        fouling_per_year=fouling_per_year, trim_opt=trim_opt,
    )
    # measurement noise (mass-flow meters ~1-3 %) and sparse outliers
    fuel = fuel * (1 + rng.normal(0, 0.025, n))
    outliers = rng.random(n) < 0.002
    fuel[outliers] *= rng.uniform(1.2, 1.5, outliers.sum())
    wind_meas = np.clip(wind + rng.normal(0, 0.8, n), 0, None)

    df = pd.DataFrame(
        {
            "ship_id": f"{vc.id}-{ship_idx + 1:02d}",
            "vessel_class": vc.id,
            "vessel_type": vc.cargo,
            "timestamp": t,
            "source": "synthetic",
            "speed_kn": speed,
            "sog_kn": speed + current,
            "load_ratio": np.clip(load + rng.normal(0, 0.01, n), 0.0, 1.0),
            "draft_ratio": draft / vc.design_draft_m,
            "trim_m": trim,
            "days_since_cleaning": days_clean,
            "wind_speed_ms": wind_meas,
            "wind_rel_deg": wind_rel,
            "wave_height_m": wave,
            "wave_rel_deg": wave_rel,
            "current_kn": current,
            "fuel_tpd": fuel,
            "design_speed_kn": vc.design_speed_kn,
            "mcr_kw": vc.mcr_kw,
            "displacement_t": vc.displacement_t,
            "length_m": vc.length_m,
            "block_coefficient": vc.block_coefficient,
            "aux_sea_kw": vc.aux_sea_kw,
        }
    )
    return df[at_sea & (speed > 3.0)].reset_index(drop=True)


def generate_fleet(
    classes: list[str] | None = None,
    ships_per_class: int = 2,
    days: int = 365,
    step_hours: float = 3.0,
    seed: int = 42,
) -> pd.DataFrame:
    lib = vessel_classes()
    classes = classes or list(lib)
    frames = []
    for ci, cid in enumerate(classes):
        for s in range(ships_per_class):
            frames.append(generate_ship(lib[cid], s, days=days, step_hours=step_hours, seed=seed + 1000 * ci + s))
    return pd.concat(frames, ignore_index=True)
