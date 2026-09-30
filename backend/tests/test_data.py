import numpy as np
import pandas as pd

from greenfleet.config import vessel_classes
from greenfleet.data import add_derived, feature_columns, generate_ship, true_fuel_tpd
from greenfleet.data.loaders import canonicalise_telemetry, match_columns


def test_true_fuel_is_monotone_in_speed_and_waves():
    vc = vessel_classes()["PANAMAX_C"]
    v = np.linspace(10, 22, 25)
    ones = np.ones_like(v)
    f = true_fuel_tpd(vc, v, ones * vc.design_draft_m, ones * 0.3, ones * 100, ones * 5, ones * 0, ones * 1.0, ones * 0)
    assert np.all(np.diff(f) > 0)
    f_calm = true_fuel_tpd(vc, ones * 18, ones * vc.design_draft_m, ones * 0.3, ones * 100, ones * 0, ones * 90, ones * 0.5, ones * 90)
    f_storm = true_fuel_tpd(vc, ones * 18, ones * vc.design_draft_m, ones * 0.3, ones * 100, ones * 18, ones * 0, ones * 5.0, ones * 0)
    assert f_storm[0] > 1.1 * f_calm[0]


def test_generated_ship_schema():
    df = add_derived(generate_ship(vessel_classes()["SUPRAMAX"], 0, days=60, seed=1))
    assert len(df) > 100
    assert df["fuel_tpd"].between(3, 80).all()
    assert (df["source"] == "synthetic").all()
    cols = feature_columns(df, include_descriptors=False)
    assert "speed_kn" in cols and "head_wave_m" in cols


def test_alias_matching_handles_real_world_names():
    cols = ["Time (UTC)", "Speed Through Water [kn]", "Draft Mean", "Wind Speed", "Wind Direction",
            "Significant Wave Height", "Heading", "Fuel Consumption [t/day]", "ME Power"]
    m = match_columns(cols, {"speed_kn": ["speed_through_water"], "draft": ["draft_mean"],
                             "fuel": ["fuel_consumption"], "wave_height_m": ["significant_wave_height"]})
    assert m["speed_kn"] == "Speed Through Water [kn]"
    assert m["fuel"] == "Fuel Consumption [t/day]"


def test_canonicalise_relative_angles():
    raw = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=4, freq="h"),
        "stw": [12, 13, 14, 15],
        "draft": [10, 10, 11, 11],
        "wind_speed": [5, 5, 5, 5],
        "wind_direction": [90, 270, 0, 180],
        "heading": [90, 90, 90, 90],
        "fuel_consumption": [30, 32, 35, 38],
    })
    out = canonicalise_telemetry(raw, "ship", "test")
    assert out["wind_rel_deg"].tolist() == [0, 180, 90, 90]
    assert out["fuel_tpd"].tolist() == [30, 32, 35, 38]
