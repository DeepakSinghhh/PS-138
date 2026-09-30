"""Scenario definition and resolution.

A ``Scenario`` is what the user edits (network, year, prices, policy levers, disruptions,
optimizer settings). ``resolve`` turns it into a ``ResolvedScenario``: concrete routes with
distances, per-route fuel availability (bunkering + range), shore-power availability,
year-interpolated prices and grid factors, and regulatory targets.
"""

from __future__ import annotations

import copy
import functools
from dataclasses import asdict, dataclass, field

from greenfleet.config import (
    NETWORKS,
    Port,
    Route,
    VesselClass,
    fuel_library,
    interp_year,
    load_routes,
    ports,
    prices,
    vessel_classes,
)

OBJECTIVES = ("fuel", "emissions", "cost", "schedule_risk")
OBJECTIVE_LABELS = {
    "fuel": "Fuel (t HFO-eq/yr)",
    "emissions": "WtW GHG (t CO2e/yr)",
    "cost": "Cost (M USD/yr)",
    "schedule_risk": "Schedule risk (%)",
}


@dataclass
class Scenario:
    network: str = "india"
    year: int = 2030
    # prices & policy
    fuel_prices: dict[str, float] = field(default_factory=dict)      # USD/t overrides
    fuel_price_multiplier: float = 1.0                                # applied to every fuel
    ets_price_eur: float | None = None
    global_levy_usd: float | None = None                              # USD/t CO2e WtW (IMO NZF-style)
    grid_factor_multiplier: float = 1.0
    # availability & disruptions
    allowed_fuels: list[str] | None = None
    fleet_availability: dict[str, int] = field(default_factory=dict)
    red_sea_diversion: bool = False
    monsoon: bool = False
    demand_multiplier: float = 1.0
    extra_ops_ports: list[str] = field(default_factory=list)
    # constraints
    on_time_min: float = 0.80
    cii_min_rating: str = "C"
    fueleu_mode: str = "penalty"          # "penalty" (pay FuelEU penalty) or "hard" (must comply)
    fleet_emission_cap_t: float | None = None
    # optimizer settings
    objectives: list[str] = field(default_factory=lambda: ["fuel", "emissions", "cost"])
    max_extra_ships: int = 2
    speed_levels: int | None = None       # discretise speeds (used for exact MILP comparison)
    use_surrogate: bool = True
    custom_routes: list[dict] | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Scenario:
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class ResolvedScenario:
    scenario: Scenario
    name: str
    routes: list[Route]
    classes: dict[str, VesselClass]
    ports: dict[str, Port]
    fuel_ids: list[str]
    route_fuels: list[list[str]]          # fuels available per route
    route_ops_share: list[float]          # share of port time at berths with shore power
    route_countries: list[list[str]]
    fuel_price: dict[str, float]          # USD/t
    ets_price_usd: float
    global_levy_usd: float
    grid_t_per_kwh: list[float]           # per route (average of OPS ports)
    elec_usd_per_kwh: list[float]         # per route
    eur_to_usd: float
    year: int
    notes: list[str] = field(default_factory=list)


@functools.lru_cache(maxsize=None)
def _cape_distance(a: str, b: str) -> tuple[float, tuple]:
    import searoute

    pa, pb = ports()[a], ports()[b]
    feat = searoute.searoute((pa.lon, pa.lat), (pb.lon, pb.lat), units="naut", restrictions=["suez"])
    return float(feat.properties["length"]), tuple(tuple(c) for c in feat.geometry["coordinates"])


def fuel_available_on_route(route: Route, fuel_id: str, year: int, port_lib: dict[str, Port]) -> bool:
    lib = fuel_library()
    rng = lib.family_of(fuel_id).range_nm
    have = [port_lib[p].bunkers.get(fuel_id, 9999) <= year for p in route.ports]
    if 2 * route.distance_nm <= rng:
        return any(have)
    if route.distance_nm <= rng:
        return all(have)
    return False


def _route_from_dict(d: dict) -> Route:
    base = {"load_factor": 0.85, "port_hours": 36, "beaufort": 4.0, "delay_mean": 0.02, "delay_sd": 0.05,
            "port_delay_sd_h": 8, "eu_scope": 0.0}
    base.update(d)
    return Route(**{k: v for k, v in base.items() if k in Route.__dataclass_fields__})


def resolve(sc: Scenario) -> ResolvedScenario:
    pr = prices()
    lib = fuel_library()
    port_lib = dict(ports())
    notes: list[str] = []
    if sc.custom_routes:
        from greenfleet.config import _sea_route

        routes = []
        for d in sc.custom_routes:
            r = _route_from_dict(d)
            if not r.distance_nm or not r.geometry:
                dist, coords = _sea_route(r.ports[0], r.ports[1])
                r.distance_nm = r.distance_nm or dist
                r.geometry = [list(c) for c in coords]
            routes.append(r)
        name = "Custom network"
    else:
        meta, routes = load_routes(NETWORKS.get(sc.network, sc.network))
        routes = [copy.deepcopy(r) for r in routes]
        name = meta.get("name", sc.network)

    classes = dict(vessel_classes())
    for cid, n in sc.fleet_availability.items():
        if cid in classes:
            from dataclasses import replace

            classes[cid] = replace(classes[cid], available=int(n))

    for r in routes:
        r.demand *= sc.demand_multiplier
        if sc.monsoon:
            r.beaufort += 1.0
        if sc.red_sea_diversion:
            try:
                d, coords = _cape_distance(r.ports[0], r.ports[1])
                if d > 1.2 * r.distance_nm:
                    notes.append(f"{r.id}: Red Sea diversion via Cape of Good Hope, {r.distance_nm:,.0f} -> {d:,.0f} nm")
                    r.distance_nm = d
                    r.geometry = [list(c) for c in coords]
            except Exception:  # pragma: no cover
                pass

    fuel_ids = [f for f in lib.fuels if sc.allowed_fuels is None or f in sc.allowed_fuels or f == lib.pilot_fuel]
    if sc.allowed_fuels is not None and not any(lib.fuels[f].family == "conventional" for f in fuel_ids):
        fuel_ids.append("VLSFO")
    route_fuels = []
    for r in routes:
        avail = [f for f in fuel_ids if fuel_available_on_route(r, f, sc.year, port_lib)]
        if sc.allowed_fuels is not None:
            avail = [f for f in avail if f in sc.allowed_fuels] or ["VLSFO"]
        route_fuels.append(avail or ["VLSFO"])

    route_ops, route_grid, route_elec, route_countries = [], [], [], []
    for r in routes:
        ops_ports = [p for p in r.ports if port_lib[p].ops_from <= sc.year or p in sc.extra_ops_ports]
        route_ops.append(len(ops_ports) / len(r.ports))
        countries = [port_lib[p].country for p in r.ports]
        route_countries.append(countries)
        use = [port_lib[p].country for p in ops_ports] or countries
        route_grid.append(sum(interp_year(pr["grid_t_per_mwh"].get(c, {2025: 0.5}), sc.year) for c in use)
                          / len(use) / 1000.0 * sc.grid_factor_multiplier)
        route_elec.append(sum(pr["electricity_usd_per_kwh"].get(c, 0.15) for c in use) / len(use))

    fuel_price = {f: interp_year(pr["fuel_usd_per_t"][f], sc.year) * sc.fuel_price_multiplier for f in lib.fuels}
    fuel_price.update({k: float(v) for k, v in sc.fuel_prices.items()})
    eur = float(pr["eur_to_usd"])
    ets = sc.ets_price_eur if sc.ets_price_eur is not None else interp_year(pr["eu_ets_eur_per_t"], sc.year)
    levy = sc.global_levy_usd if sc.global_levy_usd is not None else interp_year(pr["global_levy_usd_per_t"], sc.year)
    return ResolvedScenario(
        scenario=sc, name=name, routes=routes, classes=classes, ports=port_lib, fuel_ids=fuel_ids,
        route_fuels=route_fuels, route_ops_share=route_ops, route_countries=route_countries,
        fuel_price=fuel_price, ets_price_usd=float(ets) * eur, global_levy_usd=float(levy),
        grid_t_per_kwh=route_grid, elec_usd_per_kwh=route_elec, eur_to_usd=eur, year=sc.year, notes=notes,
    )
