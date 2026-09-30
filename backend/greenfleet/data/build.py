"""Build processed datasets: ``python -m greenfleet.data.build``.

Writes ``data/processed/{synthetic_fleet,fuelcast}.parquet`` and a data card
(``data/processed/data_card.json``) describing what was found and used.
"""

from __future__ import annotations

import json
import logging

from greenfleet.config import DATA_DIR
from greenfleet.data.loaders import load_fuelcast, load_kaggle_ship_fuel, load_mrv, mrv_summary
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
        "note": "physics-informed synthetic telemetry (labelled synthetic everywhere)",
    }

    fc = load_fuelcast()
    if fc is not None:
        fc.to_parquet(PROCESSED / "fuelcast.parquet", index=False)
        card["sources"]["fuelcast"] = {
            "rows": len(fc),
            "ships": sorted(fc["ship_id"].unique().tolist()),
            "column_map": fc.attrs.get("column_map", {}),
        }
    else:
        card["sources"]["fuelcast"] = {"rows": 0, "note": "not found in data/raw/fuelcast"}

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
        card["sources"]["kaggle_ship_fuel"] = {"rows": len(kg)}
    else:
        card["sources"]["kaggle_ship_fuel"] = {"rows": 0, "note": "not found in data/raw/kaggle_ship_fuel"}

    with open(PROCESSED / "data_card.json", "w") as fh:
        json.dump(card, fh, indent=2, default=str)
    return card


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(build(), indent=2, default=str))
