"""Classical single-objective baselines with the same interface as the quantum-inspired ones.

* ``PSO``   - inertia-weight particle swarm (Shi & Eberhart), velocity clamped
* ``RealGA``- real-coded GA: tournament selection, SBX crossover, polynomial mutation
* ``RandomSearch``
* ``BinaryGA`` - bit-string GA for feature selection (uniform crossover, bit-flip mutation)
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from greenfleet.quantum.qiea import BinaryResult
from greenfleet.quantum.qpso import OptResult


def _batch(f, batch_f):
    return batch_f or (lambda X: np.array([f(x) for x in X]))


class PSO:
    def __init__(self, lower, upper, pop_size: int = 20, w_max: float = 0.9, w_min: float = 0.4,
                 c1: float = 2.0, c2: float = 2.0, seed: int | None = None):
        self.lower, self.upper = np.asarray(lower, float), np.asarray(upper, float)
        self.dim, self.pop_size = len(self.lower), pop_size
        self.w_max, self.w_min, self.c1, self.c2 = w_max, w_min, c1, c2
        self.rng = np.random.default_rng(seed)

    def minimize(self, f: Callable, max_evals: int = 1000, batch_f=None) -> OptResult:
        evaluate = _batch(f, batch_f)
        n, span = self.pop_size, self.upper - self.lower
        x = self.lower + self.rng.random((n, self.dim)) * span
        v = self.rng.uniform(-0.1, 0.1, (n, self.dim)) * span
        fx = evaluate(x)
        history = list(np.minimum.accumulate(fx))
        pbest, pbest_f = x.copy(), fx.copy()
        g = int(np.argmin(pbest_f))
        evals = n
        iters = max(1, (max_evals - n) // n)
        for it in range(iters):
            w = self.w_max - (self.w_max - self.w_min) * it / max(1, iters - 1)
            r1, r2 = self.rng.random((n, self.dim)), self.rng.random((n, self.dim))
            v = w * v + self.c1 * r1 * (pbest - x) + self.c2 * r2 * (pbest[g] - x)
            v = np.clip(v, -0.2 * span, 0.2 * span)
            x = np.clip(x + v, self.lower, self.upper)
            fx = evaluate(x)
            evals += n
            better = fx < pbest_f
            pbest[better], pbest_f[better] = x[better], fx[better]
            g = int(np.argmin(pbest_f))
            for val in fx:
                history.append(min(history[-1], val))
        return OptResult(x=pbest[g].copy(), f=float(pbest_f[g]), history=history, evaluations=evals)


def sbx(rng, p1, p2, lower, upper, eta: float = 15.0, prob: float = 0.9):
    c1, c2 = p1.copy(), p2.copy()
    if rng.random() > prob:
        return c1, c2
    u = rng.random(p1.shape)
    beta = np.where(u <= 0.5, (2 * u) ** (1 / (eta + 1)), (1 / (2 * (1 - u))) ** (1 / (eta + 1)))
    c1 = 0.5 * ((1 + beta) * p1 + (1 - beta) * p2)
    c2 = 0.5 * ((1 - beta) * p1 + (1 + beta) * p2)
    return np.clip(c1, lower, upper), np.clip(c2, lower, upper)


def poly_mutation(rng, x, lower, upper, eta: float = 20.0, prob: float | None = None):
    prob = prob if prob is not None else 1.0 / len(x)
    y = x.copy()
    mask = rng.random(len(x)) < prob
    if not mask.any():
        return y
    span = upper - lower
    u = rng.random(len(x))
    delta = np.where(u < 0.5, (2 * u) ** (1 / (eta + 1)) - 1, 1 - (2 * (1 - u)) ** (1 / (eta + 1)))
    y[mask] = y[mask] + delta[mask] * span[mask]
    return np.clip(y, lower, upper)


class RealGA:
    def __init__(self, lower, upper, pop_size: int = 20, seed: int | None = None):
        self.lower, self.upper = np.asarray(lower, float), np.asarray(upper, float)
        self.dim, self.pop_size = len(self.lower), pop_size
        self.rng = np.random.default_rng(seed)

    def minimize(self, f: Callable, max_evals: int = 1000, batch_f=None) -> OptResult:
        evaluate = _batch(f, batch_f)
        n = self.pop_size
        x = self.lower + self.rng.random((n, self.dim)) * (self.upper - self.lower)
        fx = evaluate(x)
        history = list(np.minimum.accumulate(fx))
        evals = n
        while evals + n <= max_evals:
            children = []
            while len(children) < n:
                a, b = self.rng.integers(0, n, 2), self.rng.integers(0, n, 2)
                p1 = x[a[np.argmin(fx[a])]]
                p2 = x[b[np.argmin(fx[b])]]
                c1, c2 = sbx(self.rng, p1, p2, self.lower, self.upper)
                children += [poly_mutation(self.rng, c1, self.lower, self.upper),
                             poly_mutation(self.rng, c2, self.lower, self.upper)]
            kids = np.array(children[:n])
            fk = evaluate(kids)
            evals += n
            for val in fk:
                history.append(min(history[-1], val))
            allx, allf = np.vstack([x, kids]), np.concatenate([fx, fk])
            keep = np.argsort(allf)[:n]            # (mu + lambda) elitist survival
            x, fx = allx[keep], allf[keep]
        return OptResult(x=x[0].copy(), f=float(fx[0]), history=history, evaluations=evals)


class RandomSearch:
    def __init__(self, lower, upper, seed: int | None = None, **_):
        self.lower, self.upper = np.asarray(lower, float), np.asarray(upper, float)
        self.rng = np.random.default_rng(seed)

    def minimize(self, f: Callable, max_evals: int = 1000, batch_f=None) -> OptResult:
        evaluate = _batch(f, batch_f)
        x = self.lower + self.rng.random((max_evals, len(self.lower))) * (self.upper - self.lower)
        fx = evaluate(x)
        i = int(np.argmin(fx))
        return OptResult(x=x[i], f=float(fx[i]), history=list(np.minimum.accumulate(fx)), evaluations=max_evals)


class BinaryGA:
    def __init__(self, n_bits: int, pop_size: int = 10, mutation: float | None = None, seed: int | None = None):
        self.n_bits, self.pop_size = n_bits, pop_size
        self.mutation = mutation if mutation is not None else 1.0 / n_bits
        self.rng = np.random.default_rng(seed)

    def minimize(self, f: Callable[[np.ndarray], float], max_evals: int = 200) -> BinaryResult:
        cache: dict[bytes, float] = {}
        evals = 0
        history: list[float] = []
        best_x, best_f = None, np.inf

        def ev(x):
            nonlocal evals, best_x, best_f
            key = x.astype(np.uint8).tobytes()
            if key not in cache:
                cache[key] = f(x.astype(bool))
                evals += 1
            val = cache[key]
            if val < best_f:
                best_f, best_x = val, x.copy()
            history.append(best_f)
            return val

        pop = self.rng.random((self.pop_size, self.n_bits)) < 0.5
        fit = np.array([ev(x) for x in pop])
        gen, max_gens = 0, 5 * max(1, max_evals // self.pop_size)
        while evals < max_evals and gen < max_gens:
            gen += 1
            kids = []
            for _ in range(self.pop_size):
                a, b = self.rng.integers(0, self.pop_size, 2), self.rng.integers(0, self.pop_size, 2)
                p1, p2 = pop[a[np.argmin(fit[a])]], pop[b[np.argmin(fit[b])]]
                mask = self.rng.random(self.n_bits) < 0.5
                child = np.where(mask, p1, p2)
                flip = self.rng.random(self.n_bits) < self.mutation
                kids.append(child ^ flip)
            kids = np.array(kids)
            fk = np.array([ev(x) for x in kids])
            allx, allf = np.vstack([pop, kids]), np.concatenate([fit, fk])
            keep = np.argsort(allf)[: self.pop_size]
            pop, fit = allx[keep], allf[keep]
        return BinaryResult(x=best_x.astype(bool), f=float(best_f), history=history, evaluations=evals)
