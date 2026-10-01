<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/q-greenfleet-logo-white.svg">
    <img src="docs/brand/q-greenfleet-logo.svg" alt="Q-GreenFleet" height="52">
  </picture>
</h1>

**Quantum-inspired fuel consumption prediction and green fleet optimization.**
Built for Smart India Hackathon 2026, problem statement **26138** (Egreen Quanta · Clean & Green Technology).

**Live demo: <https://q-greenfleet.onrender.com>**. It is on free hosting, so the first visit after a quiet spell can take
about a minute to wake up. Press *Take the 2-minute tour* on the first page for a guided walk through every deliverable.

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
| **3. Quantum-inspired optimization algorithm** | **QMOEA-H**: qudit registers per route, superposition crossover, quantum memory register, δ-potential-well (QPSO) speed moves, route-wise merge, Hadamard reset, elitist Pareto survival. Plus a **QUBO** formulation solved by a from-scratch **path-integral simulated quantum annealer** and exported unchanged for D-Wave, and a gate-model **QAOA** circuit (12 qubits, one-hot-preserving XY mixer) trained on a fleet sub-problem and exported as **OpenQASM 2.0** (verified in Qiskit). See [docs/algorithms.md](docs/algorithms.md). |
| **4. Software platform / DSS** | FastAPI + React dashboard: live Pareto front streamed over SSE, fleet-allocation maps, emission profiles, scenario lab (2025–2050, fuel and carbon prices, Red Sea closure, monsoon, CSV upload), compliance views, downloadable decision report, and a guided tour. |
| **5. Demonstration** | India coastal & near-sea network (12 services, Sagarmala / Harit Sagar / green-hydrogen ports), EU FuelEU/ETS network, and **MILP-certified synthetic networks of up to 100 routes / 1,250 ships**. Benchmarks in [reports/](reports/). Implementation guide in [docs/implementation_guide.md](docs/implementation_guide.md). |

Deliverable-by-deliverable tracking: [docs/deliverables.md](docs/deliverables.md).

**Logo.** The mark is a ship's load-line disc (the Plimsoll mark painted on every hull) with a waterline through it:
staying within limits, which is what the optimizer does with emissions. SVG and PNG files, for light and dark
backgrounds, are in [docs/brand/](docs/brand/).

## Results at a glance

**Prediction** (held-out test data; the first three rows use the physics-informed synthetic fleet of 20 ships and 10
vessel classes, the last row uses real ship data):

| Scenario | Q-PHYS (ours) | Best conventional baseline | Notes |
|---|---|---|---|
| Known ships, future period | **3.29 % MAPE** | grey-box physics 3.41 %, LightGBM 5.28 % | Wilcoxon p ≤ 0.001 vs every baseline (better on 17–20 of 20 ships) |
| Unseen ships of known classes | **5.64 %** | LightGBM 5.98 % | lead over LightGBM not significant (p = 0.35) |
| Unseen vessel classes | **6.01 %** | physics 7.85 %; LightGBM 34.8 % | physics prior lets the hybrid extrapolate where pure ML fails |
| **Real ships: FuelCast** (2 cruise ships + 1 offshore vessel, 86,757 samples, future period) | **7.28 %** (Q-PHYS-M); 9.83 % (Q-PHYS) | calibrated physics 9.25 %; polynomial speed 10.1 %; LightGBM 11.6 % | the certified-monotone variant is best on every metric (MAE 4.8 t/day, R² 0.966); the standard variant is about level with physics |

- **Uncertainty**: 90 % conformal intervals cover 0.89 of known-ship data; for brand-new ships they are conservative (0.98–0.998).
- **Tuning**: at an equal budget, QPSO found the best hyperparameters (validation MAE 1.207, vs PSO 1.211, TPE 1.230, random 1.246). This is a single seed.
- **Vessel library vs EU MRV** (23,009 real ship-years, 2023–2024): for each class, ships of the same type and cargo size
  are compared at their median speed. The class model gives 0.57–0.93 × the real median fuel per n mile and lies
  inside the p10–p90 band for 6 of 10 classes. It is close for the larger classes and clearly low for the smallest
  (feeder, Handysize, MR tanker), which are the first candidates for recalibration. Details:
  [reports/mrv_validation.md](reports/mrv_validation.md).

**Fleet optimization** (8,000 plan evaluations per run, 10 seeds; hypervolume, higher is better):

| Instance | QMOEA-H (ours) | MOPSO | NSGA-III | NSGA-II | Lowest-GHG plan found (ours vs best baseline) |
|---|---|---|---|---|---|
| India 2030 (12 services, tuning instance) | **0.871** ± 0.006 | 0.562 | 0.338 | 0.135 | **656 kt** vs 743 kt |
| EU 2030 (6 services) | **0.882** ± 0.006 | 0.779 | 0.746 | 0.745 | **198 kt** vs 249 kt |
| Tight 100-route network (1,251 ships, MILP-certified feasible) | **feasible 5/5**, HV 0.66 | feasible 3/5 | never feasible | never feasible | |

Mann-Whitney U: QMOEA-H's hypervolume is higher than every other algorithm's on India and EU, p < 0.001 in each
comparison, including its own ablation without the route-wise merge (0.640 and 0.825). Friedman p ≈ 10⁻¹³ on both.

**Against the exact optimum** (India 2030, speeds discretised, MILP solved in about 1.5 s):

| Algorithm | Fuel gap | GHG gap | Cost gap |
|---|---|---|---|
| **QMOEA-H** | **0.02 %** | **0.8 %** | **0.8 %** |
| MOPSO | 1.0 % | 14.8 % | 4.9 % |
| NSGA-III | 6.7 % | 15.8 % | 11.3 % |

**QUBO + simulated quantum annealing**: every annealed plan is feasible. Our from-scratch path-integral SQA lands
2.0–7.5 % (median) from the exact optimum and has the best median gap in 5 of 6 cases; OpenJij SQA edges it on India
min-cost (2.6 % vs 2.9 %).

**Gate-model QAOA** (12 qubits, simulated exactly): the trained depth-3 circuit returns the best plan in 79 % of shots,
against 1.2 % for random guessing and 2 % for the textbook X-mixer formulation.

**Scalability** (synthetic networks, 5 seeds per size): QMOEA-H's cheapest plan is 2.2 %, 7.6 %, 6.0 % and 6.7 % above
the exact minimum cost at 12, 25, 50 and 100 routes, against 6.0 %, 13.0 %, 16.1 % and 23.1 % for MOPSO. NSGA-II/III
find no feasible plan at 100 routes.

**Where QMOEA-H falls short**:
- At **200 routes** (1,840 ships) no metaheuristic, ours included, finds a plan that meets every constraint within
  32,659 evaluations (nor within 120,000 in a separate check). Only the fleet-availability limit stays violated. The
  exact MILP solves the discretised problem in about 2 s, so at this size the MILP (or a MILP warm start) is the tool to use.
- At 12 routes one of five QMOEA-H runs ended without a feasible plan (MOPSO: 5 of 5).
- Per evaluation it is 3–5× slower than MOPSO in wall-clock time (vectorised Python operators), so at equal evaluations
  it takes longer.

**Impact (India 2030 recommended plan)**: about −60 % WtW GHG, −50 % fuel and −20 % cost vs current practice, with all
CII, FuelEU and schedule constraints met. Against an already slow-steaming VLSFO fleet: about −34 % GHG and −15 % cost.

Full tables, statistical tests and figures: [reports/prediction_benchmark.md](reports/prediction_benchmark.md) and
[reports/optimization_benchmark.md](reports/optimization_benchmark.md).

## Quick start

```bash
make install && make install-web   # Python 3.11 venv + Node deps
make api                           # http://localhost:8000  (API docs at /docs)
make web                           # http://localhost:5173  (dashboard)
```

Or run everything in one container: `docker compose up --build`, then open http://localhost:8000.

**Free live deployment (Render).** [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/DeepakSinghhh/PS-138)
`render.yaml` deploys the Docker image on Render's free plan (no card; about 270 MB of the 512 MB limit is used) and
redeploys on every push. `.github/workflows/keep-alive.yml` pings it every 10 minutes so it does not sleep.

A narrated walkthrough of the prototype is in [docs/demo/](docs/demo/) (`Q-GreenFleet_walkthrough.mp4`, 5½ min, with subtitles and a narration script; it covers the guided tour, the QAOA circuit and the real-data results).

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

1. **Overview**: the India network on the map. Current practice emits about 2.1 Mt CO₂e a year, fails CII on 11 of 12 services in 2030 and owes about ₹191 crore ($21.7 M) a year in FuelEU penalties.
2. **Fleet optimizer**: press *Run optimization*. The Pareto front streams in live, far from the grey reference plans. Click
   *Recommended*: roughly −60 % GHG, −50 % fuel and −20 % cost, all constraints satisfied. Read the explanation, hover the map,
   then click *Minimum emissions* to show the ammonia/methanol extreme. Download the decision report.
3. **Scenario levers**: tick *Red Sea closed*. The Europe service reroutes via the Cape (6,348 → 11,027 nm); re-run and compare.
4. **Fuel prediction**: move the speed and wave sliders. The conformal band tracks the prediction, which sits next to the
   physics-only curve. Switch the fuel system to e-ammonia. Show the tensor-network entanglement chart.
5. **Fuel & policy lab**: run the 2025→2050 pathway (conventional → LNG → e-ammonia), then the MACC. Anneal the QUBO and
   compare the gap to the exact MILP. Run the QAOA circuit: about 79 % of shots give the best plan, against 1.2 % for a
   random guess. Download it as OpenQASM.
6. **Benchmarks**: QMOEA-H vs NSGA-II/III, MOPSO and others (hypervolume, convergence, MILP gaps, scalability to 100 routes), including where it loses.

## Honest notes
- **Money** is shown in rupees by default, in crore for large amounts, with a ₹ / $ switch in the sidebar. The model itself
  works in US dollars because bunker fuel, charter rates and shipping finance are quoted in dollars (EU ETS in euros), and
  converts at an editable rate (`usd_to_inr: 88` in `backend/config/prices.yaml`). The decision report follows the switch.
- Everything runs on classical hardware. "Quantum-inspired" names the algorithms' mechanics: tensor networks,
  superposition/measurement, tunnelling, annealing. It is not a speed-up claim. The QAOA circuit is simulated exactly
  (state vector) on a classical computer; the exported OpenQASM file is what would run on quantum hardware.
- **Real data**: FuelCast (3 ships) is used to evaluate prediction, and EU MRV (2023–2024) to validate the vessel library.
  FuelCast's licence (CC BY-NC-ND 4.0) allows non-commercial use but not redistribution of derivatives, so its files are
  not in the repository and the shipped model is trained on the physics-informed synthetic fleet. The optimizer needs
  that fleet anyway: its vessel classes, alternative fuels and India routes have no public telemetry. The Kaggle
  "ship fuel consumption" set was downloaded too, but it fails basic physical checks (random route lengths, the same
  CO₂ factor for diesel and HFO, no weather effect), so nothing relies on it. See [docs/data_card.md](docs/data_card.md)
  for the audit and download commands.
- Alternative-fuel prices, bunkering-availability years and e-fuel well-to-tank factors are scenario assumptions (cited
  and editable in `backend/config/`).
- QMOEA-H was tuned on the India instance. The EU and synthetic networks test generalisation, and the benchmark reports
  where classical methods do better.

## Documentation
[Problem statement](docs/problem_statement.md) · [Deliverables](docs/deliverables.md) · [Mathematical model](docs/math_model.md) ·
[Algorithms](docs/algorithms.md) · [Implementation guide](docs/implementation_guide.md) · [Data card](docs/data_card.md) ·
[Model card](docs/model_card.md)
