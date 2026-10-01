# Q-GreenFleet walkthrough: narration script

Timestamps match the edited video. The video already carries this narration (neural voice, Kokoro TTS); to record it in your own voice, mute the video's audio and read each line at its timestamp.

## Title card

**0:00–0:09**  This is Q-GreenFleet, our answer to problem statement 26138: quantum-inspired fuel prediction and green fleet optimisation.

## The problem

**0:10–0:17**  Our India case study has twelve real services, from JNPT to Mundra, all the way to Rotterdam.

**0:17–0:28**  Run as fleets run today, it emits about 2.1 million tonnes of CO₂-equivalent a year, and eleven of twelve services fail the 2030 carbon-intensity limit.

**0:29–0:35**  Anyone exploring on their own can start the two-minute guided tour from this page. It walks through every deliverable.

## Title card

**0:37–0:39**  First, optimising the whole fleet.

## Fleet optimizer

**0:41–0:48**  The scenario is India in 2030, with IMO rules, FuelEU and E U carbon trading built in.

**0:49–0:58**  Our quantum-inspired optimiser, QMOEA-H, chooses the vessel mix, capacity, speed, fuel and shore power for all twelve routes at once.

**0:59–1:04**  Every dot is a complete fleet plan, streaming in live, far below today's plans in grey.

**1:05–1:12**  In seconds it evaluates six thousand plans and keeps the 200 best. The recommended plan sits at the knee of the curve.

**1:13–1:23**  Compared with today, the recommended plan cuts emissions by 62 percent, fuel by 53 percent and cost by 23 percent, while meeting every constraint.

**1:24–1:31**  And it explains itself: which routes switch to LNG or ammonia, where to slow down, and where to plug into shore power.

**1:32–1:36**  Here is the fleet on the map, next to the emission profile of every service.

**1:39–1:46**  For each service: the vessel class, number of ships, speed, fuel, shore power and the resulting CII rating.

**1:46–1:53**  One click builds a decision report for managers, with the plan, its compliance, its robustness and its abatement costs.

## Title card

**1:56–1:57**  Second, staying compliant.

## Compliance

**2:00–2:08**  For the chosen plan: every service's CII rating, the FuelEU pool against its tightening limit, and the carbon-trading cost.

## Title card

**2:09–2:11**  Third, predicting fuel for any ship.

## Fuel prediction · Q-PHYS

**2:14–2:21**  Q-PHYS predicts fuel from speed, load, weather and vessel type, combining physics with a quantum-inspired tensor network.

**2:22–2:28**  Speed up, and fuel climbs steeply. The model is certified never to predict less fuel at a higher speed.

**2:29–2:34**  Rougher seas add fuel, and the ninety percent confidence band scales with the prediction.

**2:36–2:40**  Switch the fuel to green ammonia, and the fuel mass and emissions update instantly.

**2:42–2:49**  Inside the tensor network, entanglement entropy shows which inputs the model links together, an idea borrowed from quantum physics.

## Title card

**2:51–2:54**  Fourth, planning the transition to 2050.

## Fuel & policy lab

**2:55–3:02**  Each milestone year to 2050 is optimised under that year's rules, prices and fuel availability.

**3:03–3:08**  The fuel mix shifts decade by decade as the targets tighten, while emissions keep falling.

**3:10–3:16**  The abatement cost curve shows which measures save money, and which cost dollars per tonne of carbon avoided.

**3:16–3:23**  An exact mixed-integer program finds the true optimum in about a second. That is our yardstick for every heuristic.

**3:24–3:33**  The same problem, written as a QUBO, is solved by our own simulated quantum annealer, and runs unchanged on D-Wave quantum hardware.

**3:33–3:38**  The annealed plan lands just 1.52 percent from the exact optimum.

**3:40–3:49**  And here is a real quantum circuit. Twelve qubits decide four services that compete for scarce ships, and the circuit is simulated exactly and trained right here.

**3:50–4:01**  After training, 79 percent of shots return the best plan, against about one percent by guessing, and the circuit downloads as OpenQASM for IBM quantum computers.

## Title card

**4:03–4:04**  Finally, the benchmarks.

## Benchmarks

**4:08–4:17**  Q-PHYS predicts fuel within 3.3 percent on known ships, ahead of LightGBM, random forests and neural networks on the same data.

**4:17–4:33**  On real sensor data from three ships, the FuelCast benchmark, the monotone version of Q-PHYS is the most accurate model: 7.3 percent error, against 9.3 for calibrated physics and 11.6 for LightGBM.

**4:33–4:41**  And our vessel library is checked against twenty-three thousand real E U ship reports, flagging the small classes where it still runs low.

**4:42–4:50**  Over ten seeds, our optimiser ranks first against the classical algorithms, and lands within one percent of the exact optimum.

**4:50–4:59**  And we say where it falls short: at two hundred routes no heuristic finds a feasible plan, not even ours, and the exact solver is the tool to use.

## What-if scenarios

**5:05–5:14**  And what if the Red Sea closes? One click, and the Europe service reroutes around the Cape of Good Hope, adding about four thousand seven hundred nautical miles.

## Title card

**5:16–5:20**  Q-GreenFleet. Predict every tonne, optimise every voyage. Thank you.

