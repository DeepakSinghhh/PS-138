"""QUBO / Ising utilities and (simulated) quantum annealing solvers.

* ``qubo_to_ising`` converts ``min x^T Q x`` (x in {0,1}) to ``h, J`` (s in {-1,+1}).
* ``PathIntegralSQA`` is a from-scratch path-integral Monte Carlo simulation of a
  transverse-field quantum annealer: M Trotter replicas of the spin system are coupled
  by ``J_perp = -(T/2) ln tanh(Gamma / (M T))`` and the transverse field ``Gamma`` is
  lowered from strong (quantum fluctuations dominate) to ~0 (classical ground state).
* ``solve_openjij_sqa`` / ``solve_openjij_sa`` wrap OpenJij's C++ samplers for speed.
* ``to_bqm`` exports to a ``dimod.BinaryQuadraticModel``: the same model can be sent,
  unchanged, to a D-Wave quantum annealer (``DWaveSampler``) when hardware is available.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np


@dataclass
class AnnealResult:
    x: np.ndarray            # best binary vector
    energy: float
    energies: np.ndarray     # energy of every read
    seconds: float
    solver: str


def qubo_energy(Q: np.ndarray, x: np.ndarray, offset: float = 0.0) -> np.ndarray:
    x = np.atleast_2d(x).astype(float)
    return np.einsum("ri,ij,rj->r", x, Q, x) + offset


def symmetric(Q: np.ndarray) -> np.ndarray:
    return 0.5 * (Q + Q.T)


def qubo_to_ising(Q: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """x = (1 + s) / 2  ->  E = s^T J s + h^T s + c  with J symmetric, zero diagonal."""
    Q = symmetric(Q)
    diag = np.diag(Q).copy()
    off = Q - np.diag(diag)
    J = off / 4.0
    h = diag / 2.0 + off.sum(axis=1) / 2.0
    c = diag.sum() / 2.0 + off.sum() / 4.0
    return h, J, c


class PathIntegralSQA:
    def __init__(self, trotter: int = 8, sweeps: int = 300, reads: int = 8, temperature: float | None = None,
                 gamma0: float | None = None, seed: int | None = None):
        self.trotter, self.sweeps, self.reads = trotter, sweeps, reads
        self.temperature, self.gamma0 = temperature, gamma0
        self.rng = np.random.default_rng(seed)

    def solve(self, Q: np.ndarray) -> AnnealResult:
        t0 = time.perf_counter()
        h, J, c = qubo_to_ising(Q)
        n = len(h)
        scale = max(np.abs(J).sum(axis=1).max(), np.abs(h).max(), 1e-9)
        T = self.temperature if self.temperature is not None else 0.05 * scale
        g0 = self.gamma0 if self.gamma0 is not None else 3.0 * scale
        M, R = self.trotter, self.reads
        s = self.rng.choice([-1.0, 1.0], size=(R, M, n))
        gammas = g0 * np.geomspace(1.0, 1e-3, self.sweeps)
        J2 = 2.0 * J  # E = s^T J s counts each pair twice
        even, odd = np.arange(0, M, 2), np.arange(1, M, 2)
        for gamma in gammas:
            j_perp = -0.5 * T * np.log(np.tanh(gamma / (M * T)))
            for i in self.rng.permutation(n):
                for slices in (even, odd):
                    si = s[:, slices, i]
                    local = h[i] + s[:, slices, :] @ J2[:, i]
                    up = s[:, (slices + 1) % M, i]
                    down = s[:, (slices - 1) % M, i]
                    # energy of spin i in slice k: si * (local / M) - j_perp * si * (up + down)
                    dE = -2.0 * si * (local / M - j_perp * (up + down))
                    accept = (dE <= 0) | (self.rng.random(si.shape) < np.exp(-np.clip(dE, 0, None) / T))
                    s[:, slices, i] = np.where(accept, -si, si)
        x = ((s.reshape(R * M, n) + 1) / 2).astype(int)
        e = qubo_energy(Q, x)
        best = int(np.argmin(e))
        return AnnealResult(x=x[best], energy=float(e[best]), energies=e, seconds=time.perf_counter() - t0,
                            solver="path-integral SQA (numpy)")


def _qubo_dict(Q: np.ndarray) -> dict[tuple[int, int], float]:
    Q = symmetric(Q)
    n = Q.shape[0]
    out: dict[tuple[int, int], float] = {}
    rows, cols = np.nonzero(np.triu(Q))
    for i, j in zip(rows, cols):
        out[(int(i), int(j))] = float(Q[i, j] if i == j else 2.0 * Q[i, j])
    for i in range(n):
        out.setdefault((i, i), 0.0)
    return out


def _openjij_solve(sampler, Q: np.ndarray, name: str, **kwargs) -> AnnealResult:
    t0 = time.perf_counter()
    resp = sampler.sample_qubo(_qubo_dict(Q), **kwargs)
    n = Q.shape[0]
    xs = np.array([[s[i] for i in range(n)] for s in resp.record.sample]) if hasattr(resp, "record") else None
    if xs is None:
        xs = np.array([[sample[i] for i in range(n)] for sample in resp.samples()])
    e = qubo_energy(Q, xs)
    best = int(np.argmin(e))
    return AnnealResult(x=xs[best].astype(int), energy=float(e[best]), energies=e,
                        seconds=time.perf_counter() - t0, solver=name)


def solve_openjij_sqa(Q: np.ndarray, reads: int = 20, sweeps: int = 1000, trotter: int = 8, seed: int | None = None) -> AnnealResult:
    import openjij as oj

    kwargs = {"num_reads": reads, "num_sweeps": sweeps, "trotter": trotter}
    if seed is not None:
        kwargs["seed"] = seed
    return _openjij_solve(oj.SQASampler(), Q, "OpenJij SQA (path-integral)", **kwargs)


def solve_openjij_sa(Q: np.ndarray, reads: int = 20, sweeps: int = 1000, seed: int | None = None) -> AnnealResult:
    import openjij as oj

    kwargs = {"num_reads": reads, "num_sweeps": sweeps}
    if seed is not None:
        kwargs["seed"] = seed
    return _openjij_solve(oj.SASampler(), Q, "OpenJij SA (classical)", **kwargs)


def to_bqm(Q: np.ndarray, offset: float = 0.0, labels: list[str] | None = None):
    """Export to a dimod BQM (runs unchanged on D-Wave hardware via DWaveSampler)."""
    import dimod

    qd = _qubo_dict(Q)
    if labels is not None:
        qd = {(labels[i], labels[j]): v for (i, j), v in qd.items()}
    return dimod.BinaryQuadraticModel.from_qubo(qd, offset=offset)


def brute_force(Q: np.ndarray) -> tuple[np.ndarray, float]:
    n = Q.shape[0]
    if n > 22:
        raise ValueError("brute force limited to 22 variables")
    xs = ((np.arange(2**n)[:, None] >> np.arange(n)) & 1).astype(float)
    e = qubo_energy(Q, xs)
    i = int(np.argmin(e))
    return xs[i].astype(int), float(e[i])
