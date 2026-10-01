"""Optimization benchmark: QMOEA-H versus conventional methods (PS objective 5).

1. Solution quality & convergence speed on the India network (tuning instance) and the EU
   network (unseen during tuning): hypervolume, IGD+, spacing, evaluations to reach 95 % of
   the reference hypervolume, wall time; Mann-Whitney U and Friedman tests over seeds.
2. Exact reference: with speeds discretised, the multiple-choice MILP gives the true optimum.
   Gaps of each algorithm's best cost / emissions / fuel plans and IGD+ against the exact
   bi-objective (cost-emissions) front.
3. QUBO + annealing: from-scratch path-integral SQA vs OpenJij SQA vs classical SA on the
   fleet QUBO, gap to the exact optimum of the same weighted objective.
4. Scalability: synthetic networks with 12 -> 100+ routes (500+ ships).
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from greenfleet.optimization import metrics as M
from greenfleet.optimization.archive import Tracker, nondominated_mask
from greenfleet.optimization.classical_moo import run_pymoo
from greenfleet.optimization.milp import FleetMILP
from greenfleet.optimization.options import enumerate_options, objective_scales
from greenfleet.optimization.problem import FleetProblem
from greenfleet.optimization.qmoea import QMOEAH, QMOEAHConfig, QMOEARegister
from greenfleet.optimization.swarm import MOPSO, MOQPSO, RandomSearchMO
from greenfleet.optimization.warmstart import exact_seeds
from greenfleet.scenarios.instances import synthetic_scenario
from greenfleet.scenarios.scenario import Scenario, resolve

OURS = "QMOEA-H (ours)"
HYBRID = "QMOEA-H + exact seeds (hybrid)"
NSGA_SEEDED = "NSGA-II + exact seeds"
ALGORITHMS = {
    OURS: lambda p, t, s: QMOEAH(p, seed=s).run(t),
    # warm-started variants: the MILP seeds are recomputed inside every run, so their solve time is
    # included in the reported seconds; NSGA-II gets the same seeds to separate the seeds' effect from the search
    HYBRID: lambda p, t, s: QMOEAH(p, seed=s).run(t, seeds=exact_seeds(p).genes),
    NSGA_SEEDED: lambda p, t, s: run_pymoo("NSGA-II", p, t, s, seeds=exact_seeds(p).genes),
    "QMOEA-H w/o route merge (ablation)": lambda p, t, s: QMOEAH(p, QMOEAHConfig(route_merge=0.0), seed=s).run(t),
    "MOQPSO (ablation)": lambda p, t, s: MOQPSO(p, seed=s).run(t),
    "QMOEA-R (ablation)": lambda p, t, s: QMOEARegister(p, seed=s).run(t),
    "MOPSO": lambda p, t, s: MOPSO(p, seed=s).run(t),
    "NSGA-II": lambda p, t, s: run_pymoo("NSGA-II", p, t, s),
    "NSGA-III": lambda p, t, s: run_pymoo("NSGA-III", p, t, s),
    "SPEA2": lambda p, t, s: run_pymoo("SPEA2", p, t, s),
    "MOEA/D": lambda p, t, s: run_pymoo("MOEA/D", p, t, s),
    "Random search": lambda p, t, s: RandomSearchMO(p, seed=s).run(t),
}
CORE = [OURS, "MOPSO", "NSGA-II", "NSGA-III"]
LARGE = CORE + [HYBRID, NSGA_SEEDED]      # large networks: also the MILP-warm-started variants


@dataclass
class OptBenchConfig:
    """Default = the published run (``make bench``, ~30 min); ``quick`` for smoke checks; ``full`` for 30 seeds."""
    seeds: int = 10
    budget: int = 8000
    large_budget: int = 16000
    large_seeds: int = 5
    scal_sizes: tuple[int, ...] = (12, 25, 50, 100, 200)
    scal_seeds: int = 5
    qubo_seeds: int = 5
    algorithms: list[str] = field(default_factory=lambda: list(ALGORITHMS))

    @classmethod
    def quick(cls) -> OptBenchConfig:
        return cls(seeds=3, large_seeds=2, scal_sizes=(12, 25, 50, 100), scal_seeds=1, qubo_seeds=3)

    @classmethod
    def full(cls) -> OptBenchConfig:
        return cls(seeds=30, budget=20000, large_budget=40000, large_seeds=10, scal_seeds=10, qubo_seeds=10)


def run_algorithms(problem: FleetProblem, names: list[str], seeds: int, budget: int) -> dict:
    runs: dict[str, list[dict]] = {}
    for name in names:
        runs[name] = []
        for s in range(seeds):
            tr = Tracker(problem, budget, n_snapshots=20)
            t0 = time.perf_counter()
            ALGORITHMS[name](problem, tr, s)
            feas = tr.archive.feasible
            runs[name].append({
                "seed": s, "seconds": time.perf_counter() - t0, "feasible": feas,
                "F": tr.archive.F if feas else np.zeros((0, problem.n_obj)),
                "snapshots": [(sn["nfe"], sn["F"] if sn["feasible"] else None) for sn in tr.snapshots],
                "genes": tr.archive.genes if feas else None,
            })
    return runs


def summarise(runs: dict, problem: FleetProblem) -> dict:
    fronts = [r["F"] for rs in runs.values() for r in rs if len(r["F"])]
    if not fronts:
        return {"no_feasible_plan": True, "objectives": problem.objectives,
                "table": {name: {"feasible_runs": 0, "runs": len(rs), "seconds_mean": float(np.mean([r["seconds"] for r in rs])),
                                 "hv_mean": 0.0, "hv_std": 0.0, "igd_plus_mean": None, "spacing_mean": None,
                                 "nfe_to_95pct_ref_hv": None, "reached_95pct": 0,
                                 "best_objective_mean": {k: None for k in problem.objectives}}
                          for name, rs in runs.items()},
                "curves": {}, "mann_whitney_vs_ours": {}, "friedman": None, "reference_hv": 0.0}
    ideal, nadir = M.normaliser(fronts)
    ref = M.reference_front(fronts)
    ref_hv = M.hypervolume(ref, ideal, nadir)
    table, hv_by_alg, curves = {}, {}, {}
    for name, rs in runs.items():
        hvs = [M.hypervolume(r["F"], ideal, nadir) for r in rs]
        igd = [M.igd_plus(r["F"], ref, ideal, nadir) for r in rs if len(r["F"])]
        spc = [M.spacing(r["F"], ideal, nadir) for r in rs if len(r["F"]) > 2]
        nfe95 = []
        curve = []
        for r in rs:
            pts = [(nfe, M.hypervolume(F, ideal, nadir) if F is not None else 0.0) for nfe, F in r["snapshots"]]
            curve.append([hv for _, hv in pts])
            hit = next((nfe for nfe, hv in pts if hv >= 0.95 * ref_hv), None)
            nfe95.append(hit)
        curves[name] = {"nfe": [nfe for nfe, _ in rs[0]["snapshots"]], "hv_mean": np.mean(curve, axis=0).tolist()}
        best = {k: float(np.mean([r["F"][:, i].min() for r in rs if len(r["F"])])) if any(len(r["F"]) for r in rs) else None
                for i, k in enumerate(problem.objectives)}
        table[name] = {
            "hv_mean": float(np.mean(hvs)), "hv_std": float(np.std(hvs)),
            "igd_plus_mean": float(np.mean(igd)) if igd else None,
            "spacing_mean": float(np.nanmean(spc)) if spc else None,
            "feasible_runs": int(sum(r["feasible"] for r in rs)), "runs": len(rs),
            "nfe_to_95pct_ref_hv": (float(np.mean([x for x in nfe95 if x is not None])) if any(x is not None for x in nfe95) else None),
            "reached_95pct": int(sum(x is not None for x in nfe95)),
            "seconds_mean": float(np.mean([r["seconds"] for r in rs])),
            "best_objective_mean": best,
        }
        hv_by_alg[name] = hvs
    tests = {}
    if OURS in hv_by_alg:
        for name, hvs in hv_by_alg.items():
            if name == OURS or len(hvs) < 3:
                continue
            u = stats.mannwhitneyu(hv_by_alg[OURS], hvs, alternative="greater")
            tests[name] = {"p_value": float(u.pvalue), "ours_better": bool(np.mean(hv_by_alg[OURS]) > np.mean(hvs))}
    friedman = None
    names = list(hv_by_alg)
    if len(names) >= 3 and len(hv_by_alg[names[0]]) >= 3:
        mat = np.array([hv_by_alg[n] for n in names])
        fr = stats.friedmanchisquare(*mat)
        ranks = stats.rankdata(-mat, axis=0).mean(axis=1)
        friedman = {"p_value": float(fr.pvalue), "mean_rank": dict(zip(names, map(float, ranks)))}
    return {"reference_hv": ref_hv, "table": table, "mann_whitney_vs_ours": tests, "friedman": friedman,
            "curves": curves, "ideal": ideal.tolist(), "nadir": nadir.tolist(), "objectives": problem.objectives,
            "reference_front": ref.tolist()}


def exact_comparison(cfg: OptBenchConfig, log) -> dict:
    """Discretised-speed India instance: metaheuristics vs the exact MILP optimum."""
    sc = Scenario(network="india", year=2030, speed_levels=5)
    problem = FleetProblem(resolve(sc))
    opts = enumerate_options(problem, 5)
    milp = FleetMILP(problem, opts)
    t0 = time.perf_counter()
    exact = {}
    for obj in problem.objectives:
        res = milp.minimize(obj)
        F, CV = problem.evaluate(res.genes)
        exact[obj] = {"value": float(F[0, problem.objectives.index(obj)]), "seconds": res.seconds, "status": res.status}
    front = milp.epsilon_front("cost", "emissions", 12)
    ef = np.vstack([problem.evaluate(r.genes)[0] for r in front])
    i_em, i_co = problem.objectives.index("emissions"), problem.objectives.index("cost")
    exact2d = ef[:, [i_em, i_co]]
    exact2d = exact2d[nondominated_mask(exact2d)]
    milp_secs = time.perf_counter() - t0
    log("[optimization] exact comparison: running metaheuristics on the discretised instance")
    runs = run_algorithms(problem, CORE, cfg.seeds, cfg.budget)
    out = {"milp_seconds_total": milp_secs, "exact_extremes": exact, "exact_front_cost_vs_emissions": exact2d.tolist(),
           "options_per_route": [len(o) for o in opts], "algorithms": {}}
    lo = exact2d.min(axis=0)
    hi = exact2d.max(axis=0)
    for name, rs in runs.items():
        gaps = {obj: [] for obj in problem.objectives}
        igd = []
        for r in rs:
            if not len(r["F"]):
                continue
            for obj in problem.objectives:
                best = r["F"][:, problem.objectives.index(obj)].min()
                gaps[obj].append(100 * (best - exact[obj]["value"]) / abs(exact[obj]["value"]))
            f2 = r["F"][:, [i_em, i_co]]
            f2 = f2[nondominated_mask(f2)]
            igd.append(M.igd_plus(f2, exact2d, lo, hi))
        out["algorithms"][name] = {
            "gap_pct_mean": {k: (float(np.mean(v)) if v else None) for k, v in gaps.items()},
            "igd_plus_vs_exact_front": float(np.mean(igd)) if igd else None,
            "feasible_runs": int(sum(r["feasible"] for r in rs)),
        }
    return out


def qubo_comparison(cfg: OptBenchConfig, log) -> dict:
    from greenfleet.optimization import qubo as QB

    out = {}
    for net in ("india", "eu"):
        problem = FleetProblem(resolve(Scenario(network=net, year=2030, speed_levels=5)))
        opts = enumerate_options(problem, 5)
        scales = objective_scales(opts)
        milp = FleetMILP(problem, opts)
        rows = []
        for w in ({"fuel": 1 / 3, "emissions": 1 / 3, "cost": 1 / 3}, {"cost": 1.0}, {"emissions": 0.7, "cost": 0.3}):
            ref = milp.weighted(w)
            v_opt = QB.weighted_value(problem, ref.genes, w, scales)
            fq = QB.build_qubo(problem, opts, w)
            row = {"weights": w, "exact_value": v_opt, "milp_seconds": ref.seconds, "qubo_vars_max": fq.n_vars, "solvers": {}}
            for solver in ("pi_sqa", "openjij_sqa", "openjij_sa"):
                gaps, secs, feas = [], [], []
                for s in range(cfg.qubo_seeds):
                    res = QB.solve_qubo(problem, opts, w, solver, seed=s)
                    gaps.append(100 * (QB.weighted_value(problem, res.genes, w, scales) - v_opt) / v_opt)
                    secs.append(res.seconds)
                    feas.append(bool(problem.evaluate(res.genes)[1][0] <= 1e-9))
                row["solvers"][solver] = {"gap_pct_median": float(np.median(gaps)), "gap_pct_mean": float(np.mean(gaps)),
                                          "feasible_share": float(np.mean(feas)), "seconds_mean": float(np.mean(secs))}
            rows.append(row)
        out[net] = rows
        log(f"[optimization] QUBO comparison done for {net}")
    return out


def scalability(cfg: OptBenchConfig, log, done: list[dict] | None = None, checkpoint=None) -> dict:
    rows = list(done or [])
    for n in cfg.scal_sizes:
        if any(r["routes"] == n for r in rows):      # resumed: this size is already in the checkpoint
            continue
        sc = synthetic_scenario(n, seed=7)
        problem = FleetProblem(resolve(sc))
        budget = int(cfg.budget * max(1.0, n / 12) ** 0.5)
        runs = run_algorithms(problem, LARGE, cfg.scal_seeds, budget)
        summ = summarise(runs, problem)
        opts = enumerate_options(problem, 5)
        t0 = time.perf_counter()
        exact_cost = FleetMILP(problem, opts, time_limit=300).minimize("cost")
        milp_secs = time.perf_counter() - t0
        exact_val = problem.evaluate(exact_cost.genes)[0][0, problem.objectives.index("cost")] if exact_cost.genes is not None else None
        row = {"routes": n, "ships_available": int(problem.available.sum()), "budget": budget,
               "milp_min_cost_seconds": milp_secs, "milp_status": exact_cost.status, "algorithms": {}}
        for name in LARGE:
            t = summ["table"][name]
            best_cost = t["best_objective_mean"].get("cost")
            row["algorithms"][name] = {
                "hv_mean": t["hv_mean"], "seconds_mean": t["seconds_mean"], "feasible_runs": t["feasible_runs"],
                "cost_gap_pct_vs_milp": (100 * (best_cost - exact_val) / exact_val) if (best_cost and exact_val) else None,
                "ms_per_1000_evals": 1000 * t["seconds_mean"] / budget,
            }
        rows.append(row)
        log(f"[optimization] scalability {n} routes done")
        if checkpoint:
            checkpoint(rows)
    return {"rows": sorted(rows, key=lambda r: r["routes"])}


def _checkpoint(out: dict) -> None:
    import json

    from greenfleet.config import REPORTS_DIR

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORTS_DIR / "optimization_benchmark.partial.json", "w") as fh:
        json.dump(out, fh, default=float)


def run(cfg: OptBenchConfig | None = None, log=print, resume: dict | None = None) -> dict:
    """``resume``: a partial result (``optimization_benchmark.partial.json``) whose finished stages are kept."""
    warnings.filterwarnings("ignore")
    cfg = cfg or OptBenchConfig.quick()
    t0 = time.perf_counter()
    conf = {k: (list(v) if isinstance(v, tuple) else v) for k, v in cfg.__dict__.items()}
    if resume and resume.get("config") == conf:
        out = resume
        log("[optimization] resuming: " + ", ".join(list(out.get("instances", {})) +
                                                    [k for k in ("exact", "qubo") if k in out]))
    else:
        out = {"config": conf, "instances": {}}
    prev_seconds = out.pop("elapsed_seconds", 0.0)

    def save():
        out["elapsed_seconds"] = prev_seconds + time.perf_counter() - t0
        _checkpoint(out)
        out.pop("elapsed_seconds")

    for key, sc in (("india_2030", Scenario(network="india", year=2030)),
                    ("eu_2030", Scenario(network="eu", year=2030))):
        if key in out["instances"]:
            continue
        log(f"[optimization] {key}: {len(cfg.algorithms)} algorithms x {cfg.seeds} seeds x {cfg.budget} evaluations")
        problem = FleetProblem(resolve(sc))
        runs = run_algorithms(problem, cfg.algorithms, cfg.seeds, cfg.budget)
        summ = summarise(runs, problem)
        base = problem.evaluate(problem.baseline_genes("current_practice"))[0][0]
        summ["current_practice"] = dict(zip(problem.objectives, map(float, base)))
        out["instances"][key] = summ
        save()
    if "synthetic_100_routes" not in out["instances"]:
        log("[optimization] large-scale synthetic network (100 routes)")
        big = FleetProblem(resolve(synthetic_scenario(100, seed=11)))
        runs = run_algorithms(big, LARGE, cfg.large_seeds, cfg.large_budget)
        summ = summarise(runs, big)
        summ["ships_available"] = int(big.available.sum())
        out["instances"]["synthetic_100_routes"] = summ
        save()
    if "exact" not in out:
        log("[optimization] exact MILP comparison")
        out["exact"] = exact_comparison(cfg, log)
        save()
    if "qubo" not in out:
        log("[optimization] QUBO / annealing comparison")
        out["qubo"] = qubo_comparison(cfg, log)
        save()
    log("[optimization] scalability sweep")

    def scal_checkpoint(rows):
        out["scalability_partial"] = rows
        save()

    out["scalability"] = scalability(cfg, log, out.pop("scalability_partial", None), scal_checkpoint)
    out.pop("scalability_partial", None)
    out["seconds"] = prev_seconds + time.perf_counter() - t0
    return out
