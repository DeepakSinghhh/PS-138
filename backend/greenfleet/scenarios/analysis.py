"""Decision analytics on top of the optimizer: knee point, explanations, robustness, MACC, timeline."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from greenfleet.config import fuel_library
from greenfleet.optimization.archive import Tracker
from greenfleet.optimization.problem import FleetProblem, Genes
from greenfleet.optimization.qmoea import QMOEAH
from greenfleet.scenarios.scenario import Scenario, resolve


# ------------------------------------------------------------------ knee point
def knee_point(F: np.ndarray) -> int:
    """Solution closest to the ideal point in normalised objective space (balanced compromise)."""
    if len(F) == 1:
        return 0
    lo, hi = F.min(axis=0), F.max(axis=0)
    Z = (F - lo) / np.where(hi - lo > 0, hi - lo, 1.0)
    return int(np.argmin(np.linalg.norm(Z, axis=1)))


def pick(F: np.ndarray, objectives: list[str], preference: str = "balanced") -> int:
    if preference in objectives:
        return int(np.argmin(F[:, objectives.index(preference)]))
    return knee_point(F)


# ------------------------------------------------------------------ explanation
def explain(problem: FleetProblem, genes: Genes, i: int = 0) -> dict:
    """Plain-language comparison of a plan with the current-practice reference (template, no LLM)."""
    plan = problem.describe(genes, i)
    base = problem.describe(problem.baseline_genes("current_practice"))
    slow = problem.describe(problem.baseline_genes("slow_steaming"))
    po, bo, so = plan["objectives"], base["objectives"], slow["objectives"]
    delta = {k: 100.0 * (po[k] - bo[k]) / bo[k] if bo[k] else 0.0 for k in ("fuel", "emissions", "cost")}
    delta_slow = {k: 100.0 * (po[k] - so[k]) / so[k] if so[k] else 0.0 for k in ("fuel", "emissions", "cost")}
    lib = fuel_library()
    switched = [r for r, b in zip(plan["routes"], base["routes"]) if r["fuel"] != b["fuel"]]
    slower = [(r, b) for r, b in zip(plan["routes"], base["routes"]) if r["speed_kn"] < b["speed_kn"] - 0.3]
    ops = [r for r in plan["routes"] if r["shore_power"]]
    extra = plan["fleet"]["ships"] - base["fleet"]["ships"]
    by_family: dict[str, list[str]] = {}
    for r in switched:
        by_family.setdefault(lib.fuels[r["fuel"]].family, []).append(r["route_id"])
    sentences = [
        f"This plan changes well-to-wake GHG by {delta['emissions']:+.1f} %, fuel by {delta['fuel']:+.1f} % and annual "
        f"cost by {delta['cost']:+.1f} % compared with current practice (VLSFO at the fastest schedule-feasible speed).",
        f"Against a slow-steaming VLSFO fleet it changes GHG by {delta_slow['emissions']:+.1f} %, fuel by "
        f"{delta_slow['fuel']:+.1f} % and cost by {delta_slow['cost']:+.1f} %.",
    ]
    if switched:
        names = {"conventional": "conventional oil", "lng": "LNG", "methanol": "methanol", "ammonia": "ammonia",
                 "hydrogen": "hydrogen"}
        parts = [f"{names.get(fam, fam)} on {', '.join(ids)}" for fam, ids in by_family.items()]
        sentences.append("Fuel switches: " + "; ".join(parts) + ".")
    if slower:
        avg = np.mean([100 * (b["speed_kn"] - r["speed_kn"]) / b["speed_kn"] for r, b in slower])
        sentences.append(f"Slow steaming on {len(slower)} services (average speed -{avg:.0f} %), "
                         f"with {extra:+d} ships overall to keep weekly frequencies and throughput.")
    if ops:
        sentences.append(f"Shore power at berth on {len(ops)} services ({', '.join(r['route_id'] for r in ops)}).")
    ratings = [r["cii"]["rating"] for r in plan["routes"]]
    sentences.append("CII ratings: " + ", ".join(f"{k}: {ratings.count(k)}" for k in "ABCDE" if ratings.count(k)) + ".")
    fe = plan["fleet"]["fueleu"]
    if fe["in_scope_energy_gj"] > 0:
        state = "surplus" if fe["balance_t_co2e"] >= 0 else "deficit"
        sentences.append(f"FuelEU pool intensity {fe['intensity_g_per_mj']:.1f} vs target {fe['target_g_per_mj']:.1f} "
                         f"gCO2e/MJ ({state} of {abs(fe['balance_t_co2e']):,.0f} t CO2e, penalty "
                         f"USD {fe['penalty_usd'] / 1e6:.2f} M).")
    if not plan["feasible"]:
        sentences.append("Warning: this plan violates at least one constraint: " +
                         ", ".join(k for k, v in plan["violations"].items() if v > 0) + ".")
    return {"summary": " ".join(sentences), "sentences": sentences, "delta_pct": delta,
            "delta_pct_vs_slow_steaming": delta_slow, "baseline": bo, "slow_steaming_baseline": so, "plan": po}


# ------------------------------------------------------------------ robustness (Monte Carlo)
def robustness(problem: FleetProblem, genes: Genes, n_samples: int = 400, seed: int = 0,
               price_sigma: float = 0.25, carbon_range: float = 0.3, weather_sd: float = 0.5) -> dict:
    """Distribution of cost / emissions / fuel under price, carbon-price and weather uncertainty."""
    rng = np.random.default_rng(seed)
    sc = problem.rs.scenario
    # weather sensitivity from +/-1 Beaufort re-builds of the problem (interpolated per sample)
    energy = {}
    for shift in (-1.0, 0.0, 1.0):
        if shift == 0.0:
            p = problem
        else:
            rs = resolve(sc)
            for r in rs.routes:
                r.beaufort = max(0.0, r.beaufort + shift)
            p = FleetProblem(rs, correction=problem.correction)
        _, _, parts = p.evaluate(genes, return_parts=True)
        energy[shift] = parts["route"]["energy"][0]
    _, _, parts = problem.evaluate(genes, return_parts=True)
    b = {k: v[0] for k, v in parts["route"].items()}
    fuel_ids = [problem.fuel_ids[f] for f in b["fuel"]]
    base_energy = energy[0.0]
    out = {"cost": [], "emissions": [], "fuel": []}
    families = sorted({fuel_library().fuels[f].family for f in fuel_ids})
    for _ in range(n_samples):
        mult = {fam: float(rng.lognormal(0.0, price_sigma)) for fam in families}
        carbon = float(rng.uniform(1 - carbon_range, 1 + carbon_range))
        dz = float(rng.normal(0.0, weather_sd))
        e = base_energy + (energy[1.0] - base_energy) * max(dz, 0) + (base_energy - energy[-1.0]) * min(dz, 0)
        scale = e / np.maximum(base_energy, 1e-9)
        fam_mult = np.array([mult[fuel_library().fuels[f].family] for f in fuel_ids])
        cost = (b["charter"] + b["fuel_cost"] * scale * fam_mult + b["elec_cost"]
                + (b["ets_cost"] + b["levy_cost"]) * scale * carbon).sum()
        out["cost"].append(cost / 1e6)
        out["emissions"].append(float((b["wtw"] * scale).sum()))
        out["fuel"].append(float(e.sum() / 40500.0))

    def stats(x):
        x = np.sort(np.asarray(x))
        p95 = float(np.quantile(x, 0.95))
        return {"mean": float(x.mean()), "p5": float(np.quantile(x, 0.05)), "p50": float(np.median(x)),
                "p95": p95, "cvar95": float(x[x >= p95].mean()), "samples": x[:: max(1, len(x) // 200)].tolist()}

    return {k: stats(v) for k, v in out.items()}


# ------------------------------------------------------------------ MACC
MEASURES = [
    ("Slow steaming (+1 ship where needed)", "slow"),
    ("Shore power at berth", "ops"),
    ("LNG (high-pressure dual-fuel)", "LNG_HP"),
    ("Bio-LNG", "BIO_LNG"),
    ("Bio-methanol", "METHANOL_BIO"),
    ("e-Methanol", "METHANOL_E"),
    ("e-Ammonia", "AMMONIA_E"),
    ("Liquid e-hydrogen", "H2_E"),
]


def macc(problem: FleetProblem) -> dict:
    """Marginal abatement cost of single measures applied fleet-wide to the current-practice plan."""
    base = problem.baseline_genes("current_practice")
    Fb, CVb, pb = problem.evaluate(base, return_parts=True)
    ob = pb["objectives_all"]
    rows = []
    for label, key in MEASURES:
        g = Genes(base.cat.copy(), base.u.copy())
        applied = []
        for r in range(problem.R):
            if key == "slow":
                g.u[0, r] = 0.0
                g.cat[0, 4 * r + 3] = min(1, problem.E - 1)
                applied.append(r)
            elif key == "ops":
                if len(problem.route_ops[r]) > 1:
                    g.cat[0, 4 * r + 2] = 1
                    applied.append(r)
            else:
                fuels = [problem.fuel_ids[f] for f in problem.route_fuels[r]]
                if key in fuels:
                    g.cat[0, 4 * r + 1] = fuels.index(key)
                    applied.append(r)
        if not applied:
            continue
        F, CV, parts = problem.evaluate(g, return_parts=True)
        o = parts["objectives_all"]
        d_em = float(o["emissions"][0] - ob["emissions"][0])
        d_cost = float(o["cost"][0] - ob["cost"][0]) * 1e6
        rows.append({
            "measure": label, "routes": [problem.rs.routes[r].id for r in applied],
            "abatement_t": -d_em, "delta_cost_usd": d_cost,
            "usd_per_t": d_cost / -d_em if d_em < 0 else None,
            "delta_fuel_t": float(o["fuel"][0] - ob["fuel"][0]), "feasible": bool(CV[0] <= 1e-9),
        })
    rows.sort(key=lambda r: (r["usd_per_t"] is None, r["usd_per_t"] if r["usd_per_t"] is not None else 0))
    return {"baseline": {k: float(v[0]) for k, v in ob.items()}, "measures": rows}


# ------------------------------------------------------------------ transition timeline
def timeline(scenario: Scenario, years=(2025, 2030, 2035, 2040, 2045, 2050), budget: int = 4000,
             seed: int = 0, preference: str = "cost") -> dict:
    """Optimise each milestone year and report the chosen plan's fuel mix and KPIs."""
    rows = []
    for y in years:
        sc = replace(scenario, year=int(y))
        problem = FleetProblem(resolve(sc))
        tr = Tracker(problem, budget)
        QMOEAH(problem, seed=seed).run(tr)
        arch = tr.archive
        i = pick(arch.F, problem.objectives, preference) if arch.feasible else int(np.argmin(arch.CV))
        d = problem.describe(arch.genes, i)
        rows.append({
            "year": int(y), "feasible": d["feasible"], "objectives": d["objectives"],
            "fuel_mix": d["fleet"]["fuel_mix_energy_share"],
            "fueleu": d["fleet"]["fueleu"], "ships": d["fleet"]["ships"],
            "cii_ratings": [r["cii"]["rating"] for r in d["routes"]],
            "shore_power_routes": d["fleet"]["shore_power_routes"],
            "avg_speed_kn": float(np.mean([r["speed_kn"] for r in d["routes"]])),
        })
    return {"preference": preference, "rows": rows}
