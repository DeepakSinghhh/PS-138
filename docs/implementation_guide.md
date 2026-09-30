# Implementation guide

## 1. Requirements
- Python 3.11, Node 20+ (22 used in development), 4 CPU cores and 4 GB RAM recommended.
- No GPU and no quantum hardware needed. The D-Wave export is optional.

## 2. Install and run (local)

```bash
make install        # backend venv + Python deps (uses uv; or: pip install -r backend/requirements.txt)
make install-web    # frontend deps
make data           # build processed datasets (synthetic fleet; real files from data/raw are used when present)
make train          # train Q-PHYS and the optimizer fuel surrogate (~3-5 min); a trained model ships in backend/artifacts
make api            # FastAPI on http://localhost:8000 (docs at /docs)
make web            # React dev server on http://localhost:5173 (proxies /api to :8000)
```

For a single-process demo, run `npm run build` in `frontend/` once. The API then serves the built dashboard at
http://localhost:8000.

**Docker:** `docker compose up --build`, then open http://localhost:8000.

## 3. Tests and benchmarks

```bash
make test           # backend unit/integration tests (physics, regulations, data, quantum core, prediction,
                    # optimizer, MILP vs brute force, QUBO, API)
make smoke          # Playwright end-to-end test against a running API that serves the built dashboard
make bench-quick    # ~45-60 min: prediction + optimization benchmarks -> reports/*.md, reports/figures
make bench-full     # hours: 15 seeds, larger budgets, 200-route scalability
```

## 4. Using real data

Place files under `data/raw/` and re-run `make data && make train` (see `data/raw/README.md`):

| Folder | Content |
|---|---|
| `fuelcast/` | FuelCast parquet/CSV files, one per ship (Hugging Face `krohnedigital/FuelCast`) |
| `mrv/` | EU MRV THETIS export (`.xlsx`/`.csv`) |
| `kaggle_ship_fuel/` | the Kaggle ship fuel CSV |
| `user_fleet/` | your own noon reports or sensor logs |

- **Column matching.** Columns are matched by alias. Add a `columns.yaml` to pin the mapping.
- **Required inputs** (PS Delivery Table): speed, cargo load, weather and vessel type. Engine load, power and rpm columns are excluded as target leakage and listed in `data/processed/data_card.json`.
- **FuelCast** adds benchmark scenario D (real ships) automatically.

## 5. Configuring scenarios

Everything the models use is in `backend/config/*.yaml`, with sources noted inline:

| File | Contents |
|---|---|
| `fuels.yaml` | LCV, emission factors (FuelEU Annex II), methane slip, pilot share, WtT for bio/e/blue pathways; fuel-system families (BSEC, charter premium, cargo-space loss, range) |
| `vessels.yaml` | vessel classes: capacity, DWT/GT, speeds, MCR, drafts, displacement, auxiliary loads, charter rates, availability |
| `ports.yaml` | coordinates, country, shore-power year, bunkering year per fuel |
| `routes_*.yaml` | service networks (liner or tramp, demand, port time, weather, delay model, EU scope, allowed classes) |
| `regulations.yaml` | CII reference lines, dd-vectors, reduction factors; FuelEU targets and penalty; EU ETS phase-in |
| `prices.yaml` | fuel price and carbon price trajectories by year, grid factors, electricity prices |

- **New network**: add `config/routes_<name>.yaml` and register it in `greenfleet.config.NETWORKS`.
- **Ad hoc routes**: upload a CSV in the dashboard (optimizer page) or post it to `/api/routes/parse`.
- **Scenario overrides** (UI or API): year, fuel prices, carbon prices, global levy, allowed fuels, fleet availability,
  Red Sea diversion, monsoon, demand multiplier, extra shore-power ports, on-time threshold, CII minimum rating, FuelEU mode,
  emission cap, objectives (fuel, emissions, cost, schedule risk), extra-ship range, speed discretisation.

## 6. API

Interactive OpenAPI docs are at `/docs`. Typical flow:

```bash
# 1. start an optimization (returns a job id)
curl -s -X POST localhost:8000/api/optimize -H 'Content-Type: application/json' \
  -d '{"scenario": {"network": "india", "year": 2030}, "algorithm": "QMOEA-H", "budget": 6000}'
# 2. follow progress (Server-Sent Events: the Pareto front after each batch of generations)
curl -N localhost:8000/api/jobs/<id>/stream
# 3. fetch the result: Pareto-optimal plans, recommended knee plan, explanation
curl -s localhost:8000/api/jobs/<id>
# 4. inspect / tweak a plan (by genes or a readable plan) and download a report
curl -s -X POST localhost:8000/api/evaluate -H 'Content-Type: application/json' \
  -d '{"scenario": {"network": "india", "year": 2030}, "plan": [{"route_id": "R09", "fuel": "LNG_HP", "extra_ships": 2, "speed_u": 0}]}'
curl -s -X POST localhost:8000/api/report -H 'Content-Type: application/json' -d '{"scenario": {...}, "genes": {...}}' > report.html
```

Other endpoints:

| Endpoint | Purpose |
|---|---|
| `/api/predict` | fuel prediction with a conformal interval and alternative-fuel conversion |
| `/api/model` | model card |
| `/api/robustness` | Monte Carlo robustness of a plan |
| `/api/macc` | marginal abatement cost curve |
| `/api/exact` | exact MILP optimum |
| `/api/qubo` | QUBO + annealing job |
| `/api/timeline` | 2025–2050 pathway job |
| `/api/benchmarks` | benchmark results |

## 7. Python usage

```python
from greenfleet.scenarios.scenario import Scenario, resolve
from greenfleet.optimization.problem import FleetProblem
from greenfleet.optimization.archive import Tracker
from greenfleet.optimization.qmoea import QMOEAH
from greenfleet.scenarios.analysis import knee_point, explain

problem = FleetProblem(resolve(Scenario(network="india", year=2030, red_sea_diversion=True)))
tracker = Tracker(problem, budget=6000)
QMOEAH(problem, seed=0).run(tracker)
front = tracker.archive                      # genes, objectives F (fuel, emissions, cost), violations CV
k = knee_point(front.F)
print(explain(problem, front.genes, k)["summary"])
plan = problem.describe(front.genes, k)      # per-route class, ships, speed, fuel, OPS, CII, costs
```

**Running on D-Wave hardware** (optional; needs Leap credentials):

```python
from greenfleet.optimization import qubo as QB
from greenfleet.optimization.options import enumerate_options
fq = QB.build_qubo(problem, enumerate_options(problem, 5), {"emissions": 0.5, "cost": 0.5})
bqm = QB.export_bqm(fq)
# from dwave.system import DWaveSampler, EmbeddingComposite
# sampleset = EmbeddingComposite(DWaveSampler()).sample(bqm, num_reads=1000)
```

## 8. Extending

| Task | How |
|---|---|
| **New fuel / pathway** | add it to `fuels.yaml` (family, LCV, Cf, WtT, slip, pilot share), a price in `prices.yaml`, and bunkering years in `ports.yaml` |
| **New vessel class** | add it to `vessels.yaml` and list it in the routes' `classes`; run `make train` to extend the fuel surrogate |
| **New regulation** | put the parameters in `regulations.yaml`, add a calculator in `greenfleet/regulations/`, and wire it into `FleetProblem.evaluate` as an objective term or constraint violation |
| **New optimizer** | implement `run(tracker, callback)` over `Genes` (or random keys via `problem.decode_keys`) and register it in `api/service.py::ALGORITHMS` and `benchmark/optimization_bench.py::ALGORITHMS` |

## 9. Repository map

```
backend/greenfleet/
  config.py                 YAML loading, sea distances (searoute)
  physics/                  IMO GHG4 power, Kwon weather, SFOC; WtW accounting (FuelEU method)
  regulations/              CII, FuelEU (pooling, RFNBO reward, penalty), EU ETS
  data/                     canonical schema, dataset loaders, physics-informed synthetic fleet
  quantum/                  qudit registers, QPSO, QIEA, path-integral SQA, QUBO tools
  classical/                PSO, GA, random search, binary GA
  prediction/               MPS tensor network, Q-PHYS hybrid, tuners, conformal, surrogate, training
  optimization/             fleet problem, QMOEA-H(+ablations), MOPSO, pymoo baselines, MILP, QUBO, metrics
  scenarios/                scenario resolution, large-scale instances, knee/explain/robustness/MACC/timeline
  benchmark/                prediction & optimization benchmark harness + report writers
  api/                      FastAPI app, jobs/SSE, service layer, HTML report
backend/config/             every number the models use, with sources
frontend/src/               React dashboard (pages, components, api client, theme)
docs/                       problem statement, deliverables, math model, algorithms, data & model cards
reports/                    benchmark reports, figures, dashboard screenshots
```
