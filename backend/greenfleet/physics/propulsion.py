"""Ship propulsion physics.

* Propulsion power follows the bottom-up model of the IMO Fourth GHG Study (2020):
  ``P = P_ref * (T / T_ref)^0.66 * (V / V_ref)^3 * f_weather / eta_fouling``.
* Weather is handled with Kwon's (2008) involuntary speed-loss method, converted
  into the extra power needed to hold the commanded speed, and averaged over a
  Beaufort distribution and the four heading sectors.
* Specific fuel (energy) consumption varies with engine load through the IMO
  GHG4 SFOC load curve ``SFOC(L) = SFOC_base * (0.455 L^2 - 0.710 L + 1.280)``.
"""

from __future__ import annotations

import functools
import math

import numpy as np

from greenfleet.config import VesselClass

G = 9.81
KN_TO_MS = 0.514444
RHO_SEA = 1.025
FOULING_EFFICIENCY = 0.917   # IMO GHG4 hull-fouling efficiency
DRAFT_EXPONENT = 0.66        # IMO GHG4 draft-power exponent

# Kwon (2008) speed-reduction coefficient C_U(Fn) per block coefficient
# (normal/loaded condition, ballast condition).
_KWON_CU_LOADED = {
    0.55: (1.7, -1.4, -7.4),
    0.60: (2.2, -2.5, -9.7),
    0.65: (2.6, -3.7, -11.6),
    0.70: (3.1, -5.3, -12.4),
    0.75: (2.4, -10.6, -9.5),
    0.80: (2.6, -13.1, -15.1),
    0.85: (3.1, -18.7, 28.0),
}
_KWON_CU_BALLAST = {
    **{k: v for k, v in _KWON_CU_LOADED.items() if k < 0.75},
    0.75: (2.6, -12.5, -13.5),
    0.80: (3.0, -16.3, -21.6),
    0.85: (3.4, -20.9, 31.8),
}


def sfoc_multiplier(load: np.ndarray | float, curve: str = "ice") -> np.ndarray | float:
    """Relative specific energy consumption as a function of engine load (0-1)."""
    load = np.clip(load, 0.10, 1.10)
    if curve == "fuel_cell":
        # fuel cells are most efficient at part load
        return 0.95 + 0.10 * load
    return 0.455 * load**2 - 0.710 * load + 1.280


def froude_number(speed_kn: float, length_m: float) -> float:
    return speed_kn * KN_TO_MS / math.sqrt(G * length_m)


def _kwon_cu(cb: float, fn: float, laden: bool) -> float:
    table = _KWON_CU_LOADED if laden else _KWON_CU_BALLAST
    keys = sorted(table)
    cb = min(max(cb, keys[0]), keys[-1])
    # linear interpolation between the two neighbouring block coefficients
    lo = max(k for k in keys if k <= cb + 1e-12)
    hi = min(k for k in keys if k >= cb - 1e-12)

    def poly(k: float) -> float:
        a, b, c = table[k]
        return a + b * fn + c * fn**2

    if hi == lo:
        return poly(lo)
    w = (cb - lo) / (hi - lo)
    return (1 - w) * poly(lo) + w * poly(hi)


def _kwon_direction(bn: float) -> np.ndarray:
    """2*C_beta for head, bow, beam and following seas."""
    return np.array(
        [
            2.0,
            1.7 - 0.03 * (bn - 4) ** 2,
            0.9 - 0.06 * (bn - 6) ** 2,
            0.4 - 0.03 * (bn - 8) ** 2,
        ]
    )


def kwon_speed_loss(
    bn: float,
    speed_kn: float,
    vc: VesselClass,
    laden: bool = True,
    direction_weights: tuple[float, float, float, float] = (0.25, 0.25, 0.25, 0.25),
) -> float:
    """Fractional involuntary speed loss at constant power (Kwon 2008)."""
    if bn <= 0:
        return 0.0
    vol = vc.displacement_t / RHO_SEA
    if vc.cargo == "container":
        c_form = 0.7 * bn + bn**6.5 / (22.0 * vol ** (2 / 3))
    elif laden:
        c_form = 0.5 * bn + bn**6.5 / (2.7 * vol ** (2 / 3))
    else:
        c_form = 0.7 * bn + bn**6.5 / (2.7 * vol ** (2 / 3))
    fn = froude_number(speed_kn, vc.length_m)
    c_u = max(_kwon_cu(vc.block_coefficient, fn, laden), 0.0)
    c_beta = np.clip(_kwon_direction(bn) / 2.0, 0.0, None)
    c_beta_avg = float(np.dot(np.asarray(direction_weights), c_beta))
    loss_pct = c_beta_avg * c_u * c_form
    return float(np.clip(loss_pct / 100.0, 0.0, 0.6))


def _beaufort_weights(mean_bn: float, sd: float = 1.2) -> tuple[np.ndarray, np.ndarray]:
    bns = np.arange(0, 11, dtype=float)
    w = np.exp(-0.5 * ((bns - mean_bn) / sd) ** 2)
    return bns, w / w.sum()


@functools.lru_cache(maxsize=100_000)
def _weather_factor_cached(vc: VesselClass, speed_bin: float, bn_mean: float, laden: bool) -> float:
    bns, w = _beaufort_weights(bn_mean)
    factors = []
    for bn in bns:
        loss = kwon_speed_loss(bn, speed_bin, vc, laden)
        # to hold the commanded speed the engine must supply ~(1 / (1 - loss))^3 more power
        factors.append(1.0 / (1.0 - loss) ** 3)
    return float(np.dot(w, factors))


def weather_power_factor(vc: VesselClass, speed_kn: float, bn_mean: float, laden: bool = True) -> float:
    """Expected power multiplier for holding ``speed_kn`` on a route with mean Beaufort ``bn_mean``."""
    return _weather_factor_cached(vc, round(float(speed_kn) * 4) / 4, round(float(bn_mean) * 4) / 4, laden)


def propulsion_power_kw(
    vc: VesselClass,
    speed_kn: np.ndarray | float,
    draft_m: float | None = None,
    weather_factor: float = 1.0,
    hull_factor: float = 1.0,
) -> np.ndarray | float:
    """Shaft power needed for a speed, draft and weather condition (IMO GHG4 form)."""
    draft = vc.design_draft_m if draft_m is None else draft_m
    return (
        vc.p_ref_kw
        * hull_factor
        * (draft / vc.design_draft_m) ** DRAFT_EXPONENT
        * (np.asarray(speed_kn) / vc.design_speed_kn) ** 3
        * weather_factor
        / FOULING_EFFICIENCY
    )


def max_service_speed(vc: VesselClass, bn_mean: float, laden: bool = True, mcr_fraction: float = 0.95) -> float:
    """Highest speed that stays below ``mcr_fraction`` of MCR in average route weather."""
    draft = vc.design_draft_m if laden else vc.ballast_draft_m
    lo, hi = vc.min_speed_kn, vc.max_speed_kn
    if propulsion_power_kw(vc, hi, draft, weather_power_factor(vc, hi, bn_mean, laden)) <= mcr_fraction * vc.mcr_kw:
        return hi
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        p = propulsion_power_kw(vc, mid, draft, weather_power_factor(vc, mid, bn_mean, laden))
        if p <= mcr_fraction * vc.mcr_kw:
            lo = mid
        else:
            hi = mid
    return lo
