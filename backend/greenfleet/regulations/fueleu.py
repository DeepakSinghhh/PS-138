"""FuelEU Maritime, Regulation (EU) 2023/1805.

* Target GHG intensity = 91.16 gCO2e/MJ * (1 - reduction(year)).
* Actual intensity of a ship (or a pool) = sum(E_i * I_i) / sum(E_i * RWD_i),
  where RWD = 2 for RFNBO fuels until 2033 and OPS electricity counts as 0 g/MJ.
* Compliance balance CB = (target - actual) * energy_in_scope   [gCO2e]
* Penalty (negative CB) = |CB| / (actual * 41 000) * 2 400 EUR.
"""

from __future__ import annotations

from dataclasses import dataclass

from greenfleet.config import fuel_library, regulations, step_year
from greenfleet.physics.emissions import wtw_g_per_mj


def target_intensity(year: int, cfg: dict | None = None) -> float:
    cfg = cfg or regulations()["fueleu"]
    red = step_year({int(k): v for k, v in cfg["reduction_pct"].items()}, year)
    return cfg["reference_g_per_mj"] * (1 - red / 100.0)


@dataclass
class FuelEUResult:
    energy_mj: float            # in-scope energy
    intensity: float            # gCO2e/MJ (with RFNBO reward)
    target: float
    balance_g: float            # compliance balance (positive = surplus)
    penalty_eur: float


def intensity(energy_by_fuel: dict[str, float], ops_electricity_mj: float, year: int, cfg: dict | None = None) -> float:
    cfg = cfg or regulations()["fueleu"]
    lib = fuel_library()
    num = 0.0
    den = 0.0
    for fid, e in energy_by_fuel.items():
        if e <= 0:
            continue
        fuel = lib.fuels[fid]
        rwd = cfg["rfnbo_reward_factor"] if (fuel.rfnbo and year <= cfg["rfnbo_reward_until"]) else 1.0
        num += e * wtw_g_per_mj(fuel, lib)
        den += e * rwd
    num += ops_electricity_mj * cfg["ops_electricity_g_per_mj"]
    den += ops_electricity_mj
    return num / den if den > 0 else 0.0


def penalty_eur(balance_g: float, actual_intensity: float, cfg: dict | None = None) -> float:
    cfg = cfg or regulations()["fueleu"]
    if balance_g >= 0 or actual_intensity <= 0:
        return 0.0
    return abs(balance_g) / (actual_intensity * cfg["vlsfo_mj_per_t"]) * cfg["penalty_eur_per_t_vlsfo_eq"]


def assess(energy_by_fuel: dict[str, float], ops_electricity_mj: float, year: int, cfg: dict | None = None) -> FuelEUResult:
    """Assess a ship or a pool (energies already scaled by their EU-scope share)."""
    cfg = cfg or regulations()["fueleu"]
    energy = sum(energy_by_fuel.values()) + ops_electricity_mj
    actual = intensity(energy_by_fuel, ops_electricity_mj, year, cfg)
    target = target_intensity(year, cfg)
    cb = (target - actual) * energy
    return FuelEUResult(
        energy_mj=energy,
        intensity=actual,
        target=target,
        balance_g=cb,
        penalty_eur=penalty_eur(cb, actual, cfg),
    )
