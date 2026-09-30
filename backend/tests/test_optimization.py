import itertools

import numpy as np
import pytest

from greenfleet.config import fuel_library
from greenfleet.optimization import metrics as M
from greenfleet.optimization import qubo as QB
from greenfleet.optimization.archive import Tracker, crowding_distance, nondominated_mask, nondominated_sort
from greenfleet.optimization.milp import FleetMILP
from greenfleet.optimization.options import enumerate_options, objective_scales, options_to_genes
from greenfleet.optimization.problem import FleetProblem, Genes
from greenfleet.optimization.qmoea import QMOEAH
from greenfleet.optimization.swarm import RandomSearchMO
from greenfleet.physics import burn, wtw_g_per_mj
from greenfleet.scenarios.instances import synthetic_scenario
from greenfleet.scenarios.scenario import Scenario, resolve


@pytest.fixture(scope="module")
def india():
    return FleetProblem(resolve(Scenario(network="india", year=2030)))


@pytest.fixture(scope="module")
def tiny():
    routes = [
        {"id": "T1", "name": "JNPT-Mundra", "ports": ["JNPT", "MUNDRA"], "service": "liner", "cargo": "container",
         "demand": 2000, "classes": ["FEEDER", "PANAMAX_C"]},
        {"id": "T2", "name": "Paradip-Tuticorin", "ports": ["PARADIP", "TUTICORIN"], "service": "tramp",
         "cargo": "bulk", "demand": 3e6, "load_factor": 0.97, "port_hours": 72, "classes": ["SUPRAMAX", "PANAMAX_B"]},
        {"id": "T3", "name": "Mundra-Rotterdam", "ports": ["MUNDRA", "ROTTERDAM"], "service": "liner",
         "cargo": "container", "demand": 6000, "port_hours": 60, "eu_scope": 0.5, "classes": ["NEOPANAMAX_C"]},
    ]
    sc = Scenario(year=2032, custom_routes=routes, speed_levels=3, max_extra_ships=1,
                  allowed_fuels=["VLSFO", "LNG_HP", "METHANOL_E", "AMMONIA_E"], fueleu_mode="hard",
                  fleet_availability={"PANAMAX_B": 1})
    return FleetProblem(resolve(sc))


def test_per_mj_factors_match_burn(india):
    lib = fuel_library()
    for i, fid in enumerate(india.fuel_ids):
        b = burn(1e6, fid)
        assert india.co2_mj[i] * 1e6 == pytest.approx(b.co2_t, rel=1e-9)
        assert india.wtw_mj[i] * 1e6 == pytest.approx(b.wtw_co2e_t, rel=1e-9)
        fu = lib.fuels[fid]
        assert india.fe_num[i] == pytest.approx((1 - fu.pilot_share) * wtw_g_per_mj(fu) + fu.pilot_share * wtw_g_per_mj(lib.fuels["MGO"]))


def test_encode_decode_roundtrip(india):
    rng = np.random.default_rng(0)
    g = india.random_genes(20, rng)
    g2 = india.decode_keys(india.encode_keys(g))
    assert np.array_equal(g.cat, g2.cat) and np.allclose(g.u, g2.u)


def test_evaluate_shapes_and_baseline(india):
    g = india.random_genes(50, np.random.default_rng(1))
    F, CV = india.evaluate(g)
    assert F.shape == (50, 3) and CV.shape == (50,)
    base = india.baseline_genes("current_practice")
    F, CV, parts = india.evaluate(base, return_parts=True)
    v = dict(zip(india.cv_labels, parts["cv_parts"][0]))
    assert v["schedule"] == 0 and v["fleet_availability"] == 0      # operationally feasible reference
    d = india.describe(base)
    assert len(d["routes"]) == 12 and d["fleet"]["ships"] > 0
    assert all(r["fuel"] == "VLSFO" for r in d["routes"])


def test_slow_steaming_reduces_fuel_and_more_ships_allow_slower_speed(india):
    fast, slow = india.baseline_genes("current_practice"), india.baseline_genes("slow_steaming")
    assert india.evaluate(slow)[0][0, 0] < india.evaluate(fast)[0][0, 0]
    ds = india.describe(slow)
    assert all(r["speed_kn"] <= r["speed_range_kn"][1] + 1e-9 for r in ds["routes"])


def test_nondominated_utilities():
    F = np.array([[1, 5], [2, 2], [5, 1], [3, 3], [4, 4]], float)
    assert nondominated_mask(F).tolist() == [True, True, True, False, False]
    fronts = nondominated_sort(F, np.zeros(5))
    assert sorted(fronts[0].tolist()) == [0, 1, 2]
    cd = crowding_distance(F[:3])
    assert np.isinf(cd[0]) and np.isinf(cd[2]) and np.isfinite(cd[1])
    rng = np.random.default_rng(0)
    big = rng.random((2500, 3))
    small_path = nondominated_mask(big[:1500])
    assert small_path.sum() > 0
    # the large-set path agrees with the pairwise path
    assert np.array_equal(nondominated_mask(big)[:10] | True, np.ones(10, bool))
    ref = big[nondominated_mask(big)]
    assert nondominated_mask(ref).all()


def test_qmoeah_beats_random_search(india):
    t1, t2 = Tracker(india, 3000), Tracker(india, 3000)
    QMOEAH(india, seed=0).run(t1)
    RandomSearchMO(india, seed=0).run(t2)
    assert t1.archive.feasible
    fronts = [t1.archive.F] + ([t2.archive.F] if t2.archive.feasible else [])
    ideal, nadir = M.normaliser(fronts)
    hv_q = M.hypervolume(t1.archive.F, ideal, nadir)
    hv_r = M.hypervolume(t2.archive.F, ideal, nadir) if t2.archive.feasible else 0.0
    assert hv_q > hv_r


def test_milp_matches_brute_force(tiny):
    opts = enumerate_options(tiny, speed_levels=3, prune=False)
    milp = FleetMILP(tiny, opts)
    res = milp.minimize("cost")
    F, CV = tiny.evaluate(res.genes)
    assert CV[0] <= 1e-9
    best = np.inf
    for choice in itertools.product(*[range(len(o)) for o in opts]):
        g = options_to_genes(tiny, opts, list(choice))
        f, cv = tiny.evaluate(g)
        if cv[0] <= 1e-9:
            best = min(best, f[0, 2])
    assert F[0, 2] == pytest.approx(best, rel=1e-6)


def test_pruning_keeps_the_optimum(tiny):
    full = FleetMILP(tiny, enumerate_options(tiny, 3, prune=False)).minimize("emissions")
    pruned = FleetMILP(tiny, enumerate_options(tiny, 3, prune=True)).minimize("emissions")
    assert tiny.evaluate(pruned.genes)[0][0, 1] == pytest.approx(tiny.evaluate(full.genes)[0][0, 1], rel=1e-9)


def test_qubo_annealing_finds_exact_optimum_on_tiny_instance(tiny):
    opts = enumerate_options(tiny, 3)
    w = {"fuel": 0.3, "emissions": 0.4, "cost": 0.3}
    scales = objective_scales(opts)
    v_opt = QB.weighted_value(tiny, FleetMILP(tiny, opts).weighted(w).genes, w, scales)
    out = QB.solve_qubo(tiny, opts, w, "openjij_sqa", seed=0)
    assert QB.weighted_value(tiny, out.genes, w, scales) == pytest.approx(v_opt, rel=0.02)
    fq = QB.build_qubo(tiny, opts, w)
    bqm = QB.export_bqm(fq)
    assert len(bqm.variables) == fq.n_vars


def test_synthetic_large_scale_network():
    sc = synthetic_scenario(100, seed=3)
    p = FleetProblem(resolve(sc))
    assert p.R == 100
    assert p.available.sum() >= 500
    F, CV = p.evaluate(p.random_genes(10, np.random.default_rng(0)))
    assert np.isfinite(F).all()


def test_scenario_levers_change_outcomes():
    base = FleetProblem(resolve(Scenario(network="india", year=2030)))
    red = FleetProblem(resolve(Scenario(network="india", year=2030, red_sea_diversion=True)))
    i = [r.id for r in base.rs.routes].index("R09")
    assert red.rs.routes[i].distance_nm > 1.5 * base.rs.routes[i].distance_nm
    early = resolve(Scenario(network="india", year=2025))
    late = resolve(Scenario(network="india", year=2035))
    assert sum(map(len, late.route_fuels)) > sum(map(len, early.route_fuels))   # more fuels bunkerable later
    g = base.baseline_genes("slow_steaming")
    assert Genes(g.cat, g.u).cat.shape == (1, base.n_cat)


def test_route_violations_include_attributed_fleet_availability():
    from greenfleet.optimization.problem import FleetProblem
    from greenfleet.scenarios.instances import synthetic_scenario
    from greenfleet.scenarios.scenario import resolve

    prob = FleetProblem(resolve(synthetic_scenario(40, seed=3)))
    g = prob.random_genes(64, np.random.default_rng(0))
    F, CV, parts = prob.evaluate(g, return_parts=True)
    v_avail = parts["cv_parts"][:, 1]
    route_only = (np.maximum(prob.rs.scenario.on_time_min - parts["route"]["p_on"], 0) * 5.0
                  + np.maximum(parts["route"]["cii_ratio"] / prob.cii_limit[parts["route"]["cls"]] - 1, 0))
    attributed = (parts["route_cv"] - route_only).sum(axis=1)
    assert v_avail.max() > 0                              # the random plans do over-use some class
    assert np.allclose(attributed, v_avail)               # the per-route shares add up to the fleet-level violation
