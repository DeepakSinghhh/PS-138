"""Run Q-GreenFleet's 12-qubit fleet QAOA circuit on IBM Quantum hardware, or on a noisy emulation of one.

    # real hardware (needs a free IBM Quantum account; the token is read from the environment, never from a file)
    IBM_QUANTUM_TOKEN=... python tools/ibm_quantum/run_qaoa_hardware.py --shots 4000

    # no account: the same transpiled circuit on Qiskit Aer with the noise model of a real IBM device
    python tools/ibm_quantum/run_qaoa_hardware.py --emulate FakeTorino

The circuit is the one the dashboard exports (India 2030, four services that share scarce ships, three options
each, XY mixer). Every valid plan is also evaluated exactly with the fleet model, so the measured outcomes can be
scored against the true best plan. Results go to reports/qaoa_hardware.{json,md}; "raw" counts every shot,
"post-selected" keeps only shots that are valid plans (exactly one option per service), a common, cheap
mitigation for one-hot encodings.

Requirements (not part of the main app): pip install -r tools/ibm_quantum/requirements.txt
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from greenfleet.optimization.problem import FleetProblem
from greenfleet.quantum import qaoa as Q
from greenfleet.scenarios.scenario import Scenario, resolve

WEIGHTS = {"emissions": 0.5, "cost": 0.5}       # the dashboard's QAOA card uses the same trade-off


def build(depths: list[int]):
    """Ground truth plus the trained XY-mixer circuit for each requested depth p."""
    problem = FleetProblem(resolve(Scenario(network="india", year=2030)))
    res = Q.run_qaoa(problem, WEIGHTS, n_routes=4, k=3, p_max=max(depths))
    sub = Q.build_subproblem(problem, WEIGHTS, 4, 3)
    k, m = sub.k, sub.n // sub.k
    valid = {int(sum(1 << (r * k + j) for r, j in enumerate(combo))) for combo in np.ndindex(*(k,) * m)}
    circuits = {}
    for p in depths:
        layer = res["layers"]["xy"][p - 1]
        circuits[p] = {"qasm": Q.to_qasm(sub, layer["gammas"], layer["betas"]),
                       "ideal": {"p_optimal": layer["p_optimal"], "p_top3": layer["p_top3"], "p_valid": layer["p_valid"]}}
    return res, sub, valid, int(res["optimum"]["bits"], 2), res["top3_indices"], circuits


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--emulate", metavar="FAKE_BACKEND", help="e.g. FakeTorino, FakeSherbrooke (no account needed)")
    ap.add_argument("--backend", help="IBM backend name (default: least busy device with >= 12 qubits)")
    ap.add_argument("--shots", type=int, default=4000)
    ap.add_argument("--depths", default="1,2,3", help="QAOA depths p to run, comma separated")
    ap.add_argument("--out", help="output path without extension (default reports/qaoa_hardware or qaoa_noisy_emulation)")
    args = ap.parse_args()
    args.out = args.out or str(ROOT / "reports" / ("qaoa_noisy_emulation" if args.emulate else "qaoa_hardware"))
    warnings.filterwarnings("ignore", category=DeprecationWarning)

    from qiskit import QuantumCircuit
    from qiskit.transpiler import generate_preset_pass_manager
    from qiskit_ibm_runtime import SamplerV2

    depths = [int(d) for d in args.depths.split(",")]
    res, sub, valid, opt, top3, circuits = build(depths)

    if args.emulate:
        from qiskit_aer import AerSimulator
        from qiskit_ibm_runtime import fake_provider

        device = getattr(fake_provider, args.emulate)()
        backend = AerSimulator.from_backend(device)
        where = f"Qiskit Aer with the noise model of {device.name} ({device.num_qubits} qubits), emulation"
    else:
        token = os.environ.get("IBM_QUANTUM_TOKEN")
        if not token:
            sys.exit("Set IBM_QUANTUM_TOKEN (an IBM Quantum API key) or use --emulate FakeTorino")
        from qiskit_ibm_runtime import QiskitRuntimeService

        service = QiskitRuntimeService(channel="ibm_quantum_platform", token=token,
                                       instance=os.environ.get("IBM_QUANTUM_INSTANCE") or None)
        backend = service.backend(args.backend) if args.backend else service.least_busy(
            operational=True, simulator=False, min_num_qubits=sub.n)
        where = f"IBM Quantum {backend.name} ({backend.num_qubits} qubits), real hardware"

    pm = generate_preset_pass_manager(optimization_level=3, backend=backend, seed_transpiler=7)
    sampler = SamplerV2(mode=backend)
    rows = []
    for p in depths:
        qc = QuantumCircuit.from_qasm_str(circuits[p]["qasm"])
        isa = pm.run(qc)
        ops = isa.count_ops()
        two_q = sum(v for g, v in ops.items() if g in ("cx", "cz", "ecr", "rzz"))
        job = sampler.run([isa], shots=args.shots)
        counts = job.result()[0].data.c.get_counts()
        idx_counts = {int(b, 2): c for b, c in counts.items()}     # bitstring c[n-1]..c[0]; bit i = qubit i
        shots = sum(idx_counts.values())
        n_valid = sum(c for i, c in idx_counts.items() if i in valid)
        hit = idx_counts.get(opt, 0)
        hit3 = sum(idx_counts.get(i, 0) for i in top3)
        best_seen = max(idx_counts, key=idx_counts.get)
        rows.append({
            "p": p, "depth": isa.depth(), "two_qubit_gates": int(two_q), "shots": shots,
            "job_id": job.job_id() if callable(getattr(job, "job_id", None)) else None,
            "raw": {"p_optimal": hit / shots, "p_top3": hit3 / shots, "p_valid": n_valid / shots},
            "post_selected": {"p_optimal": hit / max(n_valid, 1), "p_top3": hit3 / max(n_valid, 1), "valid_shots": n_valid},
            "ideal": circuits[p]["ideal"], "most_frequent_is_optimal": bool(best_seen == opt),
        })
        print(f"p={p}: depth {isa.depth()}, {two_q} two-qubit gates | best plan {100 * hit / shots:.1f}% raw, "
              f"{100 * hit / max(n_valid, 1):.1f}% of valid shots | valid {100 * n_valid / shots:.1f}% "
              f"(ideal: best {100 * circuits[p]['ideal']['p_optimal']:.1f}%, valid {100 * circuits[p]['ideal']['p_valid']:.1f}%)")

    out = {"where": where, "date": dt.datetime.now(dt.UTC).date().isoformat(), "weights": WEIGHTS, "qubits": sub.n,
           "valid_plans": len(valid), "random_guess_p_optimal": 1 / len(valid), "optimum": res["optimum"],
           "services": res["service_names"], "results": rows}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(f"{args.out}.json").write_text(json.dumps(out, indent=1))
    Path(f"{args.out}.md").write_text(markdown(out))
    print(f"wrote {args.out}.json and .md")


def markdown(o: dict) -> str:
    pct = lambda v: f"{100 * v:.1f} %"
    lines = [
        "# QAOA under real-device noise (emulation)" if "emulation" in o["where"] else "# QAOA on quantum hardware", "",
        (f"Backend: **{o['where']}** · {o['date']} · {o['qubits']} qubits, {o['valid_plans']} valid plans "
         f"(random guess finds the best plan {pct(o['random_guess_p_optimal'])} of the time)."), "",
        (f"Services: {', '.join(o['services'])}. Best plan (exact enumeration with the full fleet model): "
         f"{'; '.join(o['optimum']['plan'] or [])}."), "",
        "| p | depth | 2-qubit gates | best plan, raw | best plan, valid shots only | valid shots | ideal best plan | ideal valid |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in o["results"]:
        lines.append(f"| {r['p']} | {r['depth']} | {r['two_qubit_gates']} | {pct(r['raw']['p_optimal'])} | "
                     f"{pct(r['post_selected']['p_optimal'])} | {pct(r['raw']['p_valid'])} | {pct(r['ideal']['p_optimal'])} | "
                     f"{pct(r['ideal']['p_valid'])} |")
    lines += ["", ("Ideal = exact state-vector simulation of the same circuit. Raw counts every shot; the post-selected "
                   "column keeps only shots that are valid plans (one option per service). Noise grows with depth, so "
                   "deeper circuits that are better in theory can do worse on hardware."), ""]
    if "emulation" in o["where"]:
        lines += [("This is a classical simulation with the device's published noise model (gate errors, readout "
                   "errors, decoherence), not a run on quantum hardware. `IBM_QUANTUM_TOKEN=... python "
                   "tools/ibm_quantum/run_qaoa_hardware.py` runs the same circuits on a real IBM device."), ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
