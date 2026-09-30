import numpy as np
import pytest

from greenfleet.classical import PSO, BinaryGA
from greenfleet.quantum import QIEA, QPSO, QuditRegister
from greenfleet.quantum.sqa import (
    PathIntegralSQA,
    brute_force,
    qubo_energy,
    qubo_to_ising,
    solve_openjij_sa,
    solve_openjij_sqa,
    to_bqm,
)


def sphere(x):
    return float(np.sum(x**2))


def rastrigin(x):
    return float(10 * len(x) + np.sum(x**2 - 10 * np.cos(2 * np.pi * x)))


def test_register_starts_uniform_and_normalised():
    reg = QuditRegister(4, [2, 3, 5])
    p = reg.probabilities()
    assert np.allclose(p.sum(axis=2), 1.0)
    assert np.allclose(p[0, 2, :5], 0.2)
    assert reg.entropy() == pytest.approx(1.0)


def test_rotation_moves_probability_to_guide_and_respects_floor():
    reg = QuditRegister(1, [4], p_floor=0.01)
    for _ in range(200):
        reg.rotate(np.array([[2]]), 0.05 * np.pi)
    p = reg.probabilities()[0, 0, :4]
    assert np.isclose(p.sum(), 1.0)
    assert p[2] > 0.9
    assert p.min() >= 0.0099           # floor keeps every option reachable


def test_binary_rotation_equals_classic_qbit_gate():
    # for K=2 the gate is the Han & Kim rotation: theta -> theta + dtheta towards |1>
    reg = QuditRegister(1, [2], p_floor=0.0)
    reg.rotate(np.array([[1]]), np.pi / 8)
    alpha, beta = reg.psi[0, 0, :2]
    assert np.isclose(np.arctan2(beta, alpha), np.pi / 4 + np.pi / 8)


def test_not_gate_and_measurement_shapes():
    rng = np.random.default_rng(0)
    reg = QuditRegister(10, [3, 2])
    reg.rotate(np.zeros((10, 2), dtype=int), 0.4)
    before = reg.psi.copy()
    reg.not_gate(rng, 1.0)
    assert not np.allclose(before, reg.psi)
    m = reg.measure(rng)
    assert m.shape == (10, 2) and m[:, 0].max() <= 2 and m[:, 1].max() <= 1


@pytest.mark.parametrize("fn,tol", [(sphere, 1e-3), (rastrigin, 3.0)])
def test_qpso_solves_benchmarks(fn, tol):
    d = 5
    res = QPSO(-5.12 * np.ones(d), 5.12 * np.ones(d), pop_size=20, seed=1).minimize(fn, max_evals=4000)
    assert res.f < tol
    assert len(res.history) == res.evaluations
    assert all(b <= a for a, b in zip(res.history, res.history[1:]))


def test_pso_baseline_runs():
    res = PSO(-5 * np.ones(3), 5 * np.ones(3), seed=0).minimize(sphere, max_evals=1500)
    assert res.f < 1e-2


def test_qiea_feature_selection_finds_informative_bits():
    target = np.array([1, 0, 1, 1, 0, 0, 1, 0, 0, 1], dtype=bool)

    def cost(mask):
        return float(np.sum(mask != target))

    q = QIEA(len(target), pop_size=10, seed=3).minimize(cost, max_evals=400)
    g = BinaryGA(len(target), pop_size=10, seed=3).minimize(cost, max_evals=400)
    assert q.f == 0.0
    assert g.f <= 2.0
    # the population converges (entropy drops) before the stagnation reset re-expands it
    assert len(q.entropy) > 0 and min(q.entropy) < 0.8 * q.entropy[0]


def test_binary_optimizers_terminate_on_tiny_spaces():
    def cost(mask):
        return float(mask.sum())

    assert QIEA(2, pop_size=6, seed=0).minimize(cost, max_evals=500).f == 0.0
    assert BinaryGA(2, pop_size=6, seed=0).minimize(cost, max_evals=500).f == 0.0


def random_qubo(n, seed):
    rng = np.random.default_rng(seed)
    Q = rng.normal(0, 1, (n, n))
    return (Q + Q.T) / 2


def test_qubo_ising_roundtrip():
    Q = random_qubo(6, 0)
    h, J, c = qubo_to_ising(Q)
    rng = np.random.default_rng(1)
    for _ in range(10):
        x = rng.integers(0, 2, 6)
        s = 2 * x - 1
        assert qubo_energy(Q, x)[0] == pytest.approx(s @ J @ s + h @ s + c)


def test_sqa_solvers_reach_ground_state():
    Q = random_qubo(12, 7)
    _, e_star = brute_force(Q)
    ours = PathIntegralSQA(trotter=8, sweeps=150, reads=4, seed=0).solve(Q)
    assert ours.energy == pytest.approx(e_star, abs=1e-6)
    assert solve_openjij_sqa(Q, reads=10, sweeps=500, seed=1).energy == pytest.approx(e_star, abs=1e-6)
    assert solve_openjij_sa(Q, reads=10, sweeps=500, seed=1).energy == pytest.approx(e_star, abs=1e-6)


def test_bqm_export_matches_energy():
    Q = random_qubo(5, 3)
    bqm = to_bqm(Q)
    x = np.array([1, 0, 1, 1, 0])
    assert bqm.energy({i: int(v) for i, v in enumerate(x)}) == pytest.approx(qubo_energy(Q, x)[0])
