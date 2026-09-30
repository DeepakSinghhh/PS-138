"""IMO Carbon Intensity Indicator (CII), MEPC.352-355(78) and MEPC.400(83).

attained CII  = annual TtW CO2 [g] / (capacity * distance [nm])
required CII  = (1 - Z/100) * a * capacity^(-c)
rating        = A..E from attained/required against exp(d1..d4)
"""

from __future__ import annotations

from greenfleet.config import VesselClass, regulations

RATINGS = ("A", "B", "C", "D", "E")


def reduction_pct(year: int, cfg: dict | None = None) -> float:
    cfg = cfg or regulations()["cii"]
    table = {int(k): float(v) for k, v in cfg["reduction_pct"].items()}
    if year in table:
        return table[year]
    last = max(table)
    if year > last:
        return table[last] + cfg["post_2030_slope_pct"] * (year - last)
    first = min(table)
    return table[first] if year < first else 0.0


def capacity_for(vc: VesselClass, cfg: dict | None = None) -> float:
    cfg = cfg or regulations()["cii"]
    spec = cfg["ship_types"][vc.cii_type]
    return vc.gt if spec["capacity"] == "gt" else vc.dwt


def reference_cii(vc: VesselClass, cfg: dict | None = None) -> float:
    cfg = cfg or regulations()["cii"]
    spec = cfg["ship_types"][vc.cii_type]
    return spec["a"] * capacity_for(vc, cfg) ** (-spec["c"])


def required_cii(vc: VesselClass, year: int, cfg: dict | None = None) -> float:
    cfg = cfg or regulations()["cii"]
    return (1 - reduction_pct(year, cfg) / 100.0) * reference_cii(vc, cfg)


def attained_cii(co2_t: float, capacity: float, distance_nm: float) -> float:
    if distance_nm <= 0:
        return 0.0
    return co2_t * 1e6 / (capacity * distance_nm)


def rating(attained: float, required: float, cii_type: str, cfg: dict | None = None) -> str:
    cfg = cfg or regulations()["cii"]
    dd = cfg["ship_types"][cii_type]["dd"]
    ratio = attained / required
    for letter, bound in zip(RATINGS, dd):
        if ratio <= bound:
            return letter
    return "E"


def rating_ratio_limit(cii_type: str, min_rating: str = "C", cfg: dict | None = None) -> float:
    """Largest attained/required ratio that still achieves ``min_rating``."""
    cfg = cfg or regulations()["cii"]
    dd = cfg["ship_types"][cii_type]["dd"]
    idx = RATINGS.index(min_rating)
    return dd[idx] if idx < len(dd) else float("inf")
