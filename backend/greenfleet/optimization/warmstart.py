"""Exact warm start: seed the metaheuristic with MILP-optimal plans.

On large networks a random initial population almost never satisfies every constraint at once
(demand, weekly schedule, CII per route and fleet availability across routes), so a search can
spend its whole budget looking for the feasible region. The multiple-choice MILP over
discretised speeds (``milp.py``) solves even 200-route networks in seconds, and its plans are
feasible by construction. Seeding the population with a few of them (the single-objective
extremes plus balanced trade-offs) starts the quantum-inspired search inside the feasible
region; it then refines continuous speeds and fills in the trade-off front between the seeds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from greenfleet.optimization.milp import FleetMILP
from greenfleet.optimization.options import enumerate_options
from greenfleet.optimization.problem import FleetProblem, Genes

#: weight vectors on normalised objectives: the three extremes and two balanced compromises
SEED_WEIGHTS: list[dict[str, float]] = [
    {"cost": 1.0}, {"emissions": 1.0}, {"fuel": 1.0},
    {"cost": 1.0, "emissions": 1.0, "fuel": 1.0}, {"cost": 2.0, "emissions": 1.0},
]


@dataclass
class WarmStart:
    genes: Genes | None
    seconds: float
    statuses: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return 0 if self.genes is None else len(self.genes.u)


def exact_seeds(problem: FleetProblem, speed_levels: int = 5, time_limit: int = 60,
                weights: list[dict[str, float]] | None = None) -> WarmStart:
    """MILP-optimal plans for each weight vector (duplicates removed); ``genes`` is None if none solved."""
    t0 = time.perf_counter()
    milp = FleetMILP(problem, enumerate_options(problem, speed_levels), time_limit=time_limit)
    plans, seen, statuses = [], set(), []
    for w in weights or SEED_WEIGHTS:
        w = {k: v for k, v in w.items() if k in problem.objectives}
        if not w:
            continue
        res = milp.minimize(next(iter(w))) if len(w) == 1 else milp.weighted(w)
        statuses.append(res.status)
        if res.genes is None or tuple(res.choice) in seen:
            continue
        seen.add(tuple(res.choice))
        plans.append(res.genes)
    return WarmStart(Genes.concat(plans) if plans else None, time.perf_counter() - t0, statuses)
