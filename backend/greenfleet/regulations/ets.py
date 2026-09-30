"""EU Emissions Trading System for shipping (Directive (EU) 2023/959)."""

from __future__ import annotations

from greenfleet.config import fuel_library, regulations, step_year


def surrender_share(year: int, cfg: dict | None = None) -> float:
    cfg = cfg or regulations()["eu_ets"]
    return step_year({int(k): v for k, v in cfg["phase_in"].items()}, year)


def allowances_t(co2_t: float, ch4_t: float, n2o_t: float, eu_scope: float, year: int, cfg: dict | None = None) -> float:
    """Allowances (tCO2e) to surrender for the in-scope share of emissions."""
    cfg = cfg or regulations()["eu_ets"]
    lib = fuel_library()
    emissions = co2_t
    if year >= cfg["non_co2_from"]:
        emissions += ch4_t * lib.gwp_ch4 + n2o_t * lib.gwp_n2o
    return emissions * eu_scope * surrender_share(year, cfg)
