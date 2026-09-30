"""Service layer behind the HTTP API (framework-free, directly testable)."""

from __future__ import annotations

import functools
import hashlib
import json
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from greenfleet.config import (
    ARTIFACTS_DIR,
    NETWORKS,
    REPORTS_DIR,
    fuel_library,
    load_routes,
    ports,
    regulations,
    vessel_classes,
)
from greenfleet.data.schema import add_derived
from greenfleet.optimization.archive import Tracker
from greenfleet.optimization.classical_moo import run_pymoo
from greenfleet.optimization.problem import FleetProblem, Genes, state_draft_ratio
from greenfleet.optimization.qmoea import QMOEAH, QMOEARegister
from greenfleet.optimization.swarm import MOPSO, MOQPSO, RandomSearchMO
from greenfleet.physics.emissions import burn, wtw_g_per_mj
from greenfleet.prediction.physics_model import NominalPhysics
from greenfleet.regulations import cii, fueleu
from greenfleet.scenarios import analysis as A
from greenfleet.scenarios.instances import synthetic_routes
from greenfleet.scenarios.scenario import OBJECTIVE_LABELS, Scenario, resolve

ALGORITHMS = {
    "QMOEA-H": ("QMOEA-H (quantum-inspired, ours)", lambda p, t, s, cb: QMOEAH(p, seed=s).run(t, callback=cb)),
    "MOQPSO": ("MOQPSO (quantum-inspired)", lambda p, t, s, cb: MOQPSO(p, seed=s).run(t, callback=cb)),
    "QMOEA-R": ("QMOEA-R (register population)", lambda p, t, s, cb: QMOEARegister(p, seed=s).run(t, callback=cb)),
    "MOPSO": ("MOPSO (classical)", lambda p, t, s, cb: MOPSO(p, seed=s).run(t, callback=cb)),
    "NSGA-II": ("NSGA-II (classical)", lambda p, t, s, cb: run_pymoo("NSGA-II", p, t, s, callback=cb)),
    "NSGA-III": ("NSGA-III (classical)", lambda p, t, s, cb: run_pymoo("NSGA-III", p, t, s, callback=cb)),
    "SPEA2": ("SPEA2 (classical)", lambda p, t, s, cb: run_pymoo("SPEA2", p, t, s, callback=cb)),
    "Random": ("Random search", lambda p, t, s, cb: RandomSearchMO(p, seed=s).run(t, callback=cb)),
}

_problem_lock = threading.Lock()
_problems: dict[str, FleetProblem] = {}


def scenario_key(sc: Scenario) -> str:
    return hashlib.sha1(json.dumps(sc.to_dict(), sort_keys=True, default=str).encode()).hexdigest()


def get_problem(sc: Scenario) -> FleetProblem:
    key = scenario_key(sc)
    with _problem_lock:
        if key not in _problems:
            if len(_problems) > 24:
                _problems.pop(next(iter(_problems)))
            _problems[key] = FleetProblem(resolve(sc))
        return _problems[key]


def genes_to_json(g: Genes) -> dict:
    return {"cat": g.cat.astype(int).tolist(), "u": np.round(g.u, 6).tolist()}


def genes_from_json(d: dict) -> Genes:
    return Genes(np.asarray(d["cat"], dtype=int).reshape(len(d["cat"]), -1), np.asarray(d["u"], dtype=float))


# ------------------------------------------------------------------ metadata
@functools.lru_cache(maxsize=1)
def meta() -> dict:
    lib = fuel_library()
    fuels = []
    for fid, f in lib.fuels.items():
        fam = lib.families[f.family]
        fuels.append({"id": fid, "label": f.label, "family": f.family, "family_label": fam.label, "pathway": f.pathway,
                      "wtw_g_per_mj": wtw_g_per_mj(f, lib), "lcv_mj_per_kg": f.lcv_mj_per_g * 1000,
                      "rfnbo": f.rfnbo, "range_nm": fam.range_nm, "charter_premium": fam.charter_premium,
                      "capacity_loss": fam.capacity_loss, "source": f.source})
    classes = [{"id": c.id, "label": c.label, "cargo": c.cargo, "capacity": c.capacity, "capacity_unit": c.capacity_unit,
                "dwt": c.dwt, "gt": c.gt, "design_speed_kn": c.design_speed_kn, "min_speed_kn": c.min_speed_kn,
                "max_speed_kn": c.max_speed_kn, "mcr_kw": c.mcr_kw, "available": c.available,
                "charter_usd_per_day": c.charter_usd_per_day} for c in vessel_classes().values()]
    port_list = [{"id": p.id, "name": p.name, "lon": p.lon, "lat": p.lat, "country": p.country, "ops_from": p.ops_from,
                  "bunkers": p.bunkers} for p in ports().values()]
    networks = {}
    for key, fname in NETWORKS.items():
        m, routes = load_routes(fname)
        networks[key] = {"name": m.get("name", key), "description": m.get("description", ""), "routes": len(routes)}
    reg = regulations()
    return {
        "fuels": fuels, "vessel_classes": classes, "ports": port_list, "networks": networks,
        "objectives": OBJECTIVE_LABELS, "algorithms": {k: v[0] for k, v in ALGORITHMS.items()},
        "default_scenario": Scenario().to_dict(),
        "regulations": {
            "cii_reduction_pct": reg["cii"]["reduction_pct"],
            "fueleu_targets": {int(y): fueleu.target_intensity(int(y)) for y in (2025, 2030, 2035, 2040, 2045, 2050)},
            "fueleu_reference": reg["fueleu"]["reference_g_per_mj"],
            "ets_phase_in": reg["eu_ets"]["phase_in"],
        },
    }


def network(sc: Scenario) -> dict:
    p = get_problem(sc)
    rs = p.rs
    lib = fuel_library()
    routes = []
    for r, route in enumerate(rs.routes):
        routes.append({
            "id": route.id, "name": route.name, "ports": route.ports, "service": route.service, "cargo": route.cargo,
            "demand": route.demand, "demand_unit": ("per week" if route.service == "liner" else "per year"),
            "distance_nm": route.distance_nm, "geometry": route.geometry, "classes": route.classes,
            "fuels": [{"id": f, "label": lib.fuels[f].label, "family": lib.fuels[f].family} for f in rs.route_fuels[r]],
            "shore_power_share": rs.route_ops_share[r], "eu_scope": route.eu_scope, "beaufort": route.beaufort,
        })
    base = p.describe(p.baseline_genes("current_practice"))
    slow = p.describe(p.baseline_genes("slow_steaming"))
    return {"name": rs.name, "year": rs.year, "routes": routes, "notes": rs.notes,
            "prices": {"fuel_usd_per_t": rs.fuel_price, "ets_usd_per_t": rs.ets_price_usd, "levy_usd_per_t": rs.global_levy_usd},
            "fueleu_target": p.fe_target, "cii_reduction_pct": cii.reduction_pct(rs.year),
            "baselines": {"current_practice": base, "slow_steaming": slow},
            "baseline_genes": {"current_practice": genes_to_json(p.baseline_genes("current_practice")),
                               "slow_steaming": genes_to_json(p.baseline_genes("slow_steaming"))}}


# ------------------------------------------------------------------ prediction
@functools.lru_cache(maxsize=1)
def _model():
    from greenfleet.prediction.train import load_model

    try:
        return load_model()
    except Exception:
        return None


def model_card() -> dict:
    path = ARTIFACTS_DIR / "qphys_meta.json"
    if not path.exists():
        return {"available": False, "note": "run `make train` to train Q-PHYS; predictions fall back to physics"}
    with open(path) as fh:
        meta_ = json.load(fh)
    meta_["available"] = True
    return meta_


def _prediction_frame(vessel_class: str, speeds: np.ndarray, load_ratio: float, wind_speed_ms: float,
                      wind_rel_deg: float, wave_height_m: float, wave_rel_deg: float,
                      days_since_cleaning: float, trim_m: float = 0.3, current_kn: float = 0.0,
                      ship_id: str | None = None) -> pd.DataFrame:
    vc = vessel_classes()[vessel_class]
    dr = state_draft_ratio(vc, load_ratio)
    rows = [{
        "ship_id": ship_id or f"{vessel_class}-new", "vessel_class": vessel_class, "vessel_type": vc.cargo,
        "speed_kn": float(s), "load_ratio": load_ratio, "draft_ratio": dr, "trim_m": trim_m,
        "days_since_cleaning": days_since_cleaning, "wind_speed_ms": wind_speed_ms, "wind_rel_deg": wind_rel_deg,
        "wave_height_m": wave_height_m, "wave_rel_deg": wave_rel_deg, "current_kn": current_kn,
        "design_speed_kn": vc.design_speed_kn, "mcr_kw": vc.mcr_kw, "displacement_t": vc.displacement_t,
        "length_m": vc.length_m, "block_coefficient": vc.block_coefficient, "aux_sea_kw": vc.aux_sea_kw,
    } for s in speeds]
    return add_derived(pd.DataFrame(rows))


def predict(req: dict) -> dict:
    vc = vessel_classes()[req["vessel_class"]]
    lib = fuel_library()
    fuel_id = req.get("fuel", "VLSFO")
    speeds = np.round(np.linspace(vc.min_speed_kn, vc.max_speed_kn, 25), 3)
    args = dict(load_ratio=float(req.get("load_ratio", 0.9)), wind_speed_ms=float(req.get("wind_speed_ms", 6.0)),
                wind_rel_deg=float(req.get("wind_rel_deg", 45.0)), wave_height_m=float(req.get("wave_height_m", 1.5)),
                wave_rel_deg=float(req.get("wave_rel_deg", 45.0)),
                days_since_cleaning=float(req.get("days_since_cleaning", 365.0)), ship_id=req.get("ship_id"))
    speed = float(req.get("speed_kn", vc.design_speed_kn * 0.8))
    df = _prediction_frame(vc.id, np.concatenate([[speed], speeds]), **args)
    nominal = NominalPhysics().predict(df)
    model = _model()
    if model is not None:
        p, lo, hi = model.predict_interval(df)
        source = "Q-PHYS (quantum-inspired hybrid)"
    else:
        p, lo, hi = nominal, nominal * 0.9, nominal * 1.1
        source = "physics (Q-PHYS not trained)"
    fam = lib.family_of(fuel_id)
    energy = p[0] * 1e6 * lib.fuels["HFO"].lcv_mj_per_g * fam.bsec_mj_per_kwh / 7.0   # MJ/day for the chosen fuel system
    b = burn(energy, fuel_id)
    return {
        "source": source, "vessel_class": vc.id, "speed_kn": speed,
        "fuel_hfo_eq_tpd": float(p[0]), "interval_tpd": [float(lo[0]), float(hi[0])],
        "physics_nominal_tpd": float(nominal[0]),
        "fuel": fuel_id, "fuel_label": lib.fuels[fuel_id].label,
        "fuel_mass_tpd": b.fuel_t, "co2_ttw_tpd": b.co2_t, "wtw_co2e_tpd": b.wtw_co2e_t,
        "fuel_per_nm_kg": float(p[0] * 1000 / (24 * speed)),
        "curve": {"speed_kn": speeds.tolist(), "fuel_tpd": p[1:].tolist(), "lo": lo[1:].tolist(), "hi": hi[1:].tolist(),
                  "physics_tpd": nominal[1:].tolist(),
                  "fuel_per_nm_kg": (p[1:] * 1000 / (24 * speeds)).tolist()},
    }


# ------------------------------------------------------------------ optimization
def front_payload(problem: FleetProblem, genes: Genes, F: np.ndarray, CV: np.ndarray) -> dict:
    feas = CV <= 1e-9
    idx = np.nonzero(feas)[0] if feas.any() else np.argsort(CV)[:10]
    F, genes = F[idx], genes.take(idx)
    knee = A.knee_point(F)
    sols = []
    for i in range(len(F)):
        sols.append({"i": i, "objectives": dict(zip(problem.objectives, map(float, F[i]))),
                     "genes": genes_to_json(genes.take([i]))})
    picks = {"balanced": knee}
    for k, obj in enumerate(problem.objectives):
        picks[f"min_{obj}"] = int(np.argmin(F[:, k]))
    return {"objectives": problem.objectives, "labels": {k: OBJECTIVE_LABELS[k] for k in problem.objectives},
            "feasible": bool(feas.any()), "solutions": sols, "picks": picks,
            "recommended": problem.describe(genes, knee), "explanation": A.explain(problem, genes, knee)}


def run_optimization(job, sc: Scenario, algorithm: str = "QMOEA-H", budget: int = 6000, seed: int = 0) -> dict:
    problem = get_problem(sc)
    name, fn = ALGORITHMS[algorithm]
    tracker = Tracker(problem, budget, n_snapshots=25)
    state = {"last": 0}

    def cb(rec: dict, archive) -> None:
        nfe = rec.get("nfe", tracker.nfe)
        job.progress = min(0.99, nfe / budget)
        if nfe - state["last"] >= budget / 40 or nfe >= budget:
            state["last"] = nfe
            F = archive.F if archive.feasible else np.zeros((0, problem.n_obj))
            job.emit({"type": "progress", "nfe": int(nfe), "budget": budget, "feasible": bool(archive.feasible),
                      "front": np.round(F, 3).tolist(), "entropy": rec.get("entropy")})

    fn(problem, tracker, seed, cb)
    arch = tracker.archive
    payload = front_payload(problem, arch.genes, arch.F, arch.CV)
    payload.update({"algorithm": name, "budget": budget, "evaluations": tracker.nfe,
                    "convergence": [{"nfe": s["nfe"], "seconds": s["seconds"], "front_size": len(s["F"]),
                                     "feasible": s["feasible"]} for s in tracker.snapshots],
                    "scenario": sc.to_dict()})
    return payload


def evaluate(sc: Scenario, genes: Genes) -> dict:
    problem = get_problem(sc)
    out = problem.describe(genes)
    out["explanation"] = A.explain(problem, genes)
    return out


def plan_to_genes(sc: Scenario, plan: list[dict]) -> Genes:
    """Build genes from a human-readable plan: [{route_id, vessel_class, fuel, shore_power, extra_ships, speed_u}]."""
    problem = get_problem(sc)
    g = problem.baseline_genes("current_practice")
    ids = [r.id for r in problem.rs.routes]
    for item in plan:
        r = ids.index(item["route_id"])
        if "vessel_class" in item:
            opts = [problem.class_ids[c] for c in problem.route_classes[r]]
            g.cat[0, 4 * r] = opts.index(item["vessel_class"])
        if "fuel" in item:
            opts = [problem.fuel_ids[f] for f in problem.route_fuels[r]]
            g.cat[0, 4 * r + 1] = opts.index(item["fuel"])
        if "shore_power" in item:
            g.cat[0, 4 * r + 2] = int(bool(item["shore_power"]) and len(problem.route_ops[r]) > 1)
        if "extra_ships" in item:
            g.cat[0, 4 * r + 3] = int(np.clip(item["extra_ships"], 0, problem.E - 1))
        if "speed_u" in item:
            g.u[0, r] = float(np.clip(item["speed_u"], 0, 1))
    return g


def robustness(sc: Scenario, genes: Genes, n: int = 400) -> dict:
    return A.robustness(get_problem(sc), genes, n_samples=n)


def macc(sc: Scenario) -> dict:
    return A.macc(get_problem(sc))


def run_timeline(job, sc: Scenario, years: list[int], budget: int, preference: str) -> dict:
    rows = []
    for k, y in enumerate(years):
        res = A.timeline(sc, years=(y,), budget=budget, preference=preference)
        rows.extend(res["rows"])
        job.progress = (k + 1) / len(years)
        job.emit({"type": "progress", "year": y, "done": k + 1, "total": len(years)})
    return {"preference": preference, "rows": rows}


def run_exact(sc: Scenario, objective: str) -> dict:
    from dataclasses import replace

    from greenfleet.optimization.milp import FleetMILP
    from greenfleet.optimization.options import enumerate_options

    disc = replace(sc, speed_levels=sc.speed_levels or 5)
    problem = get_problem(disc)
    opts = enumerate_options(problem, disc.speed_levels)
    res = FleetMILP(problem, opts).minimize(objective)
    if res.genes is None:
        return {"status": res.status}
    out = problem.describe(res.genes)
    out.update({"status": res.status, "seconds": res.seconds, "options_per_route": [len(o) for o in opts],
                "genes": genes_to_json(res.genes), "speed_levels": disc.speed_levels})
    return out


def run_qubo(job, sc: Scenario, weights: dict, solver: str) -> dict:
    from dataclasses import replace

    from greenfleet.optimization import qubo as QB
    from greenfleet.optimization.milp import FleetMILP
    from greenfleet.optimization.options import enumerate_options, objective_scales

    disc = replace(sc, speed_levels=sc.speed_levels or 5)
    problem = get_problem(disc)
    opts = enumerate_options(problem, disc.speed_levels)
    scales = objective_scales(opts)
    job.emit({"type": "progress", "stage": "exact reference (MILP)"})
    ref = FleetMILP(problem, opts).weighted(weights)
    v_opt = QB.weighted_value(problem, ref.genes, weights, scales)
    job.emit({"type": "progress", "stage": f"annealing ({solver})"})
    out = QB.solve_qubo(problem, opts, weights, solver)
    fq = QB.build_qubo(problem, opts, weights)
    val = QB.weighted_value(problem, out.genes, weights, scales)
    return {"solver": out.solver, "qubo_variables": fq.n_vars, "iterations": out.iterations, "seconds": out.seconds,
            "gap_pct_vs_exact": 100 * (val - v_opt) / v_opt, "plan": problem.describe(out.genes),
            "exact_plan_objectives": problem.describe(ref.genes)["objectives"], "genes": genes_to_json(out.genes),
            "dwave_ready": {"variables": fq.n_vars, "format": "dimod.BinaryQuadraticModel (QB.export_bqm)"}}


def benchmarks() -> dict:
    out = {}
    for name in ("prediction_benchmark", "optimization_benchmark"):
        path = REPORTS_DIR / f"{name}.json"
        if path.exists():
            with open(path) as fh:
                out[name] = json.load(fh)
    return out


def parse_routes_csv(text: str) -> list[dict]:
    """CSV columns: id,name,port_a,port_b,service,cargo,demand[,classes (| separated),load_factor,port_hours,...]."""
    from io import StringIO

    df = pd.read_csv(StringIO(text))
    df.columns = [c.strip().lower() for c in df.columns]
    required = {"port_a", "port_b", "service", "cargo", "demand"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    known = ports()
    defaults = {"container": ["FEEDER", "PANAMAX_C", "NEOPANAMAX_C"], "bulk": ["HANDYSIZE", "SUPRAMAX", "PANAMAX_B"],
                "tanker": ["MR_TANKER", "AFRAMAX"], "pax": ["ISLAND_ROPAX", "ROPAX"]}
    out = []
    for i, row in df.iterrows():
        a, b = str(row["port_a"]).strip().upper(), str(row["port_b"]).strip().upper()
        if a not in known or b not in known:
            raise ValueError(f"row {i + 1}: unknown port {a if a not in known else b}; known ports: {sorted(known)}")
        cargo = str(row["cargo"]).strip().lower()
        classes = (str(row["classes"]).split("|") if "classes" in df and pd.notna(row.get("classes")) else defaults[cargo])
        item = {"id": str(row.get("id", f"U{i + 1:02d}")), "name": str(row.get("name", f"{a} - {b}")),
                "ports": [a, b], "service": str(row["service"]).strip().lower(), "cargo": cargo,
                "demand": float(row["demand"]), "classes": [c.strip() for c in classes]}
        for opt in ("load_factor", "port_hours", "beaufort", "eu_scope", "delay_sd", "port_delay_sd_h"):
            if opt in df and pd.notna(row.get(opt)):
                item[opt] = float(row[opt])
        out.append(item)
    return out


def example_routes_csv() -> str:
    rows = ["id,name,port_a,port_b,service,cargo,demand,classes"]
    for r in synthetic_routes(4, seed=1):
        rows.append(f"{r['id']},{r['name'].split(' (')[0]},{r['ports'][0]},{r['ports'][1]},{r['service']},"
                    f"{r['cargo']},{r['demand']:.0f},{'|'.join(r['classes'])}")
    return "\n".join(rows) + "\n"


def static_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"
