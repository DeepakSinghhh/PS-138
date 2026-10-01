# QAOA under real-device noise (emulation)

Backend: **Qiskit Aer with the noise model of fake_torino (133 qubits), emulation** · 2026-10-01 · 12 qubits, 81 valid plans (random guess finds the best plan 1.2 % of the time).

Services: JNPT - Mundra coastal container, Chennai - Port Blair (Ro-Pax), Kochi - Kavaratti (Lakshadweep), Mundra - Rotterdam (Europe trade). Best plan (exact enumeration with the full fleet model): R01 · 1 × Feeder container · Bio-methanol · 14.1 kn · shore power; R05 · 2 × Ro-Pax ferry · HFO (with scrubber) · 12.0 kn · shore power; R06 · 1 × Island passenger-cargo ship · Bio-LNG · 10.0 kn; R09 · 6 × Neo-Panamax container · LNG (high-pressure Diesel cycle) · 14.3 kn · shore power.

| p | depth | 2-qubit gates | best plan, raw | best plan, valid shots only | valid shots | ideal best plan | ideal valid |
|---|---|---|---|---|---|---|---|
| 1 | 118 | 74 | 20.6 % | 34.4 % | 59.8 % | 38.4 % | 100.0 % |
| 2 | 210 | 131 | 31.6 % | 64.4 % | 49.0 % | 76.6 % | 100.0 % |
| 3 | 268 | 189 | 28.8 % | 66.5 % | 43.4 % | 79.1 % | 100.0 % |

Ideal = exact state-vector simulation of the same circuit. Raw counts every shot; the post-selected column keeps only shots that are valid plans (one option per service). Noise grows with depth, so deeper circuits that are better in theory can do worse on hardware.

This is a classical simulation with the device's published noise model (gate errors, readout errors, decoherence), not a run on quantum hardware. `IBM_QUANTUM_TOKEN=... python tools/ibm_quantum/run_qaoa_hardware.py` runs the same circuits on a real IBM device.
