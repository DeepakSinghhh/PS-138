import { useState } from "react";
import Plot from "../components/Plot";
import QaoaCard from "../components/QaoaCard";
import ScenarioPanel from "../components/ScenarioPanel";
import { api, followJob } from "../lib/api";
import { compact, fmt, pct } from "../lib/format";
import { useStore } from "../lib/store";
import { FAMILY_LABEL, familyColor, useTheme } from "../lib/theme";

const FUEL_FAMILY = (meta: any, fid: string) => meta?.fuels.find((f: any) => f.id === fid)?.family ?? "conventional";

export default function Lab() {
  const { scenario, meta, selected, setError } = useStore();
  const t = useTheme();
  const [timeline, setTimeline] = useState<any>(null);
  const [tlBusy, setTlBusy] = useState(false);
  const [tlProg, setTlProg] = useState(0);
  const [pref, setPref] = useState("cost");
  const [macc, setMacc] = useState<any>(null);
  const [robust, setRobust] = useState<any>(null);
  const [exact, setExact] = useState<Record<string, any>>({});
  const [qubo, setQubo] = useState<any>(null);
  const [qBusy, setQBusy] = useState(false);
  const [solver, setSolver] = useState("pi_sqa");
  const [wEm, setWEm] = useState(0.5);
  const [qStage, setQStage] = useState("");
  if (!scenario) return null;

  const runTimeline = async () => {
    setTlBusy(true); setTlProg(0);
    try {
      const job = await api.timeline({ ...scenario }, [2025, 2030, 2035, 2040, 2045, 2050], 3000, pref);
      setTimeline(await followJob(job.id, (ev) => { if (ev.type === "progress") setTlProg((ev.done as number) / (ev.total as number)); }));
    } catch (e) { setError((e as Error).message); } finally { setTlBusy(false); }
  };

  // timeline data: energy share by fuel family per year
  const years: number[] = timeline?.rows.map((r: any) => r.year) ?? [];
  const famShare = (row: any) => {
    const out: Record<string, number> = {};
    Object.entries(row.fuel_mix as Record<string, number>).forEach(([fid, s]) => { const f = FUEL_FAMILY(meta, fid); out[f] = (out[f] ?? 0) + s; });
    return out;
  };
  const families = ["conventional", "lng", "methanol", "ammonia", "hydrogen"];

  // MACC geometry: bar widths = abatement, height = $/t
  const maccRows = (macc?.measures ?? []).filter((m: any) => m.usd_per_t !== null);
  let cum = 0;
  const maccX: number[] = [], maccW: number[] = [];
  maccRows.forEach((m: any) => { maccX.push(cum + m.abatement_t / 2); maccW.push(m.abatement_t); cum += m.abatement_t; });

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="page-head"><div><span className="kicker">Scenario simulation · 2025–2050</span><h1>Fuel &amp; policy lab</h1>
        <p>Scenario analysis for alternative fuels: how the optimal fleet shifts from 2025 to 2050, what each measure costs
          per tonne abated, how robust a plan is, and how close quantum-inspired annealing gets to the exact optimum.</p></div></div>
      <ScenarioPanel compact />

      <div className="card">
        <div className="card-head">
          <div><h3>Transition pathway 2025 → 2050</h3><p className="muted small">Each milestone year is optimised with QMOEA-H under that year's CII / FuelEU targets, prices and bunkering availability.</p></div>
          <div className="btn-row">
            <div className="segmented">
              {[["cost", "cheapest"], ["balanced", "balanced"], ["emissions", "greenest"]].map(([k, l]) => (
                <button key={k} className={pref === k ? "on" : ""} onClick={() => setPref(k)}>{l}</button>))}
            </div>
            <button className="btn primary" onClick={runTimeline} disabled={tlBusy}>{tlBusy ? `Optimising… ${Math.round(tlProg * 100)}%` : "Run pathway"}</button>
          </div>
        </div>
        {timeline ? (
          <div className="grid cols-2">
            <Plot ariaLabel="Fuel mix by year" height={320} data={families.map((f) => ({
              type: "bar", name: FAMILY_LABEL[f], x: years, y: timeline.rows.map((r: any) => 100 * (famShare(r)[f] ?? 0)),
              marker: { color: familyColor(t, f), line: { color: t["surface-1"], width: 2 } },
              hovertemplate: `%{x}: %{y:.0f}% ${FAMILY_LABEL[f]}<extra></extra>`,
            }))} layout={{ barmode: "stack", bargap: 0.35, yaxis: { title: { text: "share of fleet energy (%)" }, range: [0, 100] }, xaxis: { type: "category" } }} />
            <div className="grid" style={{ gap: 6 }}>
              <Plot ariaLabel="Emissions by year" height={155} data={[{
                type: "scatter", mode: "lines+markers", x: years, y: timeline.rows.map((r: any) => r.objectives.emissions / 1000),
                line: { color: t["series-1"], width: 2 }, marker: { size: 8, line: { color: t["surface-1"], width: 2 } }, name: "WtW GHG",
                hovertemplate: "%{x}: %{y:,.0f} kt CO₂e<extra></extra>" }]}
                layout={{ margin: { l: 56, r: 16, t: 4, b: 24 }, yaxis: { title: { text: "kt CO₂e" }, rangemode: "tozero" }, xaxis: { type: "category" }, showlegend: false }} />
              <Plot ariaLabel="Cost by year" height={155} data={[{
                type: "scatter", mode: "lines+markers", x: years, y: timeline.rows.map((r: any) => r.objectives.cost),
                line: { color: t["neutral-series"], width: 2 }, marker: { size: 8, line: { color: t["surface-1"], width: 2 } }, name: "Cost",
                hovertemplate: "%{x}: %{y:,.0f} M USD<extra></extra>" }]}
                layout={{ margin: { l: 56, r: 16, t: 4, b: 24 }, yaxis: { title: { text: "M USD" }, rangemode: "tozero" }, xaxis: { type: "category" }, showlegend: false }} />
              <p className="small muted">{timeline.rows.map((r: any) => `${r.year}: ${r.feasible ? "compliant" : "infeasible"}`).join(" · ")}</p>
            </div>
          </div>
        ) : <div className="empty">Optimise six milestone years (about 10 s).</div>}
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-head"><div><h3>Marginal abatement cost curve</h3><p className="muted small">Single measures applied fleet-wide to current practice; width = t CO₂e abated per year.</p></div>
            <button className="btn" onClick={() => api.macc(scenario).then(setMacc).catch((e) => setError(e.message))}>Compute</button></div>
          {macc ? (
            <>
              <Plot ariaLabel="Marginal abatement cost curve" height={320} data={[{
                type: "bar", x: maccX, width: maccW, y: maccRows.map((m: any) => m.usd_per_t),
                marker: { color: maccRows.map((m: any) => (m.usd_per_t < 0 ? t["series-3"] : t["series-1"])), line: { color: t["surface-1"], width: 2 } },
                customdata: maccRows.map((m: any) => [m.measure, m.abatement_t, m.feasible ? "feasible alone" : "needs other measures"]),
                hovertemplate: "%{customdata[0]}<br>%{y:,.0f} USD/t · %{customdata[1]:,.0f} t/yr<br>%{customdata[2]}<extra></extra>",
                text: maccRows.map((m: any) => m.measure.split(" (")[0]), textposition: "outside", textfont: { size: 10, color: t["text-secondary"] }, cliponaxis: false,
              }]} layout={{ xaxis: { title: { text: "cumulative abatement (t CO₂e / yr)" } }, yaxis: { title: { text: "USD per t CO₂e" } }, showlegend: false }} />
              <div className="legend"><span><i className="swatch" style={{ background: t["series-3"] }} />saves money</span><span><i className="swatch" style={{ background: t["series-1"] }} />costs money</span></div>
            </>
          ) : <div className="empty">Rank decarbonisation measures by cost-effectiveness.</div>}
        </div>

        <div className="card">
          <div className="card-head"><div><h3>Robustness of the selected plan</h3><p className="muted small">{selected?.label ?? "No plan selected"}: 400 Monte Carlo draws of fuel prices (σ 25 %), carbon price (±30 %) and weather (±0.5 Bf).</p></div>
            <button className="btn" disabled={!selected} onClick={() => selected && api.robustness(scenario, selected.genes).then(setRobust).catch((e) => setError(e.message))}>Simulate</button></div>
          {robust ? (
            <>
              <Plot ariaLabel="Distribution of annual cost" height={260} data={[{
                type: "histogram", x: robust.cost.samples, nbinsx: 30, marker: { color: t["series-1"], line: { color: t["surface-1"], width: 1 } },
                hovertemplate: "%{x:,.0f} M USD: %{y} draws<extra></extra>", name: "cost",
              }]} layout={{ xaxis: { title: { text: "annual cost (M USD)" } }, yaxis: { title: { text: "draws" } }, bargap: 0.05, showlegend: false,
                shapes: [["p5", "P5"], ["mean", "mean"], ["p95", "P95"]].map(([k]) => ({ type: "line", x0: robust.cost[k], x1: robust.cost[k], yref: "paper", y0: 0, y1: 1, line: { color: t["text-muted"], width: 1 } })),
                annotations: [["p5", "P5"], ["mean", "mean"], ["p95", "P95"]].map(([k, l]) => ({ x: robust.cost[k], yref: "paper", y: 1.02, text: l, showarrow: false, font: { size: 10, color: t["text-secondary"] } })) }} />
              <p className="small">Cost mean <b>{fmt(robust.cost.mean, 1)}</b> M USD · P95 {fmt(robust.cost.p95, 1)} · CVaR95 {fmt(robust.cost.cvar95, 1)} ·
                emissions P95 {compact(robust.emissions.p95)} t CO₂e</p>
            </>
          ) : <div className="empty">Stress-test the plan chosen in the optimizer.</div>}
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-head"><div><h3>Exact reference (MILP)</h3><p className="muted small">With speeds discretised to 5 levels, the multiple-choice MILP gives the true optimum, the yardstick for every heuristic.</p></div></div>
          <div className="btn-row">
            {["fuel", "emissions", "cost"].map((o) => (
              <button key={o} className="btn" onClick={() => api.exact(scenario, o).then((r) => setExact((s) => ({ ...s, [o]: r }))).catch((e) => setError(e.message))}>Minimum {o}</button>))}
          </div>
          {Object.keys(exact).length === 0 ? <div className="empty" style={{ marginTop: 10, minHeight: 120 }}>Solve for an extreme to see the true optimum.</div> : (
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table><thead><tr><th>Exact optimum</th><th className="n">Fuel t</th><th className="n">GHG t CO₂e</th><th className="n">Cost M$</th><th className="n">Solve s</th><th className="n">vs selected plan</th></tr></thead>
              <tbody>{Object.entries(exact).map(([o, r]) => (
                <tr key={o}><td>min {o}</td><td className="n">{fmt(r.objectives?.fuel)}</td><td className="n">{fmt(r.objectives?.emissions)}</td>
                  <td className="n">{fmt(r.objectives?.cost, 1)}</td><td className="n">{fmt(r.seconds, 2)}</td>
                  <td className="n">{selected ? pct(100 * (selected.plan.objectives[o as "fuel"] - r.objectives[o]) / r.objectives[o]) : "–"}</td></tr>))}
              </tbody></table>
          </div>)}
        </div>
        <div className="card">
          <div className="card-head"><div><h3>QUBO + quantum annealing</h3><p className="muted small">The fleet problem as a one-hot QUBO, exported as a D-Wave BQM and solved here by simulated quantum annealing.</p></div></div>
          <div className="filters">
            <label className="field">Solver
              <select value={solver} onChange={(e) => setSolver(e.target.value)}>
                <option value="pi_sqa">Path-integral SQA (ours, from scratch)</option>
                <option value="openjij_sqa">OpenJij SQA</option>
                <option value="openjij_sa">Classical simulated annealing</option>
              </select>
            </label>
            <label className="field" style={{ minWidth: 200 }}>
              <span className="range-row"><span>Weight on emissions</span><span className="num">{wEm.toFixed(2)}</span></span>
              <input type="range" min={0} max={1} step={0.05} value={wEm} onChange={(e) => setWEm(Number(e.target.value))} />
            </label>
            <button className="btn primary" disabled={qBusy} onClick={async () => {
              setQBusy(true);
              try {
                setQStage("");
                const job = await api.qubo(scenario, { emissions: wEm, cost: 1 - wEm }, solver);
                setQubo(await followJob(job.id, (ev) => {
                  if (ev.type === "queued") setQStage(`waiting for ${ev.ahead} earlier run${(ev.ahead as number) > 1 ? "s" : ""}`);
                  if (ev.type === "progress") setQStage(String(ev.stage ?? ""));
                }));
              } catch (e) { setError((e as Error).message); } finally { setQBusy(false); setQStage(""); }
            }}>{qBusy ? "Annealing…" : "Anneal"}</button>
            {qBusy && qStage && <span className="small muted">{qStage}</span>}
          </div>
          {qubo ? (
            <div className="grid cols-3" style={{ marginTop: 12 }}>
              <div className="stat"><span className="label">Gap to exact optimum</span><span className="value">{qubo.gap_pct_vs_exact.toFixed(2)}%</span><span className="unit">same weighted objective</span></div>
              <div className="stat"><span className="label">QUBO variables</span><span className="value">{qubo.qubo_variables}</span><span className="unit">one-hot + slack bits</span></div>
              <div className="stat"><span className="label">Time</span><span className="value">{qubo.seconds.toFixed(1)} s</span><span className="unit">{qubo.iterations} lazy-constraint round(s)</span></div>
            </div>
          ) : <div className="empty" style={{ minHeight: 120, marginTop: 12 }}>Anneal the fleet QUBO and compare with the exact MILP.</div>}
        </div>
      </div>
      <QaoaCard />
    </div>
  );
}
