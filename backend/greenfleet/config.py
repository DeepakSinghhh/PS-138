"""Configuration loading: fuels, vessel classes, ports, routes, regulations, prices.

All domain data lives in YAML under ``backend/config`` so that every number used by
the models is visible, cited and editable. This module turns it into typed objects.
"""

from __future__ import annotations

import copy
import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
CONFIG_DIR = BACKEND_DIR / "config"
DATA_DIR = REPO_DIR / "data"
ARTIFACTS_DIR = BACKEND_DIR / "artifacts"
REPORTS_DIR = REPO_DIR / "reports"


def load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@functools.cache
def _cached_yaml(name: str) -> dict[str, Any]:
    return load_yaml(name)


def raw(name: str) -> dict[str, Any]:
    """Return a deep copy of a cached YAML file (callers may mutate it)."""
    return copy.deepcopy(_cached_yaml(name))


def interp_year(series: dict[int, float] | float, year: float) -> float:
    """Linear interpolation of a ``{year: value}`` mapping, flat outside the range."""
    if not isinstance(series, dict):
        return float(series)
    years = sorted(int(y) for y in series)
    if year <= years[0]:
        return float(series[years[0]])
    if year >= years[-1]:
        return float(series[years[-1]])
    for y0, y1 in zip(years, years[1:]):
        if y0 <= year <= y1:
            v0, v1 = float(series[y0]), float(series[y1])
            return v0 + (v1 - v0) * (year - y0) / (y1 - y0)
    raise AssertionError("unreachable")


def step_year(series: dict[int, float], year: int) -> float:
    """Piecewise-constant lookup: value of the latest listed year <= ``year``."""
    years = sorted(int(y) for y in series)
    value = 0.0
    for y in years:
        if year >= y:
            value = float(series[y])
    return value


@dataclass(frozen=True)
class FuelFamily:
    id: str
    label: str
    bsec_mj_per_kwh: float
    load_curve: str
    charter_premium: float
    capacity_loss: float
    range_nm: float


@dataclass(frozen=True)
class Fuel:
    id: str
    label: str
    family: str
    pathway: str
    lcv_mj_per_g: float
    cf_co2: float
    cf_ch4: float
    cf_n2o: float
    wtt_g_per_mj: float
    slip: float
    pilot_share: float
    rfnbo: bool
    source: str = ""


@dataclass(frozen=True)
class VesselClass:
    id: str
    label: str
    cargo: str
    capacity: float
    capacity_unit: str
    dwt: float
    gt: float
    cii_type: str
    design_speed_kn: float
    min_speed_kn: float
    max_speed_kn: float
    mcr_kw: float
    design_draft_m: float
    ballast_draft_m: float
    displacement_t: float
    length_m: float
    block_coefficient: float
    aux_sea_kw: float
    aux_berth_kw: float
    charter_usd_per_day: float
    available: int

    @property
    def p_ref_kw(self) -> float:
        """Calm-water propulsion power at design speed and design draft."""
        return 0.75 * self.mcr_kw


@dataclass(frozen=True)
class Port:
    id: str
    name: str
    lon: float
    lat: float
    country: str
    ops_from: int
    bunkers: dict[str, int]


@dataclass
class Route:
    id: str
    name: str
    ports: list[str]
    service: str
    cargo: str
    demand: float
    load_factor: float
    port_hours: float
    beaufort: float
    delay_mean: float
    delay_sd: float
    port_delay_sd_h: float
    eu_scope: float
    classes: list[str]
    distance_nm: float = 0.0
    geometry: list[list[float]] = field(default_factory=list)

    @property
    def annual_demand(self) -> float:
        return self.demand * 52.0 if self.service == "liner" else self.demand


@dataclass
class FuelLibrary:
    gwp_ch4: float
    gwp_n2o: float
    families: dict[str, FuelFamily]
    fuels: dict[str, Fuel]
    pilot_fuel: str

    def family_of(self, fuel_id: str) -> FuelFamily:
        return self.families[self.fuels[fuel_id].family]


@functools.lru_cache(maxsize=1)
def fuel_library() -> FuelLibrary:
    cfg = load_yaml("fuels.yaml")
    families = {k: FuelFamily(id=k, **v) for k, v in cfg["families"].items()}
    fuels = {k: Fuel(id=k, **v) for k, v in cfg["fuels"].items()}
    return FuelLibrary(
        gwp_ch4=float(cfg["gwp100"]["ch4"]),
        gwp_n2o=float(cfg["gwp100"]["n2o"]),
        families=families,
        fuels=fuels,
        pilot_fuel=cfg["pilot_fuel"],
    )


@functools.lru_cache(maxsize=1)
def vessel_classes() -> dict[str, VesselClass]:
    cfg = load_yaml("vessels.yaml")
    return {k: VesselClass(id=k, **v) for k, v in cfg["classes"].items()}


@functools.lru_cache(maxsize=1)
def ports() -> dict[str, Port]:
    cfg = load_yaml("ports.yaml")
    default = {k: int(v) for k, v in cfg["default_bunkers"].items()}
    out = {}
    for pid, p in cfg["ports"].items():
        bunkers = dict(default)
        bunkers.update({k: int(v) for k, v in (p.get("bunkers") or {}).items()})
        out[pid] = Port(
            id=pid,
            name=p["name"],
            lon=float(p["lon"]),
            lat=float(p["lat"]),
            country=p["country"],
            ops_from=int(p["ops_from"]),
            bunkers=bunkers,
        )
    return out


@functools.cache
def _sea_route(a: str, b: str) -> tuple[float, tuple[tuple[float, float], ...]]:
    """Sea distance (nm) and polyline between two ports via the searoute network."""
    pa, pb = ports()[a], ports()[b]
    try:
        import searoute

        feat = searoute.searoute((pa.lon, pa.lat), (pb.lon, pb.lat), units="naut")
        coords = tuple((float(x), float(y)) for x, y in feat.geometry["coordinates"])
        return float(feat.properties["length"]), coords
    except Exception:  # pragma: no cover - fallback when searoute is unavailable
        import math

        lat1, lon1, lat2, lon2 = map(math.radians, (pa.lat, pa.lon, pb.lat, pb.lon))
        h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        gc_nm = 2 * 3440.065 * math.asin(math.sqrt(h))
        return 1.25 * gc_nm, ((pa.lon, pa.lat), (pb.lon, pb.lat))


def load_routes(name: str = "routes_india.yaml") -> tuple[dict[str, Any], list[Route]]:
    cfg = load_yaml(name)
    routes = []
    for r in cfg["routes"]:
        route = Route(**{k: v for k, v in r.items() if k in Route.__dataclass_fields__})
        if not route.distance_nm or not route.geometry:
            dist, coords = _sea_route(route.ports[0], route.ports[1])
            if not route.distance_nm:
                route.distance_nm = dist
            route.geometry = [list(c) for c in coords]
        routes.append(route)
    meta = {k: v for k, v in cfg.items() if k != "routes"}
    return meta, routes


NETWORKS = {
    "india": "routes_india.yaml",
    "eu": "routes_eu.yaml",
}


def regulations() -> dict[str, Any]:
    return raw("regulations.yaml")


def prices() -> dict[str, Any]:
    return raw("prices.yaml")
