"""Pareto machinery: constrained dominance, crowding, bounded archive, evaluation tracker."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from greenfleet.optimization.problem import FleetProblem, Genes


def dominance_matrix(F: np.ndarray, CV: np.ndarray) -> np.ndarray:
    """D[i, j] = True if i constrained-dominates j (Deb's feasibility rules)."""
    feas = CV <= 1e-12
    le = np.all(F[:, None, :] <= F[None, :, :], axis=2)
    lt = np.any(F[:, None, :] < F[None, :, :], axis=2)
    pareto = le & lt
    both_feas = feas[:, None] & feas[None, :]
    both_inf = ~feas[:, None] & ~feas[None, :]
    return (both_feas & pareto) | (feas[:, None] & ~feas[None, :]) | (both_inf & (CV[:, None] < CV[None, :]))


def nondominated_sort(F: np.ndarray, CV: np.ndarray | None = None) -> list[np.ndarray]:
    CV = np.zeros(len(F)) if CV is None else CV
    D = dominance_matrix(F, CV)
    n_dom = D.sum(axis=0)
    fronts = []
    remaining = np.ones(len(F), dtype=bool)
    while remaining.any():
        front = np.nonzero(remaining & (n_dom == 0))[0]
        if len(front) == 0:  # numerical ties among infeasible solutions
            front = np.nonzero(remaining)[0]
        fronts.append(front)
        remaining[front] = False
        n_dom = n_dom - D[front].sum(axis=0)
        n_dom[~remaining] = -1
    return fronts


def nondominated_mask(F: np.ndarray) -> np.ndarray:
    n = len(F)
    if n == 0:
        return np.zeros(0, dtype=bool)
    if n <= 1500:
        le = np.all(F[:, None, :] <= F[None, :, :], axis=2)
        lt = np.any(F[:, None, :] < F[None, :, :], axis=2)
        return ~np.any(le & lt, axis=0)
    # large sets: a point can only be dominated by points with a strictly smaller objective sum,
    # so scanning in order of increasing sum never has to remove an accepted point
    mask = np.zeros(n, dtype=bool)
    front = np.empty((0, F.shape[1]))
    for i in np.argsort(F.sum(axis=1), kind="stable"):
        f = F[i]
        if len(front) and np.any(np.all(front <= f, axis=1) & np.any(front < f, axis=1)):
            continue
        mask[i] = True
        front = np.vstack([front, f])
    return mask


def crowding_distance(F: np.ndarray) -> np.ndarray:
    n, m = F.shape
    if n <= 2:
        return np.full(n, np.inf)
    d = np.zeros(n)
    for j in range(m):
        order = np.argsort(F[:, j])
        span = F[order[-1], j] - F[order[0], j]
        d[order[0]] = d[order[-1]] = np.inf
        if span > 0:
            d[order[1:-1]] += (F[order[2:], j] - F[order[:-2], j]) / span
    return d


def truncate_by_crowding(F: np.ndarray, size: int) -> np.ndarray:
    """Indices to keep: iteratively drop the most crowded point."""
    keep = np.arange(len(F))
    while len(keep) > size:
        cd = crowding_distance(F[keep])
        keep = np.delete(keep, int(np.argmin(cd)))
    return keep


@dataclass
class Archive:
    """Bounded external archive of constrained-nondominated solutions."""

    max_size: int = 100
    genes: Genes | None = None
    F: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    CV: np.ndarray = field(default_factory=lambda: np.zeros(0))
    extra: np.ndarray | None = None     # optional per-member data kept aligned (e.g. per-route violations)

    def update(self, g: Genes, F: np.ndarray, CV: np.ndarray, extra: np.ndarray | None = None) -> bool:
        if self.genes is None:
            allg, allF, allCV, allX = g, F, CV, extra
            before = None
        else:
            allg, allF, allCV = Genes.concat([self.genes, g]), np.vstack([self.F, F]), np.concatenate([self.CV, CV])
            allX = np.vstack([self.extra, extra]) if (extra is not None and self.extra is not None) else None
            before = self.F.copy()
        feas = allCV <= 1e-12
        if feas.any():
            idx = np.nonzero(feas)[0]
            idx = idx[nondominated_mask(allF[idx])]
        else:
            idx = np.argsort(allCV)[: min(10, len(allCV))]
        # drop exact duplicates in objective space
        _, uniq = np.unique(np.round(allF[idx], 9), axis=0, return_index=True)
        idx = idx[np.sort(uniq)]
        if len(idx) > self.max_size:
            idx = idx[truncate_by_crowding(allF[idx], self.max_size)]
        self.genes, self.F, self.CV = allg.take(idx), allF[idx], allCV[idx]
        self.extra = allX[idx] if allX is not None else None
        return before is None or before.shape != self.F.shape or not np.allclose(before, self.F)

    def leaders(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """Binary tournament on crowding distance (sparse regions of the front win)."""
        k = len(self.F)
        if k == 1:
            return np.zeros(n, dtype=int)
        cd = crowding_distance(self.F) if self.feasible else -self.CV
        a, b = rng.integers(0, k, n), rng.integers(0, k, n)
        return np.where(cd[a] >= cd[b], a, b)

    @property
    def feasible(self) -> bool:
        return len(self.CV) > 0 and bool(np.all(self.CV <= 1e-12))


class Tracker:
    """Wraps a problem: counts evaluations and keeps the best-known front for fair metrics.

    Every algorithm evaluates through a tracker, so convergence curves (front quality vs
    number of evaluations) are measured identically for all methods.
    """

    def __init__(self, problem: FleetProblem, budget: int, n_snapshots: int = 20, archive_size: int = 200,
                 on_snapshot=None):
        self.problem, self.budget = problem, budget
        self.archive = Archive(max_size=archive_size)
        self.nfe = 0
        self.checkpoints = sorted({int(budget * (i + 1) / n_snapshots) for i in range(n_snapshots)})
        self.snapshots: list[dict] = []
        self.t0 = time.perf_counter()
        self.on_snapshot = on_snapshot
        self.best_cv = np.inf

    @property
    def exhausted(self) -> bool:
        return self.nfe >= self.budget

    def evaluate(self, g: Genes, route_cv: bool = False, route_f: bool = False):
        """Evaluate (counted against the budget); optionally also return per-route violations and per-route
        objective contributions (P x R x n_obj)."""
        if route_cv or route_f:
            F, CV, parts = self.problem.evaluate(g, return_parts=True)
            rcv, rf = parts["route_cv"], parts["route_f"]
        else:
            F, CV = self.problem.evaluate(g)
        start = self.nfe
        self.nfe += len(g)
        self.best_cv = min(self.best_cv, float(CV.min()))
        self.archive.update(g, F, CV)
        for cp in self.checkpoints:
            if start < cp <= self.nfe:
                snap = {"nfe": cp, "seconds": time.perf_counter() - self.t0,
                        "F": self.archive.F.copy(), "feasible": self.archive.feasible, "best_cv": self.best_cv}
                self.snapshots.append(snap)
                if self.on_snapshot:
                    self.on_snapshot(snap)
        if route_f:
            return F, CV, rcv, rf
        return (F, CV, rcv) if route_cv else (F, CV)
