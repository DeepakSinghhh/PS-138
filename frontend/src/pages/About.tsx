const DELIVERABLES = [
  ["1", "Fuel consumption prediction model", "Inputs speed, load, weather, vessel type; accuracy and statistical tests",
    "Q-PHYS: physics prior (IMO GHG4 + Kwon + SFOC) · Matrix-Product-State tensor network (qudit feature encoding, DMRG sweeps) · QPSO-tuned monotone booster · QIEA feature selection · split-conformal intervals · Wilcoxon tests"],
  ["2", "Mathematical optimization formulation", "Vessel mix, capacity, speed, fuel; min fuel/emissions/cost; demand, schedule, emission limits",
    "Per-route class, fleet size, speed, fuel pathway and shore power; objectives fuel, WtW GHG, cost (+ schedule risk); constraints demand, weekly frequency, on-time probability, fleet availability, CII, FuelEU pooling, emission cap"],
  ["3", "Quantum-inspired optimization algorithm", "Quantum optimization or equivalent; encoding; quantum update mechanisms",
    "QMOEA-H: qudit registers per route, superposition crossover, quantum memory register, δ-potential-well speed moves, Hadamard reset. Plus QUBO + path-integral simulated quantum annealing (D-Wave-ready)"],
  ["4", "Software platform / decision support", "UI/API, scenario simulation, fleet allocation & emission visualisation, reports",
    "FastAPI + React dashboard, live Pareto streaming, scenario lab (year, prices, carbon, Red Sea, monsoon, CSV upload), maps, emission profiles, downloadable report"],
  ["5", "Demonstration", "Large-scale real or simulated scenario; algorithm details; implementation guide; results",
    "India coastal & near-sea network (12 services), EU FuelEU/ETS network, MILP-certified synthetic networks up to 100 routes / 1,250 ships; benchmark reports; docs/implementation_guide.md"],
];

export default function About() {
  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="page-head"><div><span className="kicker">How it works</span><h1>Methodology</h1>
        <p>SIH 2026 problem statement 26138 (Egreen Quanta): quantum-inspired fuel consumption prediction and green fleet optimization.</p></div></div>
      <div className="card">
        <h3>How the platform meets the delivery table</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>#</th><th>Deliverable</th><th>Required</th><th>Implementation</th></tr></thead>
          <tbody>{DELIVERABLES.map((d) => <tr key={d[0]}><td>{d[0]}</td><td><b>{d[1]}</b></td><td style={{ whiteSpace: "normal" }}>{d[2]}</td><td style={{ whiteSpace: "normal" }}>{d[3]}</td></tr>)}</tbody>
        </table></div>
      </div>
      <div className="grid cols-2">
        <div className="card">
          <h3>Where the quantum inspiration is</h3>
          <ul>
            <li><b>Tensor networks.</b> The MPS regressor uses the same maths as quantum many-body simulation. Each feature is a spin-coherent qudit state, the model is a matrix product state, and it is trained by DMRG-style sweeps. Bond entanglement entropy shows which features the model couples.</li>
            <li><b>Superposition and measurement.</b> QMOEA-H stores fleet decisions as amplitude registers. Offspring are measured from superpositions of parent and leader states; a floor of Hadamard noise keeps every option reachable.</li>
            <li><b>Quantum tunnelling.</b> Speeds move in a QPSO δ-potential well: heavy-tailed ln(1/u) jumps escape local optima.</li>
            <li><b>Annealing.</b> The fleet QUBO is solved by path-integral simulated quantum annealing (Trotter replicas under a decaying transverse field) and exports unchanged to D-Wave hardware.</li>
          </ul>
        </div>
        <div className="card">
          <h3>Honesty notes</h3>
          <ul>
            <li>Everything runs on classical hardware; "quantum-inspired" names the algorithms' mechanics, not a speed-up claim.</li>
            <li>Real data: prediction is evaluated on FuelCast (sensor logs of three real ships; Q-PHYS-M 7.3 % MAPE vs 9.3 % for calibrated physics) and the vessel library is checked against 23,009 EU MRV ship-years. FuelCast's licence forbids redistributing derivatives, so the shipped model is trained on the physics-informed synthetic fleet, which also covers the alternative-fuel vessels and India routes that have no public telemetry.</li>
            <li>Alternative-fuel prices, bunkering years and e-fuel WtT factors are scenario assumptions, editable in YAML and the UI.</li>
            <li>QMOEA-H parameters were set on the India instance; two later operator settings (route-wise merge rate, availability attribution) were also compared on the EU and synthetic networks, as the benchmark report discloses. The report also shows where classical methods or the exact MILP do better.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
