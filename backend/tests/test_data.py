import numpy as np
import pandas as pd

from greenfleet.config import vessel_classes
from greenfleet.data import add_derived, feature_columns, generate_ship, true_fuel_tpd
from greenfleet.data.loaders import (
    canonicalise_telemetry,
    infer_vessel_type,
    load_kaggle_ship_fuel,
    load_telemetry_folder,
    match_columns,
)
from greenfleet.data.schema import normalise_vessel_type


def test_true_fuel_is_monotone_in_speed_and_waves():
    vc = vessel_classes()["PANAMAX_C"]
    v = np.linspace(10, 22, 25)
    ones = np.ones_like(v)
    f = true_fuel_tpd(vc, v, ones * vc.design_draft_m, ones * 0.3, ones * 100, ones * 5, ones * 0, ones * 1.0, ones * 0)
    assert np.all(np.diff(f) > 0)
    f_calm = true_fuel_tpd(vc, ones * 18, ones * vc.design_draft_m, ones * 0.3, ones * 100, ones * 0, ones * 90, ones * 0.5, ones * 90)
    f_storm = true_fuel_tpd(vc, ones * 18, ones * vc.design_draft_m, ones * 0.3, ones * 100, ones * 18, ones * 0, ones * 5.0, ones * 0)
    assert f_storm[0] > 1.1 * f_calm[0]


def test_generated_ship_has_all_ps_inputs():
    # PS Delivery Table item 1: speed, load, weather, vessel type
    df = add_derived(generate_ship(vessel_classes()["SUPRAMAX"], 0, days=60, seed=1))
    assert len(df) > 100
    assert df["fuel_tpd"].between(3, 80).all()
    assert (df["source"] == "synthetic").all()
    assert (df["vessel_type"] == "bulk").all()
    assert df["load_ratio"].between(0, 1).all()
    # laden and ballast passages both occur, and draft follows load
    assert df["load_ratio"].min() < 0.1 and df["load_ratio"].max() > 0.85
    assert np.corrcoef(df["load_ratio"], df["draft_ratio"])[0, 1] > 0.95
    cols = feature_columns(df, include_descriptors=False)
    assert {"speed_kn", "load_ratio", "wind_speed_ms", "wave_height_m"} <= set(cols)


def test_vessel_type_one_hot_in_pooled_features():
    df = add_derived(pd.concat([
        generate_ship(vessel_classes()["SUPRAMAX"], 0, days=20, seed=1),
        generate_ship(vessel_classes()["FEEDER"], 0, days=20, seed=2),
    ]))
    cols = feature_columns(df, include_descriptors=True)
    assert "vt_bulk" in cols and "vt_container" in cols


def test_vessel_type_normalisation():
    assert normalise_vessel_type("Bulk carrier") == "bulk"
    assert normalise_vessel_type("Ro-pax ship") == "pax"
    assert normalise_vessel_type("Oil Service Boat") == "tanker"
    assert infer_vessel_type("cps_poseidon") == "cruise"
    assert infer_vessel_type("oss_ceto") == "offshore"


def test_alias_matching_handles_real_world_names():
    cols = ["Time (UTC)", "Speed Through Water [kn]", "Draft Mean", "Wind Speed", "Wind Direction",
            "Significant Wave Height", "Heading", "Fuel Consumption [t/day]", "ME Power"]
    m = match_columns(cols, {"speed_kn": ["speed_through_water"], "draft": ["draft_mean"],
                             "fuel": ["fuel_consumption"], "wave_height_m": ["significant_wave_height"]})
    assert m["speed_kn"] == "Speed Through Water [kn]"
    assert m["fuel"] == "Fuel Consumption [t/day]"


def _raw_frame():
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=4, freq="h"),
        "stw": [12, 13, 14, 15],
        "draft": [10, 10, 11, 11],
        "wind_speed": [5, 5, 5, 5],
        "wind_direction": [90, 270, 0, 180],
        "heading": [90, 90, 90, 90],
        "fuel_consumption": [30, 32, 35, 38],
    })


def test_canonicalise_relative_angles_and_load_from_draft():
    out = canonicalise_telemetry(_raw_frame(), "ship", "test", vessel_type="Bulk carrier")
    assert out["wind_rel_deg"].tolist() == [0, 180, 90, 90]
    assert out["fuel_tpd"].tolist() == [30, 32, 35, 38]
    assert (out["vessel_type"] == "bulk").all()
    assert out["load_ratio"].between(0, 1).all()        # estimated from draft


def test_cargo_load_is_used_and_engine_load_is_excluded():
    raw = _raw_frame()
    raw["Cargo Load [%]"] = [50, 60, 80, 100]
    raw["ME Load [%MCR]"] = [60, 70, 80, 90]
    raw["Shaft Power [kW]"] = [1, 2, 3, 4]
    out = canonicalise_telemetry(raw, "ship", "test")
    assert out["load_ratio"].tolist() == [0.5, 0.6, 0.8, 1.0]
    assert "ME Load [%MCR]" in out.attrs["excluded_leakage"]
    assert "Shaft Power [kW]" in out.attrs["excluded_leakage"]
    assert "ME Load [%MCR]" not in out.attrs["column_map"].values()


def test_laden_ballast_labels_and_flow_rate_target():
    raw = _raw_frame().drop(columns=["fuel_consumption"])
    raw["loading_condition"] = ["Laden", "Laden", "Ballast", "Ballast"]
    raw["fuel_flow_rate_kg_h"] = [1000, 1100, 900, 950]
    raw = raw.rename(columns={"fuel_flow_rate_kg_h": "fuel_kg_h"})
    out = canonicalise_telemetry(raw, "ship", "test")
    assert out["load_ratio"].tolist() == [1.0, 1.0, 0.0, 0.0]
    assert out["fuel_tpd"].iloc[0] == 24.0


def test_folder_loader_with_column_override(tmp_path):
    raw = _raw_frame().rename(columns={"stw": "vel"})
    raw.to_csv(tmp_path / "oss_testship.csv", index=False)
    (tmp_path / "columns.yaml").write_text('speed_kn: "vel"\n')
    out = load_telemetry_folder(tmp_path, "user")
    assert len(out) == 4 and (out["vessel_type"] == "offshore").all()


def test_kaggle_loader_canonicalises(tmp_path):
    pd.DataFrame({
        "ship_id": ["NG001", "NG002"],
        "ship_type": ["Oil Service Boat", "Tanker Ship"],
        "route_id": ["Warri-Bonny", "Lagos-Apapa"],
        "month": ["January", "February"],
        "distance": [132.3, 128.5],
        "fuel_type": ["HFO", "Diesel"],
        "fuel_consumption": [3779.8, 4461.4],
        "CO2_emissions": [10625.2, 12779.3],
        "weather_conditions": ["Stormy", "Moderate"],
        "engine_efficiency": [92.1, 87.9],
    }).to_csv(tmp_path / "ship_fuel_efficiency.csv", index=False)
    out = load_kaggle_ship_fuel(tmp_path)
    assert out["vessel_type"].tolist() == ["tanker", "tanker"]
    assert out["weather_level"].tolist() == [2.0, 1.0]
    assert "co2_ref" in out and "fuel" in out
