"""Quantum-Inspired Evolutionary Algorithm for binary problems (Han & Kim, 2002).

Every individual is a string of Q-bits ``alpha|0> + beta|1>``. Each generation the
Q-bits are *observed* to produce binary solutions, which are evaluated; the Q-bits are
then rotated towards the best solution found so far (the rotation-gate lookup of
Han & Kim: rotate only where the observed bit disagrees with the best bit and the
observed solution is worse). A quantum-NOT mutation and a Hadamard reset on stagnation
maintain diversity. Used here for feature selection.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from greenfleet.quantum.qregister import QuditRegister


@dataclass
class BinaryResult:
    x: np.ndarray
    f: float
    history: list[float] = field(default_factory=list)
    evaluations: int = 0
    entropy: list[float] = field(default_factory=list)


class QIEA:
    def __init__(
        self,
        n_bits: int,
        pop_size: int = 10,
        dtheta_max: float = 0.05 * np.pi,
        dtheta_min: float = 0.01 * np.pi,
        not_rate: float = 0.02,
        stagnation: int = 8,
        seed: int | None = None,
    ):
        self.n_bits = n_bits
        self.pop_size = pop_size
        self.dtheta_max, self.dtheta_min = dtheta_max, dtheta_min
        self.not_rate = not_rate
        self.stagnation = stagnation
        self.rng = np.random.default_rng(seed)

    def minimize(self, f: Callable[[np.ndarray], float], max_evals: int = 200) -> BinaryResult:
        reg = QuditRegister(self.pop_size, [2] * self.n_bits, p_floor=0.02)
        best_x, best_f = None, np.inf
        history: list[float] = []
        entropy: list[float] = []
        cache: dict[bytes, float] = {}
        evals, gen, since_improve = 0, 0, 0
        gens = max(1, max_evals // self.pop_size)
        max_gens = 5 * gens  # cached (repeat) solutions do not consume budget; cap generations
        while evals < max_evals and gen < max_gens:
            xs = reg.measure(self.rng)
            fs = np.full(self.pop_size, np.inf)
            for i, x in enumerate(xs):
                key = x.astype(np.uint8).tobytes()
                if key not in cache:
                    cache[key] = f(x.astype(bool))
                    evals += 1
                fs[i] = cache[key]
                if fs[i] < best_f:
                    best_f, best_x = fs[i], x.copy()
                    since_improve = -1
                history.append(best_f)
                if evals >= max_evals:
                    break
            since_improve += 1
            dtheta = self.dtheta_max - (self.dtheta_max - self.dtheta_min) * min(1.0, gen / max(1, gens - 1))
            # Han & Kim lookup: rotate where the observed bit differs and the individual is worse
            differ = xs != best_x[None, :]
            worse = (fs > best_f)[:, None]
            angle = np.where(differ & worse, dtheta, np.where(differ, 0.3 * dtheta, 0.0))
            reg.rotate(np.broadcast_to(best_x, xs.shape), angle)
            reg.not_gate(self.rng, self.not_rate)
            if since_improve >= self.stagnation:
                worst = np.argsort(fs)[-self.pop_size // 2 :]
                reg.hadamard(worst)
                since_improve = 0
            entropy.append(reg.entropy())
            gen += 1
        return BinaryResult(x=best_x.astype(bool), f=float(best_f), history=history, evaluations=evals, entropy=entropy)
