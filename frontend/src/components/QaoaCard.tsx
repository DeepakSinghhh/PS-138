import { useState } from "react";
import Plot from "./Plot";
import { api, followJob } from "../lib/api";
import { useStore } from "../lib/store";
import { useTheme } from "../lib/theme";

interface Layer { p: number; p_optimal: number; p_top3: number; p_valid: number; approx_ratio: number }
interface TopPlan { bits: string; probability: number; plan: string[] | null; optimal: boolean }
interface QaoaResult {
  qubits: number; services: string[]; service_names: string[]; options_per_service: number; valid_plans: number;
  coupled_pairs: number; random_guess_p_optimal: number; random_guess_p_top3: number; qubo_matches_full_model: boolean;
  layers: { xy: Layer[]; x: Layer[] }; top_plans: TopPlan[]; optimum: TopPlan; qasm: string;
}

const pctFmt = (v: number) => `${(100 * v).toFixed(v < 0.1 ? 1 : 0)}%`;

/** Gate-model QAOA on a small fleet sub-problem: trained circuit, measurement statistics, OpenQASM download. */
export default function QaoaCard() {
  const { scenario, setError } = useStore();
  const t = useTheme();
  const [res, setRes] = useState<QaoaResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  if (!scenario) return null;

  const run = async () => {
    setBusy(true); setStage("");
    try {
      const job = await api.qaoa(scenario, { emissions: 0.5, cost: 0.5 });
      setRes(await followJob<QaoaResult>(job.id, (ev) => {
        if (ev.type === "queued") setStage(`waiting for ${ev.ahead} earlier run${(ev.ahead as number) > 1 ? "s" : ""}`);
        if (ev.type === "progress") setStage(String(ev.stage ?? ""));
      }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); setStage(""); }
  };

  const download = () => {
    if (!res) return;
    const url = URL.createObjectURL(new Blob([res.qasm], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `q-greenfleet_qaoa_${res.qubits}q.qasm`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };

  const xy = res?.layers.xy ?? [];
  const best = xy[xy.length - 1];
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>Gate-model QAOA</h3>
          <p className="muted small">A piece of the fleet problem as a quantum circuit: four services that compete for scarce ships each pick
            one of three options (12 qubits). The circuit is simulated exactly and trained here, and exported as OpenQASM 2.0
            for IBM Quantum, Amazon Braket or any QASM toolchain.</p>
        </div>
      </div>
      <div className="filters">
        <button className="btn primary" disabled={busy} onClick={run}>{busy ? "Training circuit…" : "Run QAOA"}</button>
        {res && <button className="btn" onClick={download}>Download OpenQASM</button>}
        {busy && stage && <span className="small muted">{stage}</span>}
      </div>
      {res && best ? (
        <>
          <div className="grid cols-3" style={{ marginTop: 12 }}>
            <div className="stat"><span className="label">Best plan measured</span><span className="value">{pctFmt(best.p_optimal)}</span>
              <span className="unit">of shots at depth p = {best.p}; random guess {pctFmt(res.random_guess_p_optimal)}</span></div>
            <div className="stat"><span className="label">Circuit</span><span className="value">{res.qubits} qubits</span>
              <span className="unit">{res.valid_plans} valid plans · {res.coupled_pairs} ship-sharing couplings</span></div>
            <div className="stat"><span className="label">One of the 3 best plans</span><span className="value">{pctFmt(best.p_top3)}</span>
              <span className="unit">of shots; random guess {pctFmt(res.random_guess_p_top3)}</span></div>
          </div>
          <div className="grid cols-2" style={{ marginTop: 12 }}>
            <div>
              <Plot ariaLabel="Probability of measuring the best plan versus circuit depth" height={260} config={{ displayModeBar: false }} data={[
                {
                  type: "scatter", mode: "lines+markers", name: "XY mixer (one-hot preserving)", x: xy.map((l) => l.p), y: xy.map((l) => 100 * l.p_optimal),
                  line: { color: t["series-1"], width: 2 }, marker: { size: 9, line: { color: t["surface-1"], width: 2 } },
                  hovertemplate: "p = %{x}: %{y:.1f}% of shots<extra>XY mixer</extra>",
                },
                {
                  type: "scatter", mode: "lines+markers", name: "X mixer + penalty (textbook)", x: res.layers.x.map((l) => l.p), y: res.layers.x.map((l) => 100 * l.p_optimal),
                  line: { color: t["series-2"], width: 2 }, marker: { size: 9, line: { color: t["surface-1"], width: 2 } },
                  hovertemplate: "p = %{x}: %{y:.1f}% of shots<extra>X mixer</extra>",
                },
                {
                  type: "scatter", mode: "lines", name: "Random guess", x: [xy[0].p, best.p], y: [100 * res.random_guess_p_optimal, 100 * res.random_guess_p_optimal],
                  line: { color: t["text-muted"], width: 1.5, dash: "dot" }, hoverinfo: "skip",
                },
              ]} layout={{
                xaxis: { title: { text: "circuit depth p (layers)" }, dtick: 1 },
                yaxis: { title: { text: "best plan, % of shots" }, rangemode: "tozero" },
                legend: { orientation: "h", x: 0, y: 1.18 },
                margin: { l: 56, r: 16, t: 48, b: 44 },
              }} />
            </div>
            <div>
              <div className="small muted" style={{ marginBottom: 6 }}>Best plan ({pctFmt(best.p_optimal)} of shots)</div>
              <ul className="plain-list small">
                {(res.optimum.plan ?? []).map((line) => <li key={line}>{line}</li>)}
              </ul>
              <div className="table-wrap" style={{ marginTop: 10 }}>
                <table>
                  <thead><tr><th className="n">Shots</th><th>Next most frequent outcomes (what differs from the best plan)</th></tr></thead>
                  <tbody>
                    {res.top_plans.filter((tp) => !tp.optimal).slice(0, 4).map((tp) => (
                      <tr key={tp.bits}>
                        <td className="n">{pctFmt(tp.probability)}</td>
                        <td className="wrap small">{tp.plan
                          ? tp.plan.filter((line, i) => line !== res.optimum.plan?.[i]).join(" | ")
                          : "invalid (not one option per service)"}</td>
                      </tr>))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <p className="note">Ground truth: all {res.valid_plans} plans evaluated with the full fleet model; the circuit's lowest-energy plan
            {res.qubo_matches_full_model ? " is" : " is not"} the true best plan. The XY mixer keeps exactly one option per service, so
            {" "}{pctFmt(best.p_valid)} of shots are valid plans (textbook X mixer: {pctFmt(res.layers.x[res.layers.x.length - 1].p_valid)}).
            Simulated on a classical computer; no quantum hardware or speed-up is claimed.</p>
        </>
      ) : <div className="empty" style={{ minHeight: 120, marginTop: 12 }}>Train a 12-qubit QAOA circuit on a fleet sub-problem and download it as OpenQASM.</div>}
    </div>
  );
}
