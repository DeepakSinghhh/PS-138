# Q-GreenFleet walkthrough: voice-over script

Timestamps match the edited video. Read each line while its caption is on screen (about 150 words per minute). The on-screen captions already carry the story, so the video also works without a voice-over.

## The problem

**0:04–0:10**  This is our India case study: twelve real coastal and near-sea services, from JNPT to Mundra and Chennai to Singapore, all the way to Mundra and Rotterdam.

**0:10–0:17**  Run the way fleets run today, on VLSFO at full schedule speed, this network emits about two point one million tonnes of CO2-equivalent a year, and eleven of the twelve services fail the 2030 carbon-intensity limit.

## Fleet optimizer

**0:22–0:27**  The scenario is India in 2030. IMO's carbon-intensity rules, FuelEU Maritime and the EU emissions trading system are built in, and every assumption can be edited.

**0:27–0:35**  Our quantum-inspired optimiser, QMOEA-H, decides the vessel mix, capacity, speed, fuel and shore power for all twelve routes at once.

**0:35–0:41**  Every dot is a complete fleet plan. The front of best trade-offs streams in live, far below today's reference plans in grey.

**0:41–0:48**  In a few seconds it evaluates six thousand plans and keeps 116 Pareto-optimal ones. The recommended plan sits at the knee of the curve.

**0:48–0:55**  The recommended plan cuts well-to-wake greenhouse gas by 60 percent, fuel by 52 percent and cost by 23 percent compared with today, and it meets every constraint.

**0:55–1:03**  And it explains itself in plain words: which routes switch to LNG or ammonia, where to slow down, and where to plug into shore power.

**1:03–1:10**  Here is the fleet allocation on the map, next to the emission profile of every service.

**1:10–1:17**  For each service you get the vessel class and capacity, the number of ships, the speed, the fuel, shore power, and the resulting CII rating.

**1:17–1:26**  One more click builds a decision report for managers, with the plan, its compliance, its robustness and its abatement costs.

## Compliance

**1:31–1:37**  For the chosen plan you see the CII rating of every service, the FuelEU pool against a limit that tightens every year, and the EU ETS exposure.

## Fuel prediction · Q-PHYS

**1:42–1:48**  Q-PHYS predicts fuel from speed, load, weather and vessel type. It combines a physics model with a quantum-inspired tensor network.

**1:48–1:56**  Speed up and fuel rises steeply. The model is certified never to predict less fuel at a higher speed, so the optimiser can trust it.

**1:56–2:03**  Rougher seas add fuel, and the ninety percent confidence band scales with the prediction.

**2:03–2:09**  Switch the fuel system to e-ammonia, and the fuel mass and well-to-wake emissions update instantly.

**2:09–2:15**  Inside the tensor network, entanglement entropy shows which inputs the model couples, a view borrowed straight from quantum physics.

## Fuel & policy lab

**2:20–2:25**  Now the transition to 2050. Every milestone year is optimised under that year's rules, prices and fuel availability.

**2:25–2:33**  The fuel mix shifts decade by decade as the targets tighten, while emissions keep falling.

**2:33–2:39**  The marginal abatement cost curve shows which measures save money, and which ones cost dollars per tonne of CO2 avoided.

**2:39–2:45**  An exact MILP solves the discretised problem to true optimality in about a second. That is the yardstick we hold every heuristic to.

**2:45–2:51**  The same fleet problem is also written as a QUBO, solved by our own simulated quantum annealer, and it can be sent unchanged to D-Wave quantum hardware.

**2:51–2:56**  The annealed plan lands 1.52 percent from the exact optimum on the same objective, and it is fully feasible.

## Benchmarks

**3:02–3:10**  On prediction, Q-PHYS reaches three point three percent error on known ships, ahead of LightGBM, random forests and neural networks trained on the same data.

**3:10–3:16**  On optimisation, QMOEA-H ranks first against NSGA-II, NSGA-III and MOPSO, and lands within one to three percent of the exact optimum.

**3:16–3:22**  And we show where classical methods still do better, such as MOPSO on very large, loosely constrained networks.

## What-if scenarios

**3:27–3:37**  And what if the Red Sea closes? Tick one box, and the Europe service reroutes around the Cape of Good Hope, from about six thousand three hundred to eleven thousand nautical miles, ready to re-optimise.

## Title cards

- 0:00: SIH 2026 · Problem statement 26138 · Egreen Quanta Q-GreenFleet Quantum-inspired fuel prediction and green fleet optimization Prototype walkthrough · Clean & Green Technology
- 0:18: 01 Optimise the whole fleet Vessel mix · capacity · speed · fuel · shore power
- 1:26: 02 Stay compliant IMO CII · FuelEU Maritime · EU ETS, year by year
- 1:38: 03 Predict fuel for any ship Speed · load · weather · vessel type
- 2:16: 04 Plan the transition 2025 → 2050 pathway · abatement costs · exact optimum · quantum annealing
- 2:56: 05 Benchmarked honestly Accuracy · convergence · solution quality · scalability
- 3:37: Q-GreenFleet · SIH 2026 · PS 26138 Predict every tonne. Optimise every voyage. Working prototype · FastAPI + React · 71 automated tests · one-command Docker github.com/DeepakSinghhh/PS-138
