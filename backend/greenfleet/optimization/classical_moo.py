"""Classical multi-objective evolutionary baselines from pymoo, on the random-key encoding.

All algorithms evaluate through the shared ``Tracker`` so budgets and front-quality curves
are identical to the quantum-inspired methods. MOEA/D has no native constraint handling in
pymoo, so it optimises normalised objectives plus a constraint-violation penalty (the tracker
still records the true objectives and feasibility).
"""

from __future__ import annotations

import numpy as np
from pymoo.core.callback import Callback
from pymoo.core.problem import Problem
from pymoo.optimize import minimize
from pymoo.util.ref_dirs import get_reference_directions

from greenfleet.optimization.archive import Archive, Tracker
from greenfleet.optimization.problem import FleetProblem
from greenfleet.optimization.qmoea import RunResult


class _PymooProblem(Problem):
    def __init__(self, problem: FleetProblem, tracker: Tracker, penalty_scale: np.ndarray | None = None):
        self.fp, self.tracker, self.penalty_scale = problem, tracker, penalty_scale
        n_constr = 0 if penalty_scale is not None else 1
        super().__init__(n_var=problem.n_keys, n_obj=problem.n_obj, n_ieq_constr=n_constr, xl=0.0, xu=1.0)

    def _evaluate(self, X, out, *args, **kwargs):
        F, CV = self.tracker.evaluate(self.fp.decode_keys(X))
        if self.penalty_scale is not None:
            out["F"] = F / self.penalty_scale + 10.0 * CV[:, None]
        else:
            out["F"] = F
            out["G"] = CV[:, None]


class _Stop(Callback):
    def __init__(self, tracker, cb):
        super().__init__()
        self.tracker, self.cb = tracker, cb
        self.gen = 0

    def notify(self, algorithm):
        if self.cb:
            self.cb({"gen": self.gen, "nfe": self.tracker.nfe}, self.tracker.archive)
        self.gen += 1


def _ref_dirs(n_obj: int, pop: int):
    parts = {2: pop - 1, 3: 8, 4: 5}.get(n_obj, 4)
    return get_reference_directions("das-dennis", n_obj, n_partitions=parts)


def run_pymoo(name: str, problem: FleetProblem, tracker: Tracker, seed: int = 0, pop_size: int = 40,
              callback=None) -> RunResult:
    from pymoo.algorithms.moo.moead import MOEAD
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.algorithms.moo.nsga3 import NSGA3
    from pymoo.algorithms.moo.spea2 import SPEA2

    penalty = None
    if name == "NSGA-II":
        algo = NSGA2(pop_size=pop_size)
    elif name == "NSGA-III":
        rd = _ref_dirs(problem.n_obj, pop_size)
        algo = NSGA3(ref_dirs=rd, pop_size=max(pop_size, len(rd)))
    elif name == "SPEA2":
        algo = SPEA2(pop_size=pop_size)
    elif name == "MOEA/D":
        rd = _ref_dirs(problem.n_obj, pop_size)
        algo = MOEAD(ref_dirs=rd, n_neighbors=min(15, len(rd) - 1), prob_neighbor_mating=0.7)
        base = problem.evaluate(problem.baseline_genes("current_practice"))[0][0]
        penalty = np.maximum(np.abs(base), 1e-9)
    else:
        raise ValueError(name)
    minimize(_PymooProblem(problem, tracker, penalty), algo, ("n_eval", tracker.budget), seed=seed,
             callback=_Stop(tracker, callback), verbose=False)
    arch: Archive = tracker.archive
    return RunResult(name, arch.genes, arch.F, arch.CV, tracker.nfe)


CLASSICAL = ["NSGA-II", "NSGA-III", "SPEA2", "MOEA/D"]
