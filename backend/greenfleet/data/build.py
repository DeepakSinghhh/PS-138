"""Build processed datasets: ``python -m greenfleet.data.build``.

Writes ``data/processed/{synthetic_fleet,fuelcast}.parquet`` and a data card
(``data/processed/data_card.json``) describing what was found and used.
"""

from __future__ import annotations

import json
import logging

from greenfleet.config import DATA_DIR
from greenfleet.data.loaders import load_fuelcast, load_kaggle_ship_fuel, load_mrv, load_user_fleet, mrv_summary
from greenfleet.data.synthetic import generate_fleet

PROCESSED = DATA_DIR / "processed"


def build(ships_per_class: int = 2, days: int = 365) -> dict:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    card: dict = {"sources": {}}

    fleet = generate_fleet(ships_per_class=ships_per_class, days=days)
    fleet.to_parquet(PROCESSED / "synthetic_fleet.parquet", index=False)
    card["sources"]["synthetic"] = {
        "rows": len(fleet),
        "ships": int(fleet["ship_id"].nunique()),
        "classes": sorted(fleet["vessel_class"].unique().tolist()),
        "vessel_types": sorted(fleet["vessel_type"].unique().tolist()),
        "inputs_available": {"speed": True, "load": True, "weather": True, "vessel_type": True},
        "note": "physics-informed synthetic telemetry (labelled synthetic everywhere)",
    }

    for name, loader in (("fuelcast", load_fuelcast), ("user_fleet", load_user_fleet)):
        tel = loader()
        if tel is None:
            card["sources"][name] = {"rows": 0, "note": f"not found in data/raw/{name}"}
            continue
        tel.to_parquet(PROCESSED / f"{name}.parquet", index=False)
        card["sources"][name] = {
            "rows": len(tel),
            "ships": sorted(tel["ship_id"].unique().tolist()),
            "vessel_types": sorted(tel["vessel_type"].unique().tolist()),
            "inputs_available": {
                "speed": bool(tel["speed_kn"].notna().any()),
                "load": bool(tel["load_ratio"].notna().any()),
                "weather": bool(tel[["wind_speed_ms", "wave_height_m"]].notna().any().any()),
                "vessel_type": bool((tel["vessel_type"] != "other").any()),
            },
            "column_map": tel.attrs.get("column_map", {}),
            "excluded_leakage_columns": tel.attrs.get("excluded_leakage", []),
        }

    mrv = load_mrv()
    if mrv is not None:
        summ = mrv_summary(mrv)
        summ.to_csv(PROCESSED / "mrv_summary.csv", index=False)
        card["sources"]["mrv"] = {"rows": len(mrv), "ship_types": len(summ)}
    else:
        card["sources"]["mrv"] = {"rows": 0, "note": "not found in data/raw/mrv"}

    kg = load_kaggle_ship_fuel()
    if kg is not None:
        kg.to_parquet(PROCESSED / "kaggle_ship_fuel.parquet", index=False)
        card["sources"]["kaggle_ship_fuel"] = {
            "rows": len(kg),
            "vessel_types": sorted(kg["vessel_type"].unique().tolist()),
            "column_map": kg.attrs.get("column_map", {}),
        }
    else:
        card["sources"]["kaggle_ship_fuel"] = {"rows": 0, "note": "not found in data/raw/kaggle_ship_fuel"}

    with open(PROCESSED / "data_card.json", "w") as fh:
        json.dump(card, fh, indent=2, default=str)
    return card


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(build(), indent=2, default=str))
