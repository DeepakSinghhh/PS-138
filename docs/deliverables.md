# Deliverables tracker

How Q-GreenFleet answers each row of the official Delivery Table
(see [problem_statement.md](problem_statement.md)). Status is updated as the build progresses.

| # | Deliverable | Required components / metrics | Implementation | Status |
|---|---|---|---|---|
| 1 | **Fuel Consumption Prediction Model** | Input features: **speed, load, weather, vessel type**; prediction accuracy; statistical models | `backend/greenfleet/data/schema.py` (canonical inputs `speed_kn`, `load_ratio`, wind/wave/current, `vessel_type` one-hot), `backend/greenfleet/data/loaders.py` (FuelCast, EU MRV, Kaggle, operator data; engine-load/power excluded as leakage), `backend/greenfleet/prediction/` (Q-PHYS: physics prior + Matrix-Product-State tensor-network regressor + QPSO-tuned monotone GBM + QIEA feature selection + conformal intervals). Metrics: MAE, RMSE, MAPE, R², Wilcoxon tests, conformal coverage. | ✅ Done |
| 2 | **Mathematical Optimization Formulation** | Decision variables: vessel mix, capacity, speed, fuel type; objectives: **min fuel, min emissions, min cost**; constraints: cargo demand, schedule, emission limits | `backend/greenfleet/optimization/problem.py`, `docs/math_model.md`. Per route: vessel class (type and capacity), fleet size, speed, fuel/pathway, shore power. Objectives: total fuel energy, WtW GHG, annual cost; optional schedule risk. Constraints: demand throughput, weekly frequency and on-time probability, fleet availability, fuel availability and range, CII ≥ C, FuelEU intensity (with pooling), optional fleet emission cap. | ✅ Done |
| 3 | **Quantum-Inspired Optimization Algorithm** | Quantum optimization or equivalent; encoding scheme for fleet decisions; quantum update mechanisms | `backend/greenfleet/quantum/` (qudit registers with rotation/NOT/Hadamard gates, QPSO δ-potential well, QIEA, path-integral SQA, QUBO/D-Wave export). `backend/greenfleet/optimization/qmoea.py` (QMOEA-H hybrid multi-objective engine). Documented in `docs/algorithms.md`. | ✅ Done |
| 4 | **Software Platform / Decision Support System** | UI or API; scenario simulation; visualisation of fleet allocation and emission profiles; report generation | FastAPI (`backend/greenfleet/api`) + React dashboard (`frontend/`): allocation map/table, emission profiles by route/fuel/year, scenario lab (fuel prices, carbon price, year 2025-2050, fuel availability, Red Sea diversion), live Pareto streaming, and a downloadable decision report (`/api/report`). | ✅ Done |
| 5 | **Demonstration** | Complete technical and real or simulated **large-scale** scenario; algorithm details; implementation guide; experimental results | India coastal/near-sea case study (12 routes), EU FuelEU/ETS case study, and a large-scale synthetic scenario (100+ routes, 500+ ships). `docs/implementation_guide.md`, `docs/algorithms.md`, `reports/prediction_benchmark.md`, `reports/optimization_benchmark.md`. | ✅ Done |

## Benchmark commitments (PS objective 5)
| Dimension | Prediction | Optimization |
|---|---|---|
| Accuracy / solution quality | MAE, RMSE, MAPE, R² vs polynomial-speed, physics, Ridge, RF, LightGBM, MLP | Hypervolume, IGD+, spread, feasibility; optimality gap vs exact MILP on small instances |
| Convergence speed | Tuner best-so-far vs evaluations (QPSO vs PSO, GA, random, TPE, grid) | NFE to reach 95 % of reference hypervolume |
| Scalability | Training / inference time vs rows | Runtime and quality vs 5 → 100+ routes |
| Statistics | Wilcoxon signed-rank on per-fold errors | 30 seeds, Mann-Whitney U / Friedman tests |
