"""Exact reference: multiple-choice MILP over enumerated route options (PuLP + CBC).

With speeds discretised to the same levels, the optimum of this MILP is the true optimum of
the fleet problem, so it provides optimality gaps for the metaheuristics. The FuelEU pool is
exact in "hard" mode (linear compliance constraint); in "penalty" mode the pooled penalty is
linearised with the target intensity in the denominator (reported solutions are re-evaluated
exactly with the fleet model).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pulp

from greenfleet.optimization.options import RouteOptions, objective_scales, options_to_genes
from greenfleet.optimization.problem import FleetProblem, Genes


@dataclass
class MILPResult:
    genes: Genes | None
    objective: float
    status: str
    seconds: float


class FleetMILP:
    def __init__(self, problem: FleetProblem, options: list[RouteOptions], time_limit: int = 120):
        self.problem, self.options, self.time_limit = problem, options, time_limit
        self.scales = objective_scales(options)

    def _model(self, name: str):
        prob, opts = self.problem, self.options
        m = pulp.LpProblem(name, pulp.LpMinimize)
        x = [[pulp.LpVariable(f"x_{r}_{j}", cat="Binary") for j in range(len(o))] for r, o in enumerate(opts)]
        for xr in x:
            m += pulp.lpSum(xr) == 1
        for c in range(len(prob.class_ids)):
            terms = [int(o.ships[j]) * x[r][j] for r, o in enumerate(opts) for j in range(len(o)) if o.cls[j] == c]
            if terms:
                m += pulp.lpSum(terms) <= int(prob.available[c])
        excess = pulp.lpSum(float(o.fe_excess[j]) * x[r][j] for r, o in enumerate(opts) for j in range(len(o)))
        pen = pulp.LpVariable("fueleu_penalty", lowBound=0)
        sc = prob.rs.scenario
        if sc.fueleu_mode == "hard":
            m += excess <= 0
        else:
            rate = prob.fe_rate * prob.rs.eur_to_usd / max(prob.fe_target, 1e-9)   # USD per gCO2e of pooled deficit
            m += pen >= rate * excess
        exprs = {
            "fuel": pulp.lpSum(float(o.fuel_t[j]) * x[r][j] for r, o in enumerate(opts) for j in range(len(o))),
            "emissions": pulp.lpSum(float(o.wtw[j]) * x[r][j] for r, o in enumerate(opts) for j in range(len(o))),
            "cost": pulp.lpSum(float(o.cost[j]) * x[r][j] for r, o in enumerate(opts) for j in range(len(o))) + pen,
        }
        if sc.fleet_emission_cap_t:
            m += exprs["emissions"] <= sc.fleet_emission_cap_t
        return m, x, exprs

    def _solve(self, m, x) -> MILPResult:
        t0 = time.perf_counter()
        m.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=self.time_limit))
        secs = time.perf_counter() - t0
        status = pulp.LpStatus[m.status]
        if status not in ("Optimal", "Not Solved") or any(v.varValue is None for v in x[0]):
            return MILPResult(None, float("nan"), status, secs)
        choice = [int(np.argmax([v.varValue or 0 for v in xr])) for xr in x]
        return MILPResult(options_to_genes(self.problem, self.options, choice), float(pulp.value(m.objective)),
                          status, secs)

    def minimize(self, objective: str, bounds: dict[str, float] | None = None) -> MILPResult:
        m, x, exprs = self._model(f"min_{objective}")
        m += exprs[objective]
        for k, v in (bounds or {}).items():
            m += exprs[k] <= v
        return self._solve(m, x)

    def weighted(self, weights: dict[str, float]) -> MILPResult:
        m, x, exprs = self._model("weighted")
        m += pulp.lpSum(w / self.scales[k] * exprs[k] for k, w in weights.items() if w)
        return self._solve(m, x)

    def epsilon_front(self, objective: str = "cost", constrained: str = "emissions", n_points: int = 12) -> list[MILPResult]:
        """Exact bi-objective front: min `objective` s.t. `constrained` <= eps over an eps grid."""
        lo = self.minimize(constrained)
        hi = self.minimize(objective)
        if lo.genes is None or hi.genes is None:
            return [r for r in (lo, hi) if r.genes is not None]
        # evaluate the extremes with the exact fleet model to get the eps range
        unit = 1e6 if constrained == "cost" else 1.0      # fleet model reports cost in M USD
        Flo = self.problem.evaluate(lo.genes, return_parts=True)[2]["objectives_all"][constrained][0] * unit
        Fhi = self.problem.evaluate(hi.genes, return_parts=True)[2]["objectives_all"][constrained][0] * unit
        front = [lo]
        for eps in np.linspace(Flo, Fhi, n_points)[1:-1]:
            res = self.minimize(objective, {constrained: float(eps)})
            if res.genes is not None:
                front.append(res)
        front.append(hi)
        return front
