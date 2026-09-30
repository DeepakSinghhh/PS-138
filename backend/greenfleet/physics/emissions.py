"""Tank-to-wake and well-to-wake greenhouse-gas accounting.

Implements the FuelEU Maritime (Regulation (EU) 2023/1805, Annex I) intensity formula

    GHGIE = WtT + [ (1 - C_slip) * (Cf_CO2 + Cf_CH4 * GWP_CH4 + Cf_N2O * GWP_N2O)
                    + C_slip * GWP_CH4 ] / LCV

per fuel, and aggregates fuel burns (including pilot fuel for dual-fuel engines).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from greenfleet.config import Fuel, FuelLibrary, fuel_library


def ttw_g_per_mj(fuel: Fuel, lib: FuelLibrary | None = None) -> float:
    lib = lib or fuel_library()
    per_g = (1.0 - fuel.slip) * (fuel.cf_co2 + fuel.cf_ch4 * lib.gwp_ch4 + fuel.cf_n2o * lib.gwp_n2o)
    per_g += fuel.slip * lib.gwp_ch4
    return per_g / fuel.lcv_mj_per_g


def wtw_g_per_mj(fuel: Fuel, lib: FuelLibrary | None = None) -> float:
    return fuel.wtt_g_per_mj + ttw_g_per_mj(fuel, lib)


def effective_wtw_g_per_mj(fuel_id: str, lib: FuelLibrary | None = None) -> float:
    """WtW intensity of the delivered energy mix including pilot fuel."""
    lib = lib or fuel_library()
    fuel = lib.fuels[fuel_id]
    pilot = lib.fuels[lib.pilot_fuel]
    return (1 - fuel.pilot_share) * wtw_g_per_mj(fuel, lib) + fuel.pilot_share * wtw_g_per_mj(pilot, lib)


@dataclass
class Burn:
    """Aggregated result of burning fuel(s). Masses in tonnes, energy in MJ."""

    fuel_t: dict[str, float] = field(default_factory=dict)
    energy_mj: dict[str, float] = field(default_factory=dict)
    co2_t: float = 0.0          # tank-to-wake CO2 (what IMO DCS / CII and EU ETS count)
    ch4_t: float = 0.0          # incl. methane slip
    n2o_t: float = 0.0
    ttw_co2e_t: float = 0.0
    wtw_co2e_t: float = 0.0

    def add(self, other: Burn, scale: float = 1.0) -> Burn:
        for k, v in other.fuel_t.items():
            self.fuel_t[k] = self.fuel_t.get(k, 0.0) + v * scale
        for k, v in other.energy_mj.items():
            self.energy_mj[k] = self.energy_mj.get(k, 0.0) + v * scale
        self.co2_t += other.co2_t * scale
        self.ch4_t += other.ch4_t * scale
        self.n2o_t += other.n2o_t * scale
        self.ttw_co2e_t += other.ttw_co2e_t * scale
        self.wtw_co2e_t += other.wtw_co2e_t * scale
        return self

    @property
    def total_energy_mj(self) -> float:
        return sum(self.energy_mj.values())

    @property
    def total_fuel_t(self) -> float:
        return sum(self.fuel_t.values())


def _burn_single(energy_mj: float, fuel: Fuel, lib: FuelLibrary) -> Burn:
    mass_g = energy_mj / fuel.lcv_mj_per_g
    burnt = mass_g * (1.0 - fuel.slip)
    co2 = burnt * fuel.cf_co2
    ch4 = burnt * fuel.cf_ch4 + mass_g * fuel.slip
    n2o = burnt * fuel.cf_n2o
    ttw = co2 + ch4 * lib.gwp_ch4 + n2o * lib.gwp_n2o
    wtw = ttw + energy_mj * fuel.wtt_g_per_mj
    to_t = 1e-6
    return Burn(
        fuel_t={fuel.id: mass_g * to_t},
        energy_mj={fuel.id: energy_mj},
        co2_t=co2 * to_t,
        ch4_t=ch4 * to_t,
        n2o_t=n2o * to_t,
        ttw_co2e_t=ttw * to_t,
        wtw_co2e_t=wtw * to_t,
    )


def burn(energy_mj: float, fuel_id: str, lib: FuelLibrary | None = None) -> Burn:
    """Burn ``energy_mj`` of delivered energy with ``fuel_id`` (pilot fuel split included)."""
    lib = lib or fuel_library()
    fuel = lib.fuels[fuel_id]
    if fuel.pilot_share <= 0:
        return _burn_single(energy_mj, fuel, lib)
    out = _burn_single(energy_mj * (1 - fuel.pilot_share), fuel, lib)
    out.add(_burn_single(energy_mj * fuel.pilot_share, lib.fuels[lib.pilot_fuel], lib))
    return out
