"""Quantum-inspired probabilistic registers (Q-bits and qudits).

A population of quantum individuals is stored as real, non-negative amplitude vectors
``psi[p, v, :]`` over the options of each decision variable ``v`` (``K_v`` options, padded
to ``K_max``). ``|psi|^2`` is the measurement distribution. Three gates act on it:

* **measurement** collapses every register to a classical option;
* the **rotation gate** turns the state vector towards the basis state of a guide
  solution by an angle ``dtheta``. For ``K = 2`` this is exactly the classic Q-bit
  rotation gate of Han & Kim's QEA; for ``K > 2`` it rotates in the plane spanned by the
  guide's basis state and the orthogonal remainder of the state (a Givens rotation), so
  all non-guide amplitudes shrink proportionally;
* the **quantum NOT (X) gate** swaps two amplitudes (for ``K = 2`` it swaps alpha and beta),
  and the **Hadamard reset** restores the uniform superposition.

A probability floor keeps every option reachable, which prevents the premature
collapse that plain QEA implementations suffer from.
"""

from __future__ import annotations

import numpy as np


class QuditRegister:
    def __init__(self, pop_size: int, sizes: list[int] | np.ndarray, p_floor: float = 0.01):
        self.sizes = np.asarray(sizes, dtype=int)
        if np.any(self.sizes < 1):
            raise ValueError("every variable needs at least one option")
        self.pop_size = int(pop_size)
        self.n_vars = len(self.sizes)
        self.k_max = int(self.sizes.max())
        self.mask = np.arange(self.k_max)[None, :] < self.sizes[:, None]        # (V, K)
        self.p_floor = float(p_floor)
        self.psi = np.zeros((self.pop_size, self.n_vars, self.k_max))
        self.hadamard(np.arange(self.pop_size))

    # ------------------------------------------------------------------ state
    def probabilities(self) -> np.ndarray:
        return self.psi**2

    def hadamard(self, individuals: np.ndarray | list[int]) -> None:
        """Reset the given individuals to the uniform superposition |+>."""
        amp = np.where(self.mask, 1.0 / np.sqrt(self.sizes[:, None]), 0.0)
        self.psi[np.asarray(individuals, dtype=int)] = amp[None, :, :]

    def entropy(self) -> float:
        """Mean normalised Shannon entropy of the measurement distributions (1 = uniform)."""
        p = np.clip(self.probabilities(), 1e-12, 1.0)
        h = -(p * np.log(p) * self.mask[None]).sum(axis=2)
        denom = np.log(np.maximum(self.sizes, 2))[None, :]
        multi = self.sizes > 1
        if not multi.any():
            return 0.0
        return float((h / denom)[:, multi].mean())

    # ------------------------------------------------------------------ gates
    def measure(self, rng: np.random.Generator) -> np.ndarray:
        """Collapse every register; returns option indices of shape (pop, n_vars)."""
        p = self.probabilities()
        cdf = np.cumsum(p, axis=2)
        cdf /= cdf[:, :, -1:]
        u = rng.random((self.pop_size, self.n_vars, 1))
        idx = (u > cdf).sum(axis=2)
        return np.minimum(idx, self.sizes[None, :] - 1)

    def sample(self, rng: np.random.Generator, n: int, individual: int = 0) -> np.ndarray:
        """Measure ``n`` independent copies of one individual's state; shape (n, n_vars)."""
        cdf = np.cumsum(self.probabilities()[individual], axis=1)
        cdf /= cdf[:, -1:]
        u = rng.random((n, self.n_vars, 1))
        idx = (u > cdf[None, :, :]).sum(axis=2)
        return np.minimum(idx, self.sizes[None, :] - 1)

    def rotate(self, targets: np.ndarray, dtheta: float | np.ndarray, individuals: np.ndarray | None = None) -> None:
        """Rotate registers of ``individuals`` towards the basis states ``targets`` (same shape)."""
        ind = np.arange(self.pop_size) if individuals is None else np.asarray(individuals, dtype=int)
        targets = np.asarray(targets, dtype=int).reshape(len(ind), self.n_vars)
        psi = self.psi[ind]                                               # (P, V, K)
        onehot = np.zeros_like(psi)
        np.put_along_axis(onehot, targets[:, :, None], 1.0, axis=2)
        a = (psi * onehot).sum(axis=2, keepdims=True)                     # guide amplitude
        perp = psi - a * onehot
        b = np.linalg.norm(perp, axis=2, keepdims=True)
        theta = np.arctan2(b, a)                                          # angle away from guide
        dtheta = np.broadcast_to(np.asarray(dtheta, dtype=float), theta.shape[:2])[..., None]
        new_theta = np.clip(theta - dtheta, 0.0, np.pi / 2)
        unit_perp = np.divide(perp, b, out=np.zeros_like(perp), where=b > 1e-12)
        new = np.cos(new_theta) * onehot + np.sin(new_theta) * unit_perp
        self.psi[ind] = self._apply_floor(new)

    def not_gate(self, rng: np.random.Generator, rate: float) -> None:
        """Generalised quantum-NOT: swap the dominant amplitude with a random other option."""
        hits = (rng.random((self.pop_size, self.n_vars)) < rate) & (self.sizes[None, :] > 1)
        if not hits.any():
            return
        pi, vi = np.nonzero(hits)
        dominant = self.psi[pi, vi].argmax(axis=1)
        other = (dominant + rng.integers(1, self.sizes[vi])) % self.sizes[vi]
        a = self.psi[pi, vi, dominant].copy()
        self.psi[pi, vi, dominant] = self.psi[pi, vi, other]
        self.psi[pi, vi, other] = a

    def _apply_floor(self, psi: np.ndarray) -> np.ndarray:
        p = psi**2 * self.mask[None]
        p /= p.sum(axis=2, keepdims=True)
        k = self.sizes[None, :, None].astype(float)
        floor = np.minimum(self.p_floor, 0.5 / k)
        p = (1.0 - k * floor) * p + floor
        return np.sqrt(p * self.mask[None])
