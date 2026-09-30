"""Large-scale synthetic networks for scalability tests and the large-scale demonstration.

Routes connect real ports from ``ports.yaml`` (real sea distances via ``searoute``); cargo
type, demand and service pattern are sampled so each route is servable by the vessel
classes of its cargo type. Fleet availability scales with the network so that a 100-route
instance deploys 500+ ships (PS Delivery Table item 5: large-scale scenario).
"""

from __future__ import annotations

import math

import numpy as np

from greenfleet.config import _sea_route, ports, vessel_classes
from greenfleet.scenarios.scenario import Scenario

CARGO_CLASSES = {
    "container": ["FEEDER", "PANAMAX_C", "NEOPANAMAX_C"],
    "bulk": ["HANDYSIZE", "SUPRAMAX", "PANAMAX_B"],
    "tanker": ["MR_TANKER", "AFRAMAX"],
    "pax": ["ISLAND_ROPAX", "ROPAX"],
}
CARGO_MIX = {"container": 0.45, "bulk": 0.25, "tanker": 0.2, "pax": 0.1}
EU = {"NL", "DE", "ES", "SE", "GR", "IT"}


def synthetic_routes(n_routes: int, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    port_ids = sorted(ports())
    routes: list[dict] = []
    tries = 0
    while len(routes) < n_routes and tries < 50 * n_routes:
        tries += 1
        a, b = rng.choice(port_ids, 2, replace=False)
        cargo = rng.choice(list(CARGO_MIX), p=list(CARGO_MIX.values()))
        dist, coords = _sea_route(a, b)
        limit = 1500 if cargo == "pax" else 8000
        if not (150 <= dist <= limit):
            continue
        classes = CARGO_CLASSES[cargo]
        if cargo == "pax" and dist > 600:
            classes = ["ROPAX"]
        ca, cb = ports()[a].country, ports()[b].country
        eu_scope = 1.0 if (ca in EU and cb in EU) else 0.5 if (ca in EU or cb in EU) else 0.0
        if cargo in ("container", "pax"):
            service = "liner"
            demand = float(rng.uniform(600, 7000) if cargo == "container" else rng.uniform(300, 2500))
        else:
            service = "tramp"
            demand = float(rng.uniform(1.5e6, 9e6) if cargo == "bulk" else rng.uniform(3e6, 12e6))
        routes.append({
            "id": f"S{len(routes) + 1:03d}", "name": f"{ports()[a].name} - {ports()[b].name} ({cargo})",
            "ports": [a, b], "service": service, "cargo": cargo, "demand": round(demand, 0),
            "load_factor": 0.97 if service == "tramp" else 0.85,
            "port_hours": float(rng.uniform(24, 48) if service == "liner" else rng.uniform(56, 90)),
            "beaufort": float(rng.uniform(3.0, 5.0)), "delay_mean": 0.02, "delay_sd": float(rng.uniform(0.04, 0.06)),
            "port_delay_sd_h": float(rng.uniform(4, 16)), "eu_scope": eu_scope, "classes": classes,
            "distance_nm": dist, "geometry": [list(c) for c in coords],
        })
    return routes


def synthetic_scenario(n_routes: int, seed: int = 0, year: int = 2030, certify: bool = True, **kw) -> Scenario:
    """Synthetic network with ``n_routes`` services, certified feasible by the exact MILP.

    Routes with no individually feasible option (e.g. very long services that cannot meet the
    on-time requirement with the allowed extra ships) are discarded, and fleet availability is
    scaled up until the multiple-choice MILP finds a feasible fleet plan.
    """
    from dataclasses import replace

    from greenfleet.optimization.milp import FleetMILP
    from greenfleet.optimization.options import enumerate_options
    from greenfleet.optimization.problem import FleetProblem
    from greenfleet.scenarios.scenario import resolve

    base = {cid: vc.available for cid, vc in vessel_classes().items()}
    scale = max(1.0, n_routes / 12.0) * 1.25
    availability = {cid: int(math.ceil(n * scale)) for cid, n in base.items()}
    routes = synthetic_routes(n_routes if not certify else int(n_routes * 1.3) + 5, seed)
    sc = Scenario(network="synthetic", year=year, custom_routes=routes, fleet_availability=availability, **kw)
    if not certify:
        return sc
    probe = replace(sc, speed_levels=5)
    opts = enumerate_options(FleetProblem(resolve(probe)), 5)
    keep = [r for r, o in zip(routes, opts) if not o.fallback][:n_routes]
    for i, r in enumerate(keep):
        r["id"] = f"S{i + 1:03d}"
    sc = replace(sc, custom_routes=keep)
    for _ in range(6):
        probe = replace(sc, speed_levels=5)
        problem = FleetProblem(resolve(probe))
        if FleetMILP(problem, enumerate_options(problem, 5), time_limit=120).minimize("cost").genes is not None:
            break
        sc = replace(sc, fleet_availability={k: int(math.ceil(v * 1.2)) for k, v in sc.fleet_availability.items()})
    return sc
