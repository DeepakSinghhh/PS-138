import numpy as np
import pytest

from greenfleet.optimization.archive import Tracker
from greenfleet.optimization.problem import FleetProblem
from greenfleet.optimization.qmoea import QMOEAH
from greenfleet.scenarios import analysis as A
from greenfleet.scenarios.scenario import Scenario, resolve


@pytest.fixture(scope="module")
def solved():
    p = FleetProblem(resolve(Scenario(network="india", year=2030)))
    t = Tracker(p, 3000)
    QMOEAH(p, seed=1).run(t)
    return p, t.archive


def test_knee_point_is_balanced():
    F = np.array([[0, 10], [1, 1], [10, 0]], float)
    assert A.knee_point(F) == 1
    assert A.pick(F, ["a", "b"], "b") == 2


def test_explanation_mentions_levers(solved):
    p, arch = solved
    k = A.knee_point(arch.F)
    ex = A.explain(p, arch.genes, k)
    assert "current practice" in ex["summary"]
    assert set(ex["delta_pct"]) == {"fuel", "emissions", "cost"}
    assert ex["delta_pct"]["emissions"] < 0          # optimised plans beat full-speed VLSFO on emissions


def test_robustness_quantiles_are_ordered(solved):
    p, arch = solved
    r = A.robustness(p, arch.genes.take([0]), n_samples=200, seed=0)
    for k in ("cost", "emissions", "fuel"):
        assert r[k]["p5"] <= r[k]["p50"] <= r[k]["p95"] <= r[k]["cvar95"] + 1e-9


def test_macc_sorted_by_cost_effectiveness(solved):
    p, _ = solved
    rows = [m for m in A.macc(p)["measures"] if m["usd_per_t"] is not None]
    assert rows and all(a["usd_per_t"] <= b["usd_per_t"] for a, b in zip(rows, rows[1:]))
    assert any(m["measure"].startswith("Slow steaming") for m in rows)


def test_timeline_shifts_fuel_mix_towards_zero_carbon():
    tl = A.timeline(Scenario(network="india"), years=(2025, 2050), budget=1500, preference="emissions")
    mix25, mix50 = tl["rows"][0]["fuel_mix"], tl["rows"][1]["fuel_mix"]
    fossil = {"HFO", "VLSFO", "MGO"}
    assert sum(v for k, v in mix50.items() if k in fossil) < sum(v for k, v in mix25.items() if k in fossil)
