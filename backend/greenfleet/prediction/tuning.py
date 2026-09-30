"""Hyperparameter tuning: QPSO versus classical tuners at an equal evaluation budget.

Every tuner searches the same unit hypercube that is decoded into model hyperparameters
(log-scaled and integer dimensions handled by ``SearchSpace``), and every tuner receives
exactly ``budget`` objective evaluations, so "best-so-far vs evaluations" curves compare
convergence speed directly.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from greenfleet.classical.single import PSO, RandomSearch, RealGA
from greenfleet.quantum.qpso import QPSO


@dataclass
class Dim:
    name: str
    low: float
    high: float
    log: bool = False
    integer: bool = False

    def decode(self, u: float):
        u = float(np.clip(u, 0.0, 1.0))
        if self.log:
            v = float(np.exp(np.log(self.low) + u * (np.log(self.high) - np.log(self.low))))
        else:
            v = self.low + u * (self.high - self.low)
        return int(round(v)) if self.integer else v


@dataclass
class SearchSpace:
    dims: list[Dim]

    def decode(self, u: np.ndarray) -> dict:
        return {d.name: d.decode(x) for d, x in zip(self.dims, u)}

    @property
    def size(self) -> int:
        return len(self.dims)


LGBM_SPACE = SearchSpace([
    Dim("num_leaves", 8, 128, log=True, integer=True),
    Dim("learning_rate", 0.02, 0.3, log=True),
    Dim("min_child_samples", 5, 100, log=True, integer=True),
    Dim("subsample", 0.5, 1.0),
    Dim("colsample_bytree", 0.5, 1.0),
    Dim("reg_lambda", 1e-3, 10.0, log=True),
])

MPS_SPACE = SearchSpace([
    Dim("bond_dim", 2, 12, integer=True),
    Dim("local_dim_idx", 0, 2, integer=True),   # -> local_dim in (3, 5, 7)
    Dim("ridge", 1e-8, 1e-3, log=True),
])


@dataclass
class TuneResult:
    tuner: str
    best_params: dict
    best_score: float
    history: list[float] = field(default_factory=list)
    seconds: float = 0.0


class _Budgeted:
    """Objective wrapper: decodes, caches identical configs, enforces the budget."""

    def __init__(self, space: SearchSpace, objective: Callable[[dict], float], budget: int):
        self.space, self.objective, self.budget = space, objective, budget
        self.history: list[float] = []
        self.best = (np.inf, None)
        self.cache: dict[tuple, float] = {}

    def __call__(self, u: np.ndarray) -> float:
        params = self.space.decode(u)
        key = tuple(sorted(params.items()))
        if key in self.cache:
            return self.cache[key]
        if len(self.history) >= self.budget:
            return self.best[0] + 1e-9
        score = float(self.objective(params))
        self.cache[key] = score
        if score < self.best[0]:
            self.best = (score, params)
        self.history.append(self.best[0])
        return score


def _tpe(space: SearchSpace, wrapped: _Budgeted, seed: int) -> None:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=seed))

    def obj(trial):
        u = np.array([trial.suggest_float(d.name, 0.0, 1.0) for d in space.dims])
        return wrapped(u)

    while len(wrapped.history) < wrapped.budget:
        study.optimize(obj, n_trials=1)


def _grid(space: SearchSpace, wrapped: _Budgeted) -> None:
    k = max(2, int(np.floor(wrapped.budget ** (1.0 / space.size))))
    levels = np.linspace(0.1, 0.9, k)
    for combo in itertools.product(levels, repeat=space.size):
        if len(wrapped.history) >= wrapped.budget:
            break
        wrapped(np.array(combo))
    # use leftover budget around the grid's best point
    rng = np.random.default_rng(0)
    while len(wrapped.history) < wrapped.budget:
        wrapped(rng.random(space.size))


def tune(tuner: str, space: SearchSpace, objective: Callable[[dict], float], budget: int = 30,
         seed: int = 0, pop_size: int = 6) -> TuneResult:
    t0 = time.perf_counter()
    wrapped = _Budgeted(space, objective, budget)
    lo, hi = np.zeros(space.size), np.ones(space.size)
    max_evals = budget * 4   # population methods may re-propose cached points
    if tuner == "QPSO":
        QPSO(lo, hi, pop_size=pop_size, seed=seed).minimize(wrapped, max_evals=max_evals)
    elif tuner == "PSO":
        PSO(lo, hi, pop_size=pop_size, seed=seed).minimize(wrapped, max_evals=max_evals)
    elif tuner == "GA":
        RealGA(lo, hi, pop_size=pop_size, seed=seed).minimize(wrapped, max_evals=max_evals)
    elif tuner == "Random":
        RandomSearch(lo, hi, seed=seed).minimize(wrapped, max_evals=budget)
    elif tuner == "TPE (Optuna)":
        _tpe(space, wrapped, seed)
    elif tuner == "Grid":
        _grid(space, wrapped)
    else:
        raise ValueError(tuner)
    history = wrapped.history + [wrapped.best[0]] * (budget - len(wrapped.history))
    return TuneResult(tuner=tuner, best_params=wrapped.best[1] or {}, best_score=wrapped.best[0],
                      history=history[:budget], seconds=time.perf_counter() - t0)


TUNERS = ["QPSO", "PSO", "GA", "TPE (Optuna)", "Random", "Grid"]
