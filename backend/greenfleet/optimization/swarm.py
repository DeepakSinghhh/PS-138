"""Swarm baselines on the random-key encoding.

* ``MOQPSO`` - multi-objective quantum-behaved PSO (ablation: QPSO for *all* genes, no qudit
  registers), leaders from a crowding-sorted archive.
* ``MOPSO``  - classical velocity-based multi-objective PSO (Coello et al. 2004) with
  archive leaders and turbulence (mutation).
* ``RandomSearch`` - uniform sampling in key space (sanity floor).
"""

from __future__ import annotations

import numpy as np

from greenfleet.optimization.archive import Archive, Tracker
from greenfleet.optimization.problem import FleetProblem
from greenfleet.optimization.qmoea import RunResult, _dominates


class _KeySwarm:
    name = "swarm"

    def __init__(self, problem: FleetProblem, pop_size: int = 40, archive_size: int = 100, seed: int = 0):
        self.problem, self.pop_size, self.archive_size = problem, pop_size, archive_size
        self.rng = np.random.default_rng(seed)

    def _eval(self, tracker, X):
        g = self.problem.decode_keys(X)
        F, CV = tracker.evaluate(g)
        return g, F, CV


class MOQPSO(_KeySwarm):
    name = "MOQPSO (quantum-inspired, ablation)"

    def run(self, tracker: Tracker, callback=None) -> RunResult:
        P, D, rng = self.pop_size, self.problem.n_keys, self.rng
        X = rng.random((P, D))
        archive = Archive(self.archive_size)
        pbX = pbF = pbCV = None
        gens = max(1, tracker.budget // P)
        gen = 0
        while not tracker.exhausted:
            g, F, CV = self._eval(tracker, X)
            archive.update(g, F, CV)
            if pbX is None:
                pbX, pbF, pbCV = X.copy(), F.copy(), CV.copy()
            else:
                upd = _dominates(F, CV, pbF, pbCV) | (~_dominates(pbF, pbCV, F, CV) & (rng.random(P) < 0.5))
                pbX[upd], pbF[upd], pbCV[upd] = X[upd], F[upd], CV[upd]
            beta = 1.0 - 0.5 * min(1.0, gen / max(1, gens - 1))
            leadX = self.problem.encode_keys(archive.genes.take(archive.leaders(P, rng)))
            phi = rng.random((P, D))
            att = phi * pbX + (1 - phi) * leadX
            mbest = pbX.mean(axis=0, keepdims=True)
            sign = np.where(rng.random((P, D)) < 0.5, -1.0, 1.0)
            X = att + sign * beta * np.abs(mbest - X) * np.log(1.0 / np.maximum(rng.random((P, D)), 1e-12))
            X = np.clip(np.where(X < 0, -X, np.where(X > 1, 2 - X, X)), 0.0, 1.0)
            if callback:
                callback({"gen": gen, "nfe": tracker.nfe}, archive)
            gen += 1
        return RunResult(self.name, archive.genes, archive.F, archive.CV, tracker.nfe)


class MOPSO(_KeySwarm):
    name = "MOPSO (classical)"

    def run(self, tracker: Tracker, callback=None) -> RunResult:
        P, D, rng = self.pop_size, self.problem.n_keys, self.rng
        X = rng.random((P, D))
        V = np.zeros((P, D))
        archive = Archive(self.archive_size)
        pbX = pbF = pbCV = None
        gens = max(1, tracker.budget // P)
        gen = 0
        while not tracker.exhausted:
            g, F, CV = self._eval(tracker, X)
            archive.update(g, F, CV)
            if pbX is None:
                pbX, pbF, pbCV = X.copy(), F.copy(), CV.copy()
            else:
                upd = _dominates(F, CV, pbF, pbCV) | (~_dominates(pbF, pbCV, F, CV) & (rng.random(P) < 0.5))
                pbX[upd], pbF[upd], pbCV[upd] = X[upd], F[upd], CV[upd]
            leadX = self.problem.encode_keys(archive.genes.take(archive.leaders(P, rng)))
            V = 0.4 * V + 1.5 * rng.random((P, D)) * (pbX - X) + 1.5 * rng.random((P, D)) * (leadX - X)
            V = np.clip(V, -0.25, 0.25)
            X = np.clip(X + V, 0.0, 1.0)
            # turbulence: mutation rate decays over the run
            rate = 0.5 * (1 - min(1.0, gen / max(1, gens - 1))) ** 1.5
            mut = rng.random((P, D)) < rate / D * 5
            X[mut] = rng.random(mut.sum())
            if callback:
                callback({"gen": gen, "nfe": tracker.nfe}, archive)
            gen += 1
        return RunResult(self.name, archive.genes, archive.F, archive.CV, tracker.nfe)


class RandomSearchMO(_KeySwarm):
    name = "Random search"

    def run(self, tracker: Tracker, callback=None) -> RunResult:
        archive = Archive(self.archive_size)
        while not tracker.exhausted:
            g, F, CV = self._eval(tracker, self.rng.random((self.pop_size, self.problem.n_keys)))
            archive.update(g, F, CV)
        return RunResult(self.name, archive.genes, archive.F, archive.CV, tracker.nfe)
