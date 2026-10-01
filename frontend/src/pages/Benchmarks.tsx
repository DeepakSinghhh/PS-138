import { useEffect, useState } from "react";
import Plot from "../components/Plot";
import { api } from "../lib/api";
import { fmt } from "../lib/format";
import { useStore } from "../lib/store";
import { algoColor, useTheme } from "../lib/theme";

const f3 = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toFixed(3));
const pval = (p: number) => (p < 0.001 ? "< 0.001" : p.toFixed(3));
// the "without route merge" ablation shares our hue (it is our algorithm minus one operator) with a dashed line
const isAblationOfOurs = (name: string) => name.startsWith("QMOEA-H w/o");

export default function Benchmarks() {
  const t = useTheme();
  const { meta } = useStore();
  // "Unseen classes PANAMAX_C, SUPRAMAX" -> readable vessel-class names
  const prettyClasses = (txt: string) => txt.replace(/\b[A-Z][A-Z0-9_]{2,}\b/g,
    (id) => meta?.vessel_classes.find((v) => v.id === id)?.label.split(" (")[0] ?? id);
  const [data, setData] = useState<Record<string, any> | null>(null);
  const [inst, setInst] = useState("india_2030");
  useEffect(() => { api.benchmarks().then(setData).catch(() => setData({})); }, []);
  if (!data) return <div className="empty">Loading…</div>;
  const pred = data.prediction_benchmark;
  const opt = data.optimization_benchmark;
  const mrv = data.mrv_validation;
  if (!pred && !opt) return <div className="empty">No benchmark results yet. Run <span className="kbd">make bench-quick</span> (≈ 20 min) or <span className="kbd">make bench-full</span>.</div>;
  const I = opt?.instances?.[inst];

  return (
    <div className="grid page">
      <div className="page-head"><div><span className="kicker">Deliverable 5 · Experimental results</span><h1>Benchmarks</h1>
        <p>The quantum-inspired methods against conventional prediction and optimization methods on accuracy, convergence
          speed, solution quality and scalability, including cases where they do not win.</p></div></div>

      {pred && (
        <>
          <h2>Prediction</h2>
          <div className="grid cols-3">
            {Object.entries(pred.scenarios as Record<string, any>).filter(([, s]) => !s.skipped).map(([k, s]) => (
              <div className="card" key={k}>
                <div className="card-head"><h3>{prettyClasses(s.scenario)}</h3>
                  {k === "D_fuelcast" ? <span className="chip">real ship data</span> : <span className="muted small">{s.ships_in_test} test ships</span>}</div>
                <div className="table-wrap"><table><thead><tr><th>Model</th><th className="n">MAPE %</th><th className="n">R²</th></tr></thead>
                  <tbody>{s.results.filter((r: any) => r.MAPE !== undefined).sort((a: any, b: any) => a.MAPE - b.MAPE).slice(0, 8).map((r: any) => (
                    <tr key={r.model} className={r.model.startsWith("Q-PHYS") ? "hl" : ""}><td className="wrap">{r.model}</td><td className="n">{r.MAPE.toFixed(2)}</td><td className="n">{r.R2.toFixed(3)}</td></tr>))}
                  </tbody></table></div>
                <p className="small muted" style={{ marginTop: 8 }}>90 % interval coverage {(100 * s.conformal.coverage).toFixed(1)}%</p>
              </div>
            ))}
          </div>
          {mrv?.classes && (
            <div className="card">
              <div className="card-head"><div><h3>Vessel library vs EU MRV</h3>
                <p className="muted small">Real annual reports ({mrv.years.join(", ")}, {fmt(mrv.ship_years_used)} ship-years): fuel per n mile of the
                  class model against MRV ships of the same type and cargo size, at their median speed. MRV figures exclude fuel
                  at berth in EU ports but still include anchorage and non-EU port time, so the model should sit somewhat below.</p></div>
                <span className="chip">real ship data</span></div>
              <div className="table-wrap"><table>
                <thead><tr><th>Class</th><th className="n">MRV peers</th><th className="n">speed kn</th><th className="n">MRV p10</th>
                  <th className="n">MRV median</th><th className="n">MRV p90</th><th className="n">model</th><th className="n">model ÷ median</th></tr></thead>
                <tbody>{(mrv.classes as any[]).filter((r) => r.model_kg_per_nm !== undefined).map((r) => (
                  <tr key={r.class}><td className="wrap">{r.label}{r.size_matched ? "" : " (type only)"}</td><td className="n">{fmt(r.peers)}</td>
                    <td className="n">{r.median_speed_kn.toFixed(1)}</td><td className="n">{r.mrv_p10.toFixed(0)}</td><td className="n">{r.mrv_p50.toFixed(0)}</td>
                    <td className="n">{r.mrv_p90.toFixed(0)}</td><td className="n">{r.model_kg_per_nm.toFixed(0)}</td>
                    <td className="n">{r.model_to_median.toFixed(2)}{r.within_p10_p90 ? "" : " ⚑"}</td></tr>))}</tbody>
              </table></div>
              <p className="note">kg per nautical mile. ⚑ = outside the MRV p10–p90 band: the smallest classes (feeder, Handysize, MR tanker)
                under-predict real fuel use and are the first candidates for recalibration.</p>
            </div>
          )}
          {pred.tuners && (
            <div className="card">
              <div className="card-head"><div><h3>Hyperparameter search: convergence at equal budget</h3>
                <p className="muted small">Best validation MAE vs evaluations (lower is better). QPSO = quantum-behaved PSO.</p></div></div>
              <Plot ariaLabel="Tuner convergence" height={300} data={Object.entries(pred.tuners as Record<string, any>).map(([name, v], i) => ({
                type: "scatter", mode: "lines", name, x: v.mean_history.map((_: number, j: number) => j + 1), y: v.mean_history,
                line: { width: name === "QPSO" ? 2.5 : 1.5, color: name === "QPSO" ? t["series-1"] : t[`series-${Math.min(i + 2, 8)}`] },
              }))} layout={{ xaxis: { title: { text: "evaluations" } }, yaxis: { title: { text: "best validation MAE (t/day)" } } }} />
            </div>
          )}
        </>
      )}

      {opt && (
        <>
          <h2>Optimization</h2>
          <div className="segmented" style={{ alignSelf: "start", justifySelf: "start" }}>
            {Object.keys(opt.instances).map((k) => <button key={k} className={inst === k ? "on" : ""} onClick={() => setInst(k)}>{k.replace(/_/g, " ")}</button>)}
          </div>
          {I && (
            <div className="grid cols-2">
              <div className="card">
                <div className="card-head"><div><h3>Front quality</h3><p className="muted small">{opt.config.seeds} seeds · {fmt(opt.config.budget)} evaluations per run (hypervolume: higher is better)</p></div></div>
                <div className="table-wrap"><table>
                  <thead><tr><th>Algorithm</th><th className="n">HV</th><th className="n">IGD+</th><th className="n">evals to 95 %</th><th className="n">best GHG t</th><th className="n">p (vs ours)</th></tr></thead>
                  <tbody>{Object.entries(I.table as Record<string, any>).sort((a, b) => b[1].hv_mean - a[1].hv_mean).map(([name, r]) => (
                    <tr key={name} className={name.includes("ours") ? "hl" : ""}>
                      <td><i className="swatch" style={isAblationOfOurs(name)
                        ? { background: "transparent", border: `2px dashed ${algoColor(t, name)}`, marginRight: 6 }
                        : { background: algoColor(t, name), marginRight: 6 }} />{name}</td>
                      <td className="n">{f3(r.hv_mean)} <span className="muted">±{f3(r.hv_std)}</span></td>
                      <td className="n">{f3(r.igd_plus_mean)}</td>
                      <td className="n">{r.nfe_to_95pct_ref_hv ? fmt(r.nfe_to_95pct_ref_hv) : "–"}</td>
                      <td className="n">{fmt(r.best_objective_mean?.emissions)}</td>
                      <td className="n">{I.mann_whitney_vs_ours?.[name] ? pval(I.mann_whitney_vs_ours[name].p_value) : "–"}</td>
                    </tr>))}</tbody></table></div>
              </div>
              <div className="card">
                <div className="card-head"><h3>Convergence</h3><span className="muted small">mean hypervolume vs evaluations</span></div>
                <Plot ariaLabel="Hypervolume convergence" height={330} data={Object.entries(I.curves as Record<string, any>).map(([name, c]) => ({
                  type: "scatter", mode: "lines", name, x: c.nfe, y: c.hv_mean,
                  line: { color: algoColor(t, name), width: name.includes("ours") ? 2.5 : 1.5, dash: isAblationOfOurs(name) ? "dash" : "solid" },
                }))} layout={{ xaxis: { title: { text: "fleet plans evaluated" } }, yaxis: { title: { text: "hypervolume" } }, legend: { orientation: "h", y: -0.3, font: { size: 10 } } }} />
              </div>
            </div>
          )}
          <div className="grid cols-2">
            {opt.exact && (
              <div className="card">
                <div className="card-head"><div><h3>Optimality gap vs exact MILP</h3><p className="muted small">India 2030, 5 speed levels; gap of each algorithm's best plan per objective.</p></div></div>
                <div className="table-wrap"><table><thead><tr><th>Algorithm</th><th className="n">fuel %</th><th className="n">GHG %</th><th className="n">cost %</th><th className="n">IGD+ vs exact front</th></tr></thead>
                  <tbody>{Object.entries(opt.exact.algorithms as Record<string, any>).map(([n, a]) => (
                    <tr key={n} className={n.includes("ours") ? "hl" : ""}><td>{n}</td><td className="n">{a.gap_pct_mean.fuel?.toFixed(2)}</td><td className="n">{a.gap_pct_mean.emissions?.toFixed(2)}</td>
                      <td className="n">{a.gap_pct_mean.cost?.toFixed(2)}</td><td className="n">{f3(a.igd_plus_vs_exact_front)}</td></tr>))}</tbody></table></div>
              </div>
            )}
            {opt.qubo && (
              <div className="card">
                <div className="card-head"><div><h3>QUBO annealing: gap to exact optimum</h3><p className="muted small">median over seeds, same weighted objective</p></div></div>
                <div className="table-wrap"><table><thead><tr><th>Network</th><th>Weights</th><th className="n">PI-SQA (ours)</th><th className="n">OpenJij SQA</th><th className="n">Classical SA</th></tr></thead>
                  <tbody>{Object.entries(opt.qubo as Record<string, any[]>).flatMap(([net, rows]) => rows.map((r, i) => (
                    <tr key={net + i}><td>{net === "india" ? "India" : net === "eu" ? "EU" : net}</td><td className="wrap">{Object.entries(r.weights).map(([k, v]) => `${k} ${(v as number).toFixed(2)}`).join(", ")}</td>
                      <td className="n">{r.solvers.pi_sqa.gap_pct_median.toFixed(2)}%</td><td className="n">{r.solvers.openjij_sqa.gap_pct_median.toFixed(2)}%</td>
                      <td className="n">{r.solvers.openjij_sa.gap_pct_median.toFixed(2)}%</td></tr>)))}</tbody></table></div>
              </div>
            )}
          </div>
          {opt.scalability && (
            <div className="card">
              <div className="card-head"><div><h3>Scalability</h3><p className="muted small">Synthetic networks on real ports, {opt.config.scal_seeds ?? 1} run(s) per size and method: feasibility, hypervolume, cost gap of the cheapest plan to the exact single-objective MILP, and wall time. A missing point means no run found a plan meeting every constraint.</p></div></div>
              <div className="grid cols-2">
                <Plot ariaLabel="Scalability: cost gap to the exact optimum" height={300} data={
                  Object.keys(opt.scalability.rows[0].algorithms).map((name) => ({
                    type: "scatter" as const, mode: "lines+markers" as const, name, x: opt.scalability.rows.map((r: any) => r.routes),
                    y: opt.scalability.rows.map((r: any) => r.algorithms[name].cost_gap_pct_vs_milp ?? null),
                    line: { color: algoColor(t, name), width: name.includes("ours") ? 2.5 : 1.5 }, marker: { size: 8, line: { color: t["surface-1"], width: 2 } },
                    hovertemplate: `${name}<br>%{x} routes: %{y:.1f}% above the MILP cost<extra></extra>` }))
                } layout={{ xaxis: { title: { text: "routes" } }, yaxis: { title: { text: "cost gap to exact optimum (%)" }, rangemode: "tozero" }, legend: { orientation: "h", y: -0.32 } }} />
                <div className="table-wrap"><table><thead><tr><th className="n">Routes</th><th className="n">Ships</th><th>Algorithm</th><th className="n">feasible</th><th className="n">HV</th><th className="n">cost gap %</th><th className="n">s</th></tr></thead>
                  <tbody>{opt.scalability.rows.flatMap((r: any) => Object.entries(r.algorithms as Record<string, any>).map(([n, a]) => (
                    <tr key={r.routes + n} className={n.includes("ours") ? "hl" : ""}><td className="n">{r.routes}</td><td className="n">{r.ships_available}</td><td>{n}</td>
                      <td className="n">{a.feasible_runs}/{opt.config.scal_seeds ?? 1}</td><td className="n">{a.hv_mean.toFixed(2)}</td><td className="n">{a.cost_gap_pct_vs_milp?.toFixed(2) ?? "–"}</td><td className="n">{a.seconds_mean.toFixed(1)}</td></tr>)))}</tbody></table></div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
