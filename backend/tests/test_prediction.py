import numpy as np
import pandas as pd
import pytest

from greenfleet.data import add_derived, feature_columns, generate_fleet
from greenfleet.prediction.conformal import ConformalCalibrator
from greenfleet.prediction.hybrid import QPhys
from greenfleet.prediction.models import chronological_split, metrics
from greenfleet.prediction.mps import MPSRegressor
from greenfleet.prediction.surrogate import FuelCorrection, build_surrogate
from greenfleet.prediction.tuning import TUNERS, Dim, SearchSpace, tune


def test_mps_fits_smooth_interactions():
    rng = np.random.default_rng(0)
    f = lambda X: 3 * X[:, 0] ** 3 + 2 * X[:, 1] * X[:, 0] ** 2 + np.sin(3 * X[:, 2])  # noqa: E731
    X, Xt = rng.uniform(0, 1, (4000, 4)), rng.uniform(0, 1, (1000, 4))
    m = MPSRegressor(bond_dim=4, local_dim=5, sweeps=4, ridge=1e-7).fit(X, f(X))
    assert metrics(f(Xt), m.predict(Xt))["R2"] > 0.995
    ent = m.entanglement_entropy()
    assert len(ent) == 3 and min(ent) >= 0
    # the irrelevant 4th feature carries almost no entanglement across the last bond
    assert ent[-1] < ent[0]


def test_mps_rejects_odd_local_dim_without_constant():
    with pytest.raises(ValueError):
        MPSRegressor(local_dim=4)


def test_conformal_coverage_on_exchangeable_data():
    rng = np.random.default_rng(1)
    p = rng.uniform(10, 50, 6000)
    y = p * (1 + rng.normal(0, 0.05, 6000))
    cal = ConformalCalibrator(alpha=0.1).fit(y[:2000], p[:2000])
    res = cal.evaluate(y[2000:], p[2000:])
    assert 0.87 < res["coverage"] < 0.93


@pytest.mark.parametrize("tuner", TUNERS)
def test_tuners_respect_budget(tuner):
    space = SearchSpace([Dim("a", 0.0, 1.0), Dim("b", 1e-3, 1.0, log=True), Dim("c", 1, 10, integer=True)])
    calls = []

    def obj(p):
        calls.append(p)
        return (p["a"] - 0.3) ** 2 + np.log10(p["b"]) ** 2 + (p["c"] - 4) ** 2 * 0.01

    res = tune(tuner, space, obj, budget=12, seed=0)
    assert len(calls) <= 12
    assert len(res.history) == 12
    assert all(b <= a for a, b in zip(res.history, res.history[1:]))
    assert isinstance(res.best_params["c"], int)


@pytest.fixture(scope="module")
def small_fleet():
    return add_derived(generate_fleet(classes=["FEEDER", "SUPRAMAX", "AFRAMAX"], ships_per_class=2, days=120, seed=5))


def test_qphys_trains_and_is_monotone_in_speed(small_fleet):
    split = chronological_split(small_fleet)
    feats = feature_columns(small_fleet)
    q = QPhys(features=feats, tune_budget=4, select_budget=6, seed=0)
    q.fit(split.train, split.train["fuel_tpd"].to_numpy(), split.val, split.val["fuel_tpd"].to_numpy(),
          split.cal, split.cal["fuel_tpd"].to_numpy())
    y = split.test["fuel_tpd"].to_numpy()
    assert metrics(y, q.predict(split.test))["MAPE"] < 8.0
    for f in ("speed_kn", "load_ratio", "wind_speed_ms", "wave_height_m"):
        assert f in q.selected_                                # PS-mandated inputs are kept
    # certified monotone variant: fuel never decreases when only speed increases
    row = split.test.iloc[[0]]
    sweep = pd.concat([row] * 30, ignore_index=True)
    sweep["speed_kn"] = np.linspace(8, 19, 30)
    sweep = add_derived(sweep)
    assert np.all(np.diff(q.predict_monotone(sweep)) >= -1e-9)
    lo_hi = q.predict_interval(split.test.head(10))
    assert np.all(lo_hi[1] <= lo_hi[0]) and np.all(lo_hi[0] <= lo_hi[2])
    table = build_surrogate(q, classes=["SUPRAMAX"])
    corr = FuelCorrection(table)
    r = corr.ratio("SUPRAMAX", 12.0, True, 4.0)
    assert 0.5 <= r <= 2.0


def test_fuel_correction_identity_without_table():
    assert FuelCorrection(None).ratio("PANAMAX_C", 15.0, True, 3.0) == 1.0
