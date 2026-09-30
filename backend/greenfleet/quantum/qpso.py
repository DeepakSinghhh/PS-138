"""Quantum-behaved Particle Swarm Optimization (QPSO; Sun, Feng & Xu, 2004).

Each particle moves in a delta potential well centred on a local attractor
``p = phi * pbest + (1 - phi) * gbest``. Its position is sampled from the collapsed
wave function

    x = p +/- beta * |mbest - x| * ln(1 / u),     u ~ U(0, 1)

where ``mbest`` is the mean of all personal bests and ``beta`` (contraction-expansion
coefficient) is annealed from ``beta_max`` to ``beta_min``. The heavy-tailed ``ln(1/u)``
term plays the role of quantum tunnelling: occasional long jumps out of local optima.
There is no velocity and only one control parameter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np


@dataclass
class OptResult:
    x: np.ndarray
    f: float
    history: list[float] = field(default_factory=list)   # best-so-far after every evaluation
    evaluations: int = 0


class QPSO:
    def __init__(
        self,
        lower: np.ndarray,
        upper: np.ndarray,
        pop_size: int = 20,
        beta_max: float = 1.0,
        beta_min: float = 0.5,
        seed: int | None = None,
    ):
        self.lower = np.asarray(lower, dtype=float)
        self.upper = np.asarray(upper, dtype=float)
        self.dim = len(self.lower)
        self.pop_size = pop_size
        self.beta_max, self.beta_min = beta_max, beta_min
        self.rng = np.random.default_rng(seed)

    def step(self, x: np.ndarray, pbest: np.ndarray, gbest: np.ndarray, beta: float) -> np.ndarray:
        n, d = x.shape
        mbest = pbest.mean(axis=0)
        phi = self.rng.random((n, d))
        attractor = phi * pbest + (1 - phi) * gbest[None, :]
        u = self.rng.random((n, d))
        sign = np.where(self.rng.random((n, d)) < 0.5, -1.0, 1.0)
        new = attractor + sign * beta * np.abs(mbest[None, :] - x) * np.log(1.0 / np.maximum(u, 1e-300))
        # reflect back into the box, then clip
        span = self.upper - self.lower
        new = np.where(new < self.lower, self.lower + np.mod(self.lower - new, span), new)
        new = np.where(new > self.upper, self.upper - np.mod(new - self.upper, span), new)
        return np.clip(new, self.lower, self.upper)

    def minimize(
        self,
        f: Callable[[np.ndarray], float],
        max_evals: int = 1000,
        callback: Callable[[int, float], None] | None = None,
        batch_f: Callable[[np.ndarray], np.ndarray] | None = None,
    ) -> OptResult:
        n = self.pop_size
        x = self.lower + self.rng.random((n, self.dim)) * (self.upper - self.lower)
        evaluate = batch_f or (lambda X: np.array([f(xi) for xi in X]))
        fx = evaluate(x)
        evals = n
        history = list(np.minimum.accumulate(fx))
        pbest, pbest_f = x.copy(), fx.copy()
        g = int(np.argmin(pbest_f))
        iters = max(1, (max_evals - n) // n)
        for it in range(iters):
            beta = self.beta_max - (self.beta_max - self.beta_min) * it / max(1, iters - 1)
            x = self.step(x, pbest, pbest[g], beta)
            fx = evaluate(x)
            evals += n
            better = fx < pbest_f
            pbest[better], pbest_f[better] = x[better], fx[better]
            g = int(np.argmin(pbest_f))
            best = pbest_f[g]
            for v in fx:
                history.append(min(history[-1], v))
            if callback:
                callback(evals, float(best))
        return OptResult(x=pbest[g].copy(), f=float(pbest_f[g]), history=history, evaluations=evals)
