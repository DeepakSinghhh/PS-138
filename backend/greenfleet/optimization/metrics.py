"""Multi-objective quality indicators (computed on normalised objectives)."""

from __future__ import annotations

import numpy as np

from greenfleet.optimization.archive import nondominated_mask


def normaliser(fronts: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    allF = np.vstack([f for f in fronts if len(f)])
    allF = allF[nondominated_mask(allF)]
    ideal, nadir = allF.min(axis=0), allF.max(axis=0)
    nadir = np.where(nadir - ideal < 1e-12, ideal + 1.0, nadir)
    return ideal, nadir


def normalise(F: np.ndarray, ideal: np.ndarray, nadir: np.ndarray) -> np.ndarray:
    return (F - ideal) / (nadir - ideal)


def hypervolume(F: np.ndarray, ideal: np.ndarray, nadir: np.ndarray, ref: float = 1.1) -> float:
    """Exact hypervolume of the normalised front w.r.t. reference point (ref, ..., ref)."""
    if len(F) == 0:
        return 0.0
    from pymoo.indicators.hv import HV

    Z = normalise(F, ideal, nadir)
    Z = Z[np.all(Z < ref, axis=1)]
    if len(Z) == 0:
        return 0.0
    return float(HV(ref_point=np.full(F.shape[1], ref))(Z))


def igd_plus(F: np.ndarray, reference: np.ndarray, ideal: np.ndarray, nadir: np.ndarray) -> float:
    if len(F) == 0:
        return float("inf")
    from pymoo.indicators.igd_plus import IGDPlus

    return float(IGDPlus(normalise(reference, ideal, nadir))(normalise(F, ideal, nadir)))


def spacing(F: np.ndarray, ideal: np.ndarray, nadir: np.ndarray) -> float:
    """Schott's spacing (lower = more uniform spread)."""
    if len(F) < 3:
        return float("nan")
    Z = normalise(F, ideal, nadir)
    d = np.abs(Z[:, None, :] - Z[None, :, :]).sum(axis=2)
    np.fill_diagonal(d, np.inf)
    nn = d.min(axis=1)
    return float(np.sqrt(np.mean((nn - nn.mean()) ** 2)))


def reference_front(fronts: list[np.ndarray]) -> np.ndarray:
    allF = np.vstack([f for f in fronts if len(f)])
    return allF[nondominated_mask(allF)]
