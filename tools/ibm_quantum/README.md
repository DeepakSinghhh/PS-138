# Running the fleet QAOA circuit on IBM Quantum

`run_qaoa_hardware.py` takes the 12-qubit QAOA circuit the dashboard trains (India 2030: four services that share
scarce ships, three options each, XY mixer), transpiles it for an IBM device and samples it. Every valid plan is also
evaluated exactly with the fleet model, so each measured outcome can be scored against the true best plan.

```bash
pip install -r tools/ibm_quantum/requirements.txt       # qiskit, qiskit-aer, qiskit-ibm-runtime (not needed by the app)

# no account needed: the same circuits on Qiskit Aer with a real device's noise model
python tools/ibm_quantum/run_qaoa_hardware.py --emulate FakeTorino

# real hardware: a free IBM Quantum account (quantum.cloud.ibm.com), API key in the environment
export IBM_QUANTUM_TOKEN=...            # never commit it or paste it anywhere
export IBM_QUANTUM_INSTANCE=...         # optional: your instance CRN, if you have more than one
python tools/ibm_quantum/run_qaoa_hardware.py --shots 4000            # least-busy device with >= 12 qubits
python tools/ibm_quantum/run_qaoa_hardware.py --backend ibm_torino    # or a named device
```

Output: `reports/qaoa_noisy_emulation.{json,md}` (emulation) or `reports/qaoa_hardware.{json,md}` (hardware), one row
per circuit depth p with the transpiled depth, two-qubit gate count, and the share of shots that give the best plan,
raw and among valid plans only (exactly one option per service), next to the noise-free simulation.

The free IBM plan includes a monthly allowance of device time; three circuits x 4,000 shots use a few seconds of it.

## Noisy emulation result (IBM Torino noise model, 4,000 shots)

| p | 2-qubit gates | best plan, all shots | best plan, valid shots only | noise-free |
|---|---|---|---|---|
| 1 | 74 | 20.6 % | 34.4 % | 38.4 % |
| 2 | 131 | 31.6 % | 64.4 % | 76.6 % |
| 3 | 189 | 28.8 % | 66.5 % | 79.1 % |

A random guess finds the best of the 81 valid plans 1.2 % of the time. Noise erodes the deeper circuit, so p = 2 is the
best choice on today's hardware. This is a classical emulation, not a hardware run.
