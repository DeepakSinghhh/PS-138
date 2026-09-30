"""Fuel surrogate for the fleet optimizer, distilled from the trained Q-PHYS-M model.

The optimizer evaluates thousands of fleet plans per second, so it cannot call the ML
model row by row. Instead, the certified-monotone Q-PHYS-M model is sampled on a grid of
(vessel class x loading state x Beaufort x speed) for an *unseen ship of that class*,
averaged over four heading sectors, and stored as a correction ratio relative to the
nominal physics model. The optimizer multiplies its physics fuel estimate by the
interpolated ratio. With no trained artifact the ratio is 1 (pure physics).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from greenfleet.config import ARTIFACTS_DIR, vessel_classes
from greenfleet.data.schema import add_derived
from greenfleet.prediction.physics_model import NominalPhysics

BEAUFORT_GRID = np.arange(0, 9, dtype=float)
N_SPEEDS = 12
HEADINGS = (0.0, 45.0, 110.0, 170.0)
SURROGATE_PATH = ARTIFACTS_DIR / "fuel_surrogate.json"


def loading_states(cargo: str) -> dict[str, float]:
    if cargo in ("bulk", "tanker"):
        return {"laden": 1.0, "return": 0.0}
    if cargo == "container":
        return {"laden": 0.85, "return": 0.55}
    return {"laden": 0.8, "return": 0.8}


def condition_frame(cls_id: str, speeds: np.ndarray, load: float, bn: float) -> pd.DataFrame:
    vc = vessel_classes()[cls_id]
    wind = 0.836 * bn**1.5
    wave = float(np.sqrt((0.0214 * wind**2) ** 2 + 1.0))
    dr_ballast = vc.ballast_draft_m / vc.design_draft_m
    if vc.cargo == "pax":
        draft_ratio = 0.93 + 0.07 * load
    else:
        draft_ratio = dr_ballast + (1 - dr_ballast) * load**0.9
    rows = []
    for h in HEADINGS:
        for s in speeds:
            rows.append({
                "ship_id": f"{cls_id}-new", "vessel_class": cls_id, "vessel_type": vc.cargo,
                "speed_kn": s, "load_ratio": load, "draft_ratio": draft_ratio, "trim_m": 0.3,
                "days_since_cleaning": 365.0, "wind_speed_ms": wind, "wind_rel_deg": h,
                "wave_height_m": wave, "wave_rel_deg": h, "current_kn": 0.0,
                "design_speed_kn": vc.design_speed_kn, "mcr_kw": vc.mcr_kw, "displacement_t": vc.displacement_t,
                "length_m": vc.length_m, "block_coefficient": vc.block_coefficient, "aux_sea_kw": vc.aux_sea_kw,
            })
    return add_derived(pd.DataFrame(rows))


def build_surrogate(model, classes: list[str] | None = None) -> dict:
    """Sample ``model.predict_monotone`` against nominal physics on the condition grid."""
    lib = vessel_classes()
    nominal = NominalPhysics()
    table: dict = {"beaufort": BEAUFORT_GRID.tolist(), "classes": {}}
    for cid in classes or list(lib):
        vc = lib[cid]
        speeds = np.linspace(vc.min_speed_kn, vc.max_speed_kn, N_SPEEDS)
        entry = {"speeds": speeds.tolist(), "states": {}}
        for state, load in loading_states(vc.cargo).items():
            grid = np.empty((len(BEAUFORT_GRID), len(speeds)))
            for bi, bn in enumerate(BEAUFORT_GRID):
                df = condition_frame(cid, speeds, load, bn)
                ml = model.predict_monotone(df).reshape(len(HEADINGS), -1).mean(axis=0)
                ph = nominal.predict(df).reshape(len(HEADINGS), -1).mean(axis=0)
                grid[bi] = ml / np.maximum(ph, 1e-6)
            entry["states"][state] = np.clip(grid, 0.5, 2.0).round(5).tolist()
        table["classes"][cid] = entry
    return table


def save_surrogate(table: dict, path: Path = SURROGATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(table, fh)


@dataclass
class FuelCorrection:
    """Interpolates the learned correction ratio; identity when no surrogate is loaded."""

    table: dict | None = None

    @classmethod
    def load(cls, path: Path = SURROGATE_PATH) -> FuelCorrection:
        if path.exists():
            with open(path) as fh:
                return cls(json.load(fh))
        return cls(None)

    @property
    def active(self) -> bool:
        return self.table is not None

    def ratio(self, cls_id: str, speed_kn: float, laden: bool, beaufort: float) -> float:
        if self.table is None or cls_id not in self.table["classes"]:
            return 1.0
        entry = self.table["classes"][cls_id]
        grid = np.asarray(entry["states"]["laden" if laden else "return"])
        bns = np.asarray(self.table["beaufort"])
        speeds = np.asarray(entry["speeds"])
        b = float(np.clip(beaufort, bns[0], bns[-1]))
        i = min(int(np.searchsorted(bns, b, side="right") - 1), len(bns) - 2)
        w = (b - bns[i]) / (bns[i + 1] - bns[i])
        row = (1 - w) * grid[i] + w * grid[i + 1]
        return float(np.interp(speed_kn, speeds, row))
