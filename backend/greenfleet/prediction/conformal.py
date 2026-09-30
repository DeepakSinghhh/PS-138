"""Split-conformal prediction intervals (distribution-free coverage guarantee).

Normalised variant: the non-conformity score is the *relative* error |y - yhat| / yhat,
so interval width scales with the predicted fuel rate (a 300 t/day container ship and a
15 t/day bulk carrier get proportionate bands). With n calibration points the interval
``yhat * (1 +/- q)`` has marginal coverage >= 1 - alpha for exchangeable data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ConformalCalibrator:
    alpha: float = 0.10
    q_: float = float("nan")

    def fit(self, y_cal: np.ndarray, p_cal: np.ndarray) -> ConformalCalibrator:
        scores = np.abs(np.asarray(y_cal) - p_cal) / np.maximum(np.abs(p_cal), 1e-9)
        n = len(scores)
        level = min(1.0, np.ceil((n + 1) * (1 - self.alpha)) / n)
        self.q_ = float(np.quantile(scores, level, method="higher"))
        return self

    def interval(self, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        p = np.asarray(p, dtype=float)
        return p * (1 - self.q_), p * (1 + self.q_)

    def evaluate(self, y: np.ndarray, p: np.ndarray) -> dict[str, float]:
        lo, hi = self.interval(p)
        y = np.asarray(y, dtype=float)
        return {
            "target_coverage": 1 - self.alpha,
            "coverage": float(np.mean((y >= lo) & (y <= hi))),
            "mean_width": float(np.mean(hi - lo)),
            "relative_half_width": self.q_,
        }
