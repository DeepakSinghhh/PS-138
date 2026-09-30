"""Per-route option enumeration shared by the exact MILP and the QUBO / annealing solvers.

Every route-level quantity of the fleet model depends only on that route's own decision;
routes interact solely through linear fleet-level terms (ships per class, FuelEU pool,
emission cap, objective sums). Enumerating each route's options (class x fuel x OPS x extra
ships x discrete speed level) therefore turns the fleet problem into a multiple-choice
problem with linear side constraints - exactly solvable by MILP and naturally expressed as
a one-hot QUBO.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from greenfleet.optimization.archive import nondominated_mask
from greenfleet.optimization.problem import HFO_MJ_PER_T, FleetProblem, Genes


@dataclass
class RouteOptions:
    route: int
    cat: np.ndarray          # (n, 4) local option indices (class, fuel, ops, extra)
    u: np.ndarray            # (n,) speed position
    cls: np.ndarray          # (n,) global class index
    ships: np.ndarray        # (n,)
    fuel_t: np.ndarray       # HFO-eq t / yr
    wtw: np.ndarray          # t CO2e / yr
    cost: np.ndarray         # USD / yr, excluding the (pooled) FuelEU penalty
    risk: np.ndarray         # 1 - P(on time)
    fe_excess: np.ndarray    # FuelEU: num - target * den   (sum <= 0 means pool compliant), gCO2e
    fe_energy: np.ndarray    # in-scope energy incl. OPS electricity, MJ
    fallback: bool = False   # True when no option satisfies CII + schedule on its own (least-violating kept)

    def __len__(self):
        return len(self.u)

    def take(self, idx) -> RouteOptions:
        return RouteOptions(self.route, *(getattr(self, f)[idx] for f in
                            ("cat", "u", "cls", "ships", "fuel_t", "wtw", "cost", "risk", "fe_excess", "fe_energy")),
                            fallback=self.fallback)


def enumerate_options(problem: FleetProblem, speed_levels: int = 5, prune: bool = True) -> list[RouteOptions]:
    R = problem.R
    levels = np.linspace(0.0, 1.0, speed_levels)
    out = []
    for r in range(R):
        s = problem.cat_sizes[4 * r: 4 * r + 4]
        combos = np.array(list(itertools.product(range(s[0]), range(s[1]), range(s[2]), range(s[3]), range(len(levels)))))
        n = len(combos)
        cat = np.zeros((n, problem.n_cat), dtype=int)
        cat[:, 4 * r: 4 * r + 4] = combos[:, :4]
        u = np.zeros((n, R))
        u[:, r] = levels[combos[:, 4]]
        b = problem._route_block(Genes(cat, u))
        def col(k, b=b, r=r):
            return b[k][:, r]

        scope = problem.eu_scope[r]
        e_in = col("energy") * scope
        ops_in = col("elec") * 3.6 * scope
        fu = col("fuel")
        num = e_in * problem.fe_num[fu]
        den = e_in * problem.fe_den[fu] + ops_in
        cost = col("charter") + col("fuel_cost") + col("elec_cost") + col("ets_cost") + col("levy_cost")
        ok = (col("p_on") >= problem.rs.scenario.on_time_min) & (col("cii_ratio") <= problem.cii_limit[col("cls")])
        opt = RouteOptions(
            route=r, cat=combos[:, :4], u=levels[combos[:, 4]], cls=col("cls"), ships=col("n").astype(int),
            fuel_t=col("energy") / HFO_MJ_PER_T, wtw=col("wtw"), cost=cost, risk=1 - col("p_on"),
            fe_excess=num - problem.fe_target * den, fe_energy=e_in + ops_in,
        ).take(np.nonzero(ok)[0])
        if len(opt) == 0:   # no per-route feasible option: keep the least-violating ones
            viol = np.maximum(problem.rs.scenario.on_time_min - col("p_on"), 0) + np.maximum(
                col("cii_ratio") / problem.cii_limit[col("cls")] - 1, 0)
            opt = RouteOptions(
                route=r, cat=combos[:, :4], u=levels[combos[:, 4]], cls=col("cls"), ships=col("n").astype(int),
                fuel_t=col("energy") / HFO_MJ_PER_T, wtw=col("wtw"), cost=cost, risk=1 - col("p_on"),
                fe_excess=num - problem.fe_target * den, fe_energy=e_in + ops_in,
            ).take(np.argsort(viol)[:5])
            opt.fallback = True
        if prune and len(opt) > 1:
            keep = np.zeros(len(opt), dtype=bool)
            for c in np.unique(opt.cls):
                idx = np.nonzero(opt.cls == c)[0]
                crit = np.column_stack([opt.cost[idx], opt.wtw[idx], opt.fuel_t[idx], opt.ships[idx],
                                        opt.fe_excess[idx], opt.risk[idx]])
                keep[idx[nondominated_mask(crit)]] = True
            opt = opt.take(np.nonzero(keep)[0])
        out.append(opt)
    return out


def options_to_genes(problem: FleetProblem, options: list[RouteOptions], choice: list[int]) -> Genes:
    cat = np.zeros((1, problem.n_cat), dtype=int)
    u = np.zeros((1, problem.R))
    for r, (opt, j) in enumerate(zip(options, choice)):
        cat[0, 4 * r: 4 * r + 4] = opt.cat[j]
        u[0, r] = opt.u[j]
    return Genes(cat, u)


def objective_scales(options: list[RouteOptions]) -> dict[str, float]:
    """Typical fleet totals, used to normalise objectives in weighted sums."""
    return {
        "fuel": float(sum(np.median(o.fuel_t) for o in options)),
        "emissions": float(sum(np.median(o.wtw) for o in options)),
        "cost": float(sum(np.median(o.cost) for o in options)),
        "schedule_risk": float(max(sum(np.median(o.risk) for o in options), 1e-3)),
    }
