"""Q-PHYS: the quantum-inspired, physics-informed fuel-consumption model.

Pipeline
    1. Physics prior ``F_phys``: per-ship grey-box physics where the ship has history,
       class-calibrated nominal physics (IMO GHG4 + Kwon) for ships never seen before.
    2. QIEA selects the optional features (speed, load, weather and vessel type are kept).
    3. **Monotone physics-informed booster** ``G``: LightGBM on log(fuel) with log(F_phys) as an
       input, hyperparameters tuned by QPSO, and monotone constraints in speed, load, draft,
       hull age, waves and head wind. Because every constrained input (including the prior)
       is non-decreasing in speed, ``exp(G)`` is *certified* non-decreasing in speed: the
       optimizer cannot exploit spurious dips. This variant is ``Q-PHYS-M``.
    4. **MPS tensor network** learns the log correction log(fuel / F_phys) (DMRG sweeps,
       QPSO-tuned bond dimension / local dimension / ridge).
    5. Blend on validation data: ``log yhat = a * G + (1 - a) * (log F_phys + MPS)``.
    6. Split-conformal calibration gives 90 % prediction intervals.

Two heads (digital twin vs. fleet model)
    * the **ship head** is trained with each ship's own calibrated prior and is used for ships
      that have history (the operator's digital twin);
    * the **fleet head** is trained with the class-level prior only, so it knows how much to
      trust physics for a ship it has never seen. It is fitted on ~80 % of the ships and its
      conformal interval is calibrated on the remaining ships, so the coverage claim holds for
      genuinely new vessels. Rows are routed automatically by ``ship_id``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd

from greenfleet.data.schema import MONOTONE
from greenfleet.prediction.conformal import ConformalCalibrator
from greenfleet.prediction.feature_selection import select_features
from greenfleet.prediction.mps import MPSRegressor
from greenfleet.prediction.physics_model import CalibratedPrior
from greenfleet.prediction.tuning import LGBM_SPACE, MPS_SPACE, tune

LOCAL_DIMS = (3, 5, 7)


@dataclass
class _Head:
    gbm: lgb.LGBMRegressor
    mps: MPSRegressor | None
    blend: float
    conformal: ConformalCalibrator
    feats: list[str]          # MPS inputs (booster inputs are ["log_prior"] + feats)

    @property
    def gbm_cols(self) -> list[str]:
        return ["log_prior"] + self.feats


@dataclass
class QPhys:
    features: list[str]
    use_mps: bool = True
    tune_budget: int = 20
    select_budget: int = 40
    select: bool = True
    seed: int = 0
    alpha: float = 0.10
    fleet_cal_share: float = 0.2
    name: str = "Q-PHYS (quantum-inspired hybrid)"
    report: dict = field(default_factory=dict)

    # -------------------------------------------------------------- helpers
    def _with_prior(self, df: pd.DataFrame, prior: CalibratedPrior, use_ship: bool) -> pd.DataFrame:
        out = df.copy()
        out["log_prior"] = np.log(np.maximum(prior.predict(df, use_ship=use_ship), 1e-3))
        return out

    def _matrix(self, df: pd.DataFrame, cols: list[str]) -> np.ndarray:
        X = df[cols].to_numpy(dtype=float)
        return np.where(np.isnan(X), self.fill_[cols].to_numpy(), X)

    def _fit_gbm(self, params, Xtr, ytr, Xva, yva, cols: list[str]) -> lgb.LGBMRegressor:
        mono = [1 if c == "log_prior" else MONOTONE.get(c, 0) for c in cols]
        model = lgb.LGBMRegressor(
            n_estimators=800, verbose=-1, n_jobs=4, random_state=self.seed,
            monotone_constraints=mono, monotone_constraints_method="advanced", subsample_freq=1, **params,
        )
        model.fit(Xtr, ytr, eval_X=(Xva,), eval_y=(yva,), callbacks=[lgb.early_stopping(50, verbose=False)])
        return model

    def _mps(self, p: dict, sweeps: int, max_train: int) -> MPSRegressor:
        return MPSRegressor(bond_dim=p["bond_dim"], local_dim=LOCAL_DIMS[p["local_dim_idx"]], ridge=p["ridge"],
                            sweeps=sweeps, max_train=max_train, seed=self.seed)

    def _fit_head(self, tr: pd.DataFrame, ytr: np.ndarray, va: pd.DataFrame, yva: np.ndarray,
                  cal: pd.DataFrame, ycal: np.ndarray, feats: list[str],
                  blend_df: pd.DataFrame | None = None, blend_y: np.ndarray | None = None,
                  fixed_blend: float | None = None) -> _Head:
        """Fit booster (+ MPS); the blend weight is chosen on ``blend_df`` (default: validation)."""
        cols = ["log_prior"] + feats
        Xtr, Xva = self._matrix(tr, cols), self._matrix(va, cols)
        gbm = self._fit_gbm(self.gbm_params_, Xtr, np.log(ytr), Xva, np.log(yva), cols)
        head = _Head(gbm, None, 1.0, ConformalCalibrator(alpha=self.alpha), feats)
        if self.use_mps:
            Mtr, Mva = self._matrix(tr, feats), self._matrix(va, feats)
            rtr = np.log(ytr) - tr["log_prior"].to_numpy()
            rva = np.log(yva) - va["log_prior"].to_numpy()
            head.mps = self._mps(self.mps_params_, 4, 20000).fit(Mtr, rtr, Mva, rva)
            if fixed_blend is not None:
                head.blend = fixed_blend
            else:
                bd, by = (va, yva) if blend_df is None else (blend_df, blend_y)
                g = gbm.predict(self._matrix(bd, cols))
                m = bd["log_prior"].to_numpy() + head.mps.predict(self._matrix(bd, feats))
                grid = np.linspace(0, 1, 21)
                maes = [np.mean(np.abs(np.exp(a * g + (1 - a) * m) - by)) for a in grid]
                head.blend = float(grid[int(np.argmin(maes))])
        head.conformal.fit(ycal, self._head_predict(head, cal))
        return head

    def _head_predict(self, head: _Head, d: pd.DataFrame, monotone: bool = False) -> np.ndarray:
        g = head.gbm.predict(self._matrix(d, head.gbm_cols))
        if monotone or head.mps is None or head.blend >= 1.0:
            return np.exp(g)
        m = d["log_prior"].to_numpy() + head.mps.predict(self._matrix(d, head.feats))
        return np.exp(head.blend * g + (1 - head.blend) * m)

    # -------------------------------------------------------------- fit
    def fit(self, train: pd.DataFrame, y: np.ndarray, val: pd.DataFrame, y_val: np.ndarray,
            cal: pd.DataFrame | None = None, y_cal: np.ndarray | None = None) -> QPhys:
        t0 = time.perf_counter()
        y, y_val = np.asarray(y, float), np.asarray(y_val, float)
        if cal is None or y_cal is None:
            cal, y_cal = val, y_val
        y_cal = np.asarray(y_cal, float)
        self.prior_ = CalibratedPrior().fit(train, y)
        tr, va, ca = (self._with_prior(d, self.prior_, True) for d in (train, val, cal))
        self.fill_ = tr[self.features + ["log_prior"]].median(numeric_only=True).fillna(0.0)

        # 1) QIEA feature selection (mandatory PS inputs always kept)
        if self.select:
            sel = select_features("QIEA", tr, va, self.features, budget=self.select_budget,
                                  seed=self.seed, extra=["log_prior"])
            self.selected_ = sel.features
            self.report["feature_selection"] = {"selected": sel.features, "val_score": sel.score,
                                                "evaluations": sel.evaluations}
        else:
            self.selected_ = list(self.features)
        self.gbm_cols_ = ["log_prior"] + self.selected_

        # 2) QPSO tuning of the monotone booster (on the ship head's data)
        Xtr, Xva = self._matrix(tr, self.gbm_cols_), self._matrix(va, self.gbm_cols_)
        ltr, lva = np.log(y), np.log(y_val)

        def gbm_objective(params: dict) -> float:
            m = self._fit_gbm(params, Xtr, ltr, Xva, lva, self.gbm_cols_)
            return float(np.mean(np.abs(np.exp(m.predict(Xva)) - y_val)))

        res = tune("QPSO", LGBM_SPACE, gbm_objective, budget=self.tune_budget, seed=self.seed)
        self.gbm_params_ = res.best_params
        self.report["gbm_tuning"] = {"best_params": res.best_params, "val_mae": res.best_score, "history": res.history}

        # 3) QPSO tuning of the MPS tensor network on the log physics correction
        if self.use_mps:
            Mtr, Mva = self._matrix(tr, self.selected_), self._matrix(va, self.selected_)
            rtr = ltr - tr["log_prior"].to_numpy()
            prior_va = va["log_prior"].to_numpy()

            def mps_objective(params: dict) -> float:
                m = self._mps(params, 3, 12000).fit(Mtr, rtr)
                return float(np.mean(np.abs(np.exp(prior_va + m.predict(Mva)) - y_val)))

            mres = tune("QPSO", MPS_SPACE, mps_objective, budget=max(8, self.tune_budget // 2), seed=self.seed,
                        pop_size=4)
            self.mps_params_ = mres.best_params
            self.report["mps_tuning"] = {"val_mae": mres.best_score}

        # 4) ship head (digital twin for ships with history)
        self.ship_head_ = self._fit_head(tr, y, va, y_val, ca, y_cal, self.selected_)
        if self.use_mps:
            mps = self.ship_head_.mps
            self.report["mps"] = {"best_params": {**self.mps_params_, "local_dim": LOCAL_DIMS[self.mps_params_["local_dim_idx"]]},
                                  "n_params": mps.n_params, "entanglement_entropy": mps.entanglement_entropy(),
                                  "bond_features": [f"{a} | {b}" for a, b in zip(self.selected_[:-1], self.selected_[1:])],
                                  "sweeps": mps.history}
            self.report["blend_weight_gbm"] = self.ship_head_.blend

        # 5) fleet head (new ships): trained without some ships, calibrated on them
        ships = np.array(sorted(train["ship_id"].unique())) if "ship_id" in train else np.array([])
        rng = np.random.default_rng(self.seed)
        n_cal = int(round(self.fleet_cal_share * len(ships))) if len(ships) >= 4 else 0
        held = set(rng.choice(ships, n_cal, replace=False)) if n_cal else set()
        def in_fit(d):  # noqa: E306
            return ~d["ship_id"].isin(held).to_numpy() if "ship_id" in d else np.ones(len(d), bool)
        mtr, mva = in_fit(train), in_fit(val)
        fleet_prior = CalibratedPrior().fit(train[mtr], y[mtr])
        ftr, fva = (self._with_prior(d, fleet_prior, False) for d in (train[mtr], val[mva]))
        if held:
            cal_rows = pd.concat([train[~mtr], val[~mva], cal[~in_fit(cal)]])
            fca = self._with_prior(cal_rows, fleet_prior, False)
            yca = fca["fuel_tpd"].to_numpy() if "fuel_tpd" in fca else None
        else:
            fca, yca = fva, y_val[mva]
        # the fleet head keeps every candidate feature: vessel particulars matter for new ships
        # even when the ship head (with per-ship priors) finds them redundant
        fleet_feats = list(self.features)
        yca = np.asarray(yca, float)
        calib_head = self._fit_head(ftr, y[mtr], fva, y_val[mva], fca, yca, fleet_feats, blend_df=fca, blend_y=yca)
        if held:
            # refit on every ship and keep the interval width and blend weight measured on the
            # held-out ships (cross-conformal style: slightly conservative)
            self.fleet_prior_ = CalibratedPrior().fit(train, y)
            ftr_all, fva_all = (self._with_prior(d, self.fleet_prior_, False) for d in (train, val))
            self.fleet_head_ = self._fit_head(ftr_all, y, fva_all, y_val, fva_all, y_val, fleet_feats,
                                              fixed_blend=calib_head.blend)
            self.fleet_head_.conformal = calib_head.conformal
        else:
            self.fleet_prior_, self.fleet_head_ = fleet_prior, calib_head
        self.report["fleet_head"] = {"calibration_ships": sorted(str(s) for s in held),
                                     "blend_weight_gbm": self.fleet_head_.blend,
                                     "conformal_half_width": self.fleet_head_.conformal.q_}
        self.report["fit_seconds"] = time.perf_counter() - t0
        return self

    # -------------------------------------------------------------- predict
    def _route(self, df: pd.DataFrame, monotone: bool = False, interval: bool = False):
        seen = self.prior_.seen(df)
        out = np.empty(len(df))
        lo, hi = np.empty(len(df)), np.empty(len(df))
        for mask, head, prior, use_ship in ((seen, self.ship_head_, self.prior_, True),
                                            (~seen, self.fleet_head_, self.fleet_prior_, False)):
            if mask.any():
                d = self._with_prior(df[mask], prior, use_ship)
                p = self._head_predict(head, d, monotone)
                out[mask] = p
                if interval:
                    lo[mask], hi[mask] = head.conformal.interval(p)
        return (out, lo, hi) if interval else out

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self._route(df)

    def predict_monotone(self, df: pd.DataFrame) -> np.ndarray:
        """Q-PHYS-M: certified non-decreasing in speed (used as the optimizer surrogate)."""
        return self._route(df, monotone=True)

    def predict_interval(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self._route(df, interval=True)

    def interval_coverage(self, df: pd.DataFrame, y: np.ndarray) -> dict[str, float]:
        p, lo, hi = self.predict_interval(df)
        y = np.asarray(y, float)
        return {"target_coverage": 1 - self.alpha, "coverage": float(np.mean((y >= lo) & (y <= hi))),
                "mean_width": float(np.mean(hi - lo)),
                "relative_half_width": float(np.mean((hi - lo) / np.maximum(2 * p, 1e-9)))}

    @property
    def conformal_(self) -> ConformalCalibrator:
        return self.ship_head_.conformal

    @property
    def blend_(self) -> float:
        return self.ship_head_.blend

    def feature_importance(self, df: pd.DataFrame, max_rows: int = 3000) -> dict[str, float]:
        """Mean |SHAP| of the ship-head booster (LightGBM's exact TreeSHAP via pred_contrib)."""
        d = self._with_prior(df.sample(min(len(df), max_rows), random_state=0), self.prior_, True)
        cols = self.ship_head_.gbm_cols
        contrib = self.ship_head_.gbm.predict(self._matrix(d, cols), pred_contrib=True)[:, :-1]
        imp = np.abs(contrib).mean(axis=0)
        return dict(sorted(zip(cols, map(float, imp)), key=lambda kv: -kv[1]))
