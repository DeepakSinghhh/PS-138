import math

import numpy as np
import pytest

from greenfleet.config import fuel_library, interp_year, load_routes, vessel_classes
from greenfleet.physics import (
    burn,
    kwon_speed_loss,
    propulsion_power_kw,
    sfoc_multiplier,
    weather_power_factor,
    wtw_g_per_mj,
)
from greenfleet.regulations import cii, ets, fueleu


def test_hfo_wtw_matches_fueleu_default():
    # FuelEU default HFO: 13.5 + (3.114 + 0.00005*25 + 0.00018*298) / 0.0405 = 91.74 gCO2e/MJ
    assert wtw_g_per_mj(fuel_library().fuels["HFO"]) == pytest.approx(91.74, abs=0.02)


def test_lng_slip_intensities():
    lib = fuel_library()
    # Otto slow-speed (1.7 % slip) sits between Diesel (0.2 %) and Otto medium speed (3.1 %)
    lp = wtw_g_per_mj(lib.fuels["LNG_LP"])
    hp = wtw_g_per_mj(lib.fuels["LNG_HP"])
    assert hp == pytest.approx(76.1, abs=0.2)  # widely quoted FuelEU value for LNG Diesel SS
    assert hp < lp < 91.16


def test_one_tonne_hfo_gives_3114_kg_co2():
    lib = fuel_library()
    energy = 1e6 * lib.fuels["HFO"].lcv_mj_per_g  # 1 t in MJ
    b = burn(energy, "HFO")
    assert b.total_fuel_t == pytest.approx(1.0)
    assert b.co2_t == pytest.approx(3.114, rel=1e-6)


def test_pilot_fuel_split_for_ammonia():
    lib = fuel_library()
    b = burn(1e6, "AMMONIA_E")
    assert set(b.fuel_t) == {"AMMONIA_E", "MGO"}
    assert b.energy_mj["MGO"] == pytest.approx(1e6 * lib.fuels["AMMONIA_E"].pilot_share)
    assert b.co2_t > 0  # only from the pilot fuel


def test_e_fuels_are_far_below_fossil():
    lib = fuel_library()
    for fid in ["METHANOL_E", "AMMONIA_E", "H2_E"]:
        assert wtw_g_per_mj(lib.fuels[fid]) < 0.3 * 94.0  # RFNBO >= 70 % saving vs fossil comparator


def test_sfoc_curve_minimum_near_78_percent_load():
    loads = np.linspace(0.2, 1.0, 81)
    assert loads[np.argmin(sfoc_multiplier(loads))] == pytest.approx(0.78, abs=0.02)


def test_power_cube_law_and_draft():
    vc = vessel_classes()["PANAMAX_C"]
    p1 = propulsion_power_kw(vc, 20.0)
    p2 = propulsion_power_kw(vc, 10.0)
    assert p1 / p2 == pytest.approx(8.0)
    assert propulsion_power_kw(vc, 20.0, draft_m=vc.ballast_draft_m) < p1


def test_panamax_daily_fuel_is_realistic():
    # ~100-130 t/day HFO at 22 kn for a 4,500 TEU ship is the commonly reported range
    vc = vessel_classes()["PANAMAX_C"]
    p = propulsion_power_kw(vc, 22.0, weather_factor=weather_power_factor(vc, 22.0, 4.0))
    load = p / vc.mcr_kw
    energy = p * 24 * 7.0 * sfoc_multiplier(load)
    t_per_day = energy / fuel_library().fuels["HFO"].lcv_mj_per_g / 1e6
    assert 95 < t_per_day < 140


def test_kwon_loss_monotone_in_beaufort():
    vc = vessel_classes()["SUPRAMAX"]
    losses = [kwon_speed_loss(bn, 13.0, vc) for bn in range(0, 9)]
    assert losses[0] == 0.0
    assert all(b >= a for a, b in zip(losses, losses[1:]))
    assert 0.0 < losses[5] < 0.25


def test_cii_reference_and_rating():
    vc = vessel_classes()["SUPRAMAX"]
    ref = cii.reference_cii(vc)
    assert ref == pytest.approx(4745 * 58000 ** -0.622, rel=1e-9)
    req = cii.required_cii(vc, 2026)
    assert req == pytest.approx(ref * 0.89)
    assert cii.rating(req * 0.85, req, "bulk_carrier") == "A"
    assert cii.rating(req * 1.00, req, "bulk_carrier") == "C"
    assert cii.rating(req * 1.20, req, "bulk_carrier") == "E"
    assert cii.reduction_pct(2030) == pytest.approx(21.5)
    assert cii.reduction_pct(2032) == pytest.approx(21.5 + 2 * 2.625)


def test_fueleu_targets_and_penalty():
    assert fueleu.target_intensity(2025) == pytest.approx(91.16 * 0.98)
    assert fueleu.target_intensity(2029) == pytest.approx(91.16 * 0.98)
    assert fueleu.target_intensity(2030) == pytest.approx(91.16 * 0.94)
    assert fueleu.target_intensity(2050) == pytest.approx(91.16 * 0.20)
    # a ship burning only HFO (91.74) in 2025: deficit = (89.34 - 91.74) * E
    e = 1e9
    res = fueleu.assess({"HFO": e}, 0.0, 2025)
    hfo = wtw_g_per_mj(fuel_library().fuels["HFO"])
    assert res.balance_g == pytest.approx((91.16 * 0.98 - hfo) * e, rel=1e-9)
    expected_penalty = abs(res.balance_g) / (res.intensity * 41000) * 2400
    assert res.penalty_eur == pytest.approx(expected_penalty)


def test_fueleu_rfnbo_reward_and_ops():
    e = 1e9
    no_reward = fueleu.intensity({"VLSFO": e, "METHANOL_E": e}, 0.0, 2040)
    reward = fueleu.intensity({"VLSFO": e, "METHANOL_E": e}, 0.0, 2030)
    assert reward < no_reward
    with_ops = fueleu.intensity({"VLSFO": e}, 0.1 * e, 2030)
    assert with_ops < fueleu.intensity({"VLSFO": e}, 0.0, 2030)


def test_ets_phase_in():
    assert ets.allowances_t(100, 0, 0, 1.0, 2024) == pytest.approx(40)
    assert ets.allowances_t(100, 0, 0, 0.5, 2025) == pytest.approx(35)
    # CH4 / N2O join in 2026
    assert ets.allowances_t(100, 1, 0, 1.0, 2026) == pytest.approx(125)


def test_interp_year():
    s = {2025: 100, 2030: 50}
    assert interp_year(s, 2020) == 100
    assert interp_year(s, 2027.5) == pytest.approx(75)
    assert interp_year(s, 2040) == 50


def test_routes_have_sea_distances():
    _, routes = load_routes("routes_india.yaml")
    assert len(routes) == 12
    by_id = {r.id: r for r in routes}
    assert by_id["R09"].distance_nm == pytest.approx(6348, rel=0.05)  # Mundra-Rotterdam via Suez
    assert all(r.distance_nm > 100 for r in routes)
    assert all(len(r.geometry) >= 2 for r in routes)
    assert not math.isnan(sum(r.distance_nm for r in routes))
