# Q-GreenFleet

**Quantum-inspired fuel consumption prediction and green fleet optimization.**
Built for Smart India Hackathon 2026, problem statement **26138** (Egreen Quanta · Clean & Green Technology).

Q-GreenFleet predicts ship fuel consumption with a quantum-inspired hybrid model, then optimizes a whole fleet's
deployment for every service:
- vessel type and capacity, fleet size and cruising speed;
- fuel pathway: HFO, VLSFO, MGO, LNG, bio-LNG, grey/bio/e-methanol, grey/blue/e-ammonia, grey/e-hydrogen;
- shore power at berth.

It minimises **fuel, well-to-wake greenhouse-gas emissions and cost** while meeting cargo demand, schedule
reliability, fleet availability, IMO CII and FuelEU Maritime. Every result is benchmarked against conventional methods
and against an exact MILP optimum.

![Fleet optimizer](reports/screenshots/02_optimizer.png)

## What is inside

| PS deliverable | What we built |
|---|---|
| **1. Fuel consumption prediction model** | **Q-PHYS**: physics prior (IMO Fourth GHG Study power model + Kwon weather + SFOC curve) + **Matrix-Product-State tensor network** (spin-coherent qudit feature encoding, DMRG-style training) + QPSO-tuned *certified-monotone* booster + QIEA feature selection + split-conformal intervals. Inputs are exactly the PS's: **speed, load, weather, vessel type**. |
| **2. Mathematical optimization formulation** | Multi-objective MINLP: per-route vessel class (type & capacity), fleet size, speed, fuel pathway, shore power. Objectives min fuel / min WtW emissions / min cost (+ optional schedule risk). Constraints: demand, weekly frequency, on-time probability, fleet availability, CII ≥ C, FuelEU pooling, emission cap. See [docs/math_model.md](docs/math_model.md). |
| **3. Quantum-inspired optimization algorithm** | **QMOEA-H**: qudit registers per route, superposition crossover, quantum memory register, δ-potential-well (QPSO) speed moves, Hadamard reset, elitist Pareto survival. Plus a **QUBO** formulation solved by a from-scratch **path-integral simulated quantum annealer** and exported unchanged for D-Wave. See [docs/algorithms.md](docs/algorithms.md). |
| **4. Software platform / DSS** | FastAPI + React dashboard: live Pareto front streamed over SSE, fleet-allocation maps, emission profiles, scenario lab (2025–2050, fuel and carbon prices, Red Sea closure, monsoon, CSV upload), compliance views, downloadable decision report. |
| **5. Demonstration** | India coastal & near-sea network (12 services, Sagarmala / Harit Sagar / green-hydrogen ports), EU FuelEU/ETS network, and a **synthetic 100-route, 750-ship network**. Benchmarks in [reports/](reports/). Implementation guide in [docs/implementation_guide.md](docs/implementation_guide.md). |

Deliverable-by-deliverable tracking: [docs/deliverables.md](docs/deliverables.md).

## Results at a glance

<!-- RESULTS -->

Full tables, statistical tests and figures: [reports/prediction_benchmark.md](reports/prediction_benchmark.md) and
[reports/optimization_benchmark.md](reports/optimization_benchmark.md).

## Quick start

```bash
make install && make install-web   # Python 3.11 venv + Node deps
make api                           # http://localhost:8000  (API docs at /docs)
make web                           # http://localhost:5173  (dashboard)
```

Or run everything in one container: `docker compose up --build`, then open http://localhost:8000.

A trained model ships in `backend/artifacts/`. Retrain with `make data && make train`. Run `make test` for the test
suite, and `make bench-quick` to regenerate the benchmarks.

## Architecture

```
 data/raw (FuelCast · EU MRV · Kaggle · your logs)  ──►  canonical schema (speed, load, weather, vessel type)
            │  (physics-informed synthetic fleet when real data is absent)
            ▼
 Physics & emissions engine ── IMO GHG4 power · Kwon weather · SFOC · FuelEU WtW factors · CII · FuelEU · EU ETS
            │
            ▼
 Q-PHYS prediction ── calibrated physics prior ▸ QIEA feature selection ▸ QPSO-tuned monotone booster
            │          ▸ MPS tensor network ▸ conformal intervals ▸ ship head / fleet head
            ▼ (certified-monotone fuel surrogate)
 Fleet optimization ── vectorised fleet model (~55k plans/s) ▸ QMOEA-H │ MOQPSO │ NSGA-II/III │ SPEA2 │ MOEA/D │ MOPSO
            │           ▸ exact MILP (optimality gaps) ▸ QUBO + simulated quantum annealing (D-Wave-ready)
            ▼
 Decision analytics ── knee point · plain-language explanation · Monte Carlo robustness · MACC · 2025–2050 pathway
            ▼
 FastAPI (jobs + SSE) ──► React dashboard ──► printable decision report
```

## Three-minute demo script

1. **Overview**: the India network on the map. Current practice emits about 2.3 Mt CO₂e a year and fails CII on 11 of 12 services in 2030.
2. **Fleet optimizer**: press *Run optimization*. The Pareto front streams in live, far from the grey reference plans. Click
   *Recommended*: roughly −60 % GHG, −50 % fuel and −20 % cost, all constraints satisfied. Read the explanation, hover the map,
   then click *Minimum emissions* to show the ammonia/methanol extreme. Download the decision report.
3. **Scenario levers**: tick *Red Sea closed*. The Europe service reroutes via the Cape (6,348 → 11,027 nm); re-run and compare.
4. **Fuel prediction**: move the speed and wave sliders. The conformal band tracks the prediction, which sits next to the
   physics-only curve. Switch the fuel system to e-ammonia. Show the tensor-network entanglement chart.
5. **Fuel & policy lab**: run the 2025→2050 pathway (conventional → LNG → e-ammonia), then the MACC. Anneal the QUBO and
   compare the gap to the exact MILP.
6. **Benchmarks**: QMOEA-H vs NSGA-II/III, MOPSO and others (hypervolume, convergence, MILP gaps, scalability to 100 routes).

## Honest notes
- Everything runs on classical hardware. "Quantum-inspired" names the algorithms' mechanics: tensor networks,
  superposition/measurement, tunnelling, annealing. It is not a speed-up claim.
- The build environment could not reach Hugging Face, Kaggle or EMSA, so prediction results use **physics-informed synthetic
  telemetry**. Loaders for FuelCast, EU MRV and the Kaggle set pick up real files from `data/raw/` automatically. See
  [docs/data_card.md](docs/data_card.md).
- Alternative-fuel prices, bunkering-availability years and e-fuel well-to-tank factors are scenario assumptions (cited
  and editable in `backend/config/`).
- QMOEA-H was tuned on the India instance. The EU and synthetic networks test generalisation, and the benchmark reports
  where classical methods do better.

## Documentation
[Problem statement](docs/problem_statement.md) · [Deliverables](docs/deliverables.md) · [Mathematical model](docs/math_model.md) ·
[Algorithms](docs/algorithms.md) · [Implementation guide](docs/implementation_guide.md) · [Data card](docs/data_card.md) ·
[Model card](docs/model_card.md)
