# Model card: Q-PHYS fuel-consumption model

| | |
|---|---|
| **Task** | Predict ship fuel consumption (t/day) from speed, cargo load, weather and vessel type |
| **Type** | Physics prior + QPSO-tuned monotone gradient boosting + Matrix-Product-State tensor network (quantum-inspired), with split-conformal intervals |
| **Artifacts** | `backend/artifacts/qphys.joblib`, `qphys_meta.json` (metrics, selected features, SHAP importance, MPS entanglement), `fuel_surrogate.json` |
| **Training data** | Physics-informed synthetic telemetry (see [data_card.md](data_card.md)); FuelCast is supported |
| **Split** | Per ship, forward in time: 60 % train, 15 % validation, 10 % conformal calibration, 15 % test |

## Intended use
- Fuel and emission estimates for voyage and fleet planning.
- The optimizer's fuel surrogate, via the certified-monotone variant Q-PHYS-M.
- Decision support only; never for direct engine control.

## Performance (quick benchmark; full tables in `reports/prediction_benchmark.md`)

| Scenario | Q-PHYS MAPE | Best conventional baseline |
|---|---|---|
| Known ships, future period | ≈ 3.1–3.3 % | grey-box physics ≈ 3.4 %, LightGBM ≈ 5.3 % |
| Unseen ships of known classes | ≈ 5.6 % | LightGBM ≈ 6.0 % |
| Unseen vessel classes | ≈ 6.0 % | physics ≈ 7.9 %; pure ML collapses (LightGBM ≈ 35 %) |

Paired Wilcoxon signed-rank tests on per-ship errors are reported for every scenario.

## Uncertainty
- **Split-conformal 90 % intervals** on relative error. Coverage on known ships' future data is about 0.89 against the 0.90 target; the small shortfall comes from time drift (hull fouling).
- **New ships** are served by the fleet head, which is calibrated on held-out ships. Coverage there is conservative (0.98–0.99), with wide intervals (±19–25 %).

## Guarantees and design choices
- **Monotonicity**: Q-PHYS-M is non-decreasing in speed by construction. The booster has monotone constraints on every speed-dependent input, including the physics prior, and the prior's basis functions are non-decreasing in speed. This is unit-tested with speed sweeps.
- **Mandatory inputs**: speed, load, weather and vessel type are never removed by feature selection.

## Limitations
- Accuracy numbers are on synthetic data until real telemetry is supplied.
- Alternative-fuel consumption is derived by energy equivalence and fuel-system efficiency.
- Weather is summarised by wind, waves and current at the reporting resolution; swell/wind-sea separation is not modelled explicitly.
