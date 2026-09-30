# Q-GreenFleet walkthrough: narration script

Timestamps match the edited video. The video already carries this narration (neural voice, Kokoro TTS); to record it in your own voice, mute the video's audio and read each line at its timestamp.

## Title card

**0:00–0:09**  This is Q-GreenFleet, our answer to problem statement 26138: quantum-inspired fuel prediction and green fleet optimisation.

## The problem

**0:10–0:17**  Our India case study has twelve real services, from JNPT to Mundra, all the way to Rotterdam.

**0:17–0:28**  Run as fleets run today, it emits about 2.1 million tonnes of CO₂-equivalent a year, and eleven of twelve services fail the 2030 carbon-intensity limit.

## Title card

**0:30–0:32**  First, optimising the whole fleet.

## Fleet optimizer

**0:34–0:41**  The scenario is India in 2030, with IMO rules, FuelEU and E U carbon trading built in.

**0:42–0:51**  Our quantum-inspired optimiser, QMOEA-H, chooses the vessel mix, capacity, speed, fuel and shore power for all twelve routes at once.

**0:52–0:57**  Every dot is a complete fleet plan, streaming in live, far below today's plans in grey.

**0:58–1:06**  In seconds it evaluates six thousand plans and keeps the 116 best. The recommended plan sits at the knee of the curve.

**1:06–1:16**  Compared with today, the recommended plan cuts emissions by 60 percent, fuel by 52 percent and cost by 23 percent, while meeting every constraint.

**1:17–1:24**  And it explains itself: which routes switch to LNG or ammonia, where to slow down, and where to plug into shore power.

**1:25–1:29**  Here is the fleet on the map, next to the emission profile of every service.

**1:32–1:39**  For each service: the vessel class, number of ships, speed, fuel, shore power and the resulting CII rating.

**1:40–1:47**  One click builds a decision report for managers, with the plan, its compliance, its robustness and its abatement costs.

## Title card

**1:49–1:51**  Second, staying compliant.

## Compliance

**1:54–2:02**  For the chosen plan: every service's CII rating, the FuelEU pool against its tightening limit, and the carbon-trading cost.

## Title card

**2:03–2:05**  Third, predicting fuel for any ship.

## Fuel prediction · Q-PHYS

**2:07–2:15**  Q-PHYS predicts fuel from speed, load, weather and vessel type, combining physics with a quantum-inspired tensor network.

**2:16–2:22**  Speed up, and fuel climbs steeply. The model is certified never to predict less fuel at a higher speed.

**2:23–2:28**  Rougher seas add fuel, and the ninety percent confidence band scales with the prediction.

**2:31–2:36**  Switch the fuel to green ammonia, and the fuel mass and emissions update instantly.

**2:37–2:45**  Inside the tensor network, entanglement entropy shows which inputs the model links together, an idea borrowed from quantum physics.

## Title card

**2:46–2:49**  Fourth, planning the transition to 2050.

## Fuel & policy lab

**2:50–2:57**  Each milestone year to 2050 is optimised under that year's rules, prices and fuel availability.

**2:58–3:03**  The fuel mix shifts decade by decade as the targets tighten, while emissions keep falling.

**3:05–3:11**  The abatement cost curve shows which measures save money, and which cost dollars per tonne of carbon avoided.

**3:11–3:18**  An exact mixed-integer program finds the true optimum in about a second. That is our yardstick for every heuristic.

**3:19–3:28**  The same problem, written as a QUBO, is solved by our own simulated quantum annealer, and runs unchanged on D-Wave quantum hardware.

**3:28–3:33**  The annealed plan lands just 1.52 percent from the exact optimum.

## Title card

**3:35–3:36**  Finally, the benchmarks.

## Benchmarks

**3:40–3:49**  Q-PHYS predicts fuel within 3.3 percent on known ships, ahead of LightGBM, random forests and neural networks on the same data.

**3:49–3:56**  Our optimiser ranks first against the classical algorithms, and lands within one to three percent of the exact optimum.

**3:57–4:03**  And we show honestly where classical methods still win: on very large, loosely constrained networks.

## What-if scenarios

**4:08–4:17**  And what if the Red Sea closes? One click, and the Europe service reroutes around the Cape of Good Hope, adding about four thousand seven hundred nautical miles.

## Title card

**4:19–4:24**  Q-GreenFleet. Predict every tonne, optimise every voyage. Thank you.

