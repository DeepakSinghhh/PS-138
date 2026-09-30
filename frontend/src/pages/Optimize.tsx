import { useMemo, useState } from "react";
import Plot from "../components/Plot";
import PlanDetails from "../components/PlanDetails";
import ScenarioPanel from "../components/ScenarioPanel";
import { api, followJob } from "../lib/api";
import { fmt, OBJ_SHORT, OBJ_UNITS } from "../lib/format";
import { useStore } from "../lib/store";
import { useTheme } from "../lib/theme";
import type { OptResult } from "../lib/types";

const PICK_LABEL: Record<string, string> = {
  balanced: "Recommended (balanced)", min_fuel: "Minimum fuel", min_emissions: "Minimum emissions", min_cost: "Minimum cost",
  min_schedule_risk: "Most reliable",
};

export default function Optimize() {
  const { scenario, meta, network, result, setResult, selected, setSelected, setError } = useStore();
  const t = useTheme();
  const [algorithm, setAlgorithm] = useState("QMOEA-H");
  const [budget, setBudget] = useState(6000);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [live, setLive] = useState<number[][]>([]);
  const [view, setView] = useState<"2d" | "3d">("2d");
  const [feasibleSoFar, setFeasibleSoFar] = useState(false);

  const objs = result?.objectives ?? scenario?.objectives ?? ["fuel", "emissions", "cost"];
  const ix = (o: string) => objs.indexOf(o as never);

  const run = async () => {
    if (!scenario) return;
    setRunning(true); setProgress(0); setLive([]); setResult(null); setFeasibleSoFar(false);
    try {
      const job = await api.optimize(scenario, algorithm, budget);
      const res = await followJob<OptResult>(job.id, (ev) => {
        if (ev.type === "progress") {
          setProgress((ev.nfe as number) / (ev.budget as number));
          setLive(ev.front as number[][]);
          setFeasibleSoFar(Boolean(ev.feasible));
        }
      });
      setResult(res);
      const k = res.picks.balanced;
      setSelected({ genes: res.solutions[k].genes, plan: { ...res.recommended, explanation: res.explanation }, label: PICK_LABEL.balanced });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
      setProgress(1);
    }
  };

  const choose = async (i: number, label: string) => {
    if (!result || !scenario) return;
    try {
      const plan = await api.evaluate(scenario, result.solutions[i].genes);
      setSelected({ genes: result.solutions[i].genes, plan, label });
    } catch (e) { setError((e as Error).message); }
  };

  const points = useMemo(() => (result ? result.solutions.map((s) => objs.map((o) => s.objectives[o])) : live), [result, live, objs]);
  const baselines = network ? [
    { name: "Current practice", o: network.baselines.current_practice.objectives, symbol: "x" },
    { name: "Slow steaming (VLSFO)", o: network.baselines.slow_steaming.objectives, symbol: "diamond" },
  ] : [];
  const knee = result ? result.picks.balanced : -1;
  const hasCost = ix("cost") >= 0 && ix("emissions") >= 0;
  const colorObj = objs.includes("fuel") ? "fuel" : objs.find((o) => o !== "emissions" && o !== "cost") ?? "fuel";

  const scatter2d: any[] = hasCost ? [
    {
      type: "scatter", mode: "markers", name: result ? "Pareto-optimal plans (click one)" : "Current front",
      x: points.map((p) => p[ix("emissions")] / 1000), y: points.map((p) => p[ix("cost")]),
      marker: {
        size: 9, line: { color: t["surface-1"], width: 2 },
        color: points.map((p) => p[ix(colorObj)] ?? 0), colorscale: [[0, t["seq-100"]], [0.5, t["seq-300"]], [1, t["seq-700"]]],
        colorbar: { title: { text: OBJ_SHORT[colorObj], font: { size: 11 } }, thickness: 10, len: 0.8, tickfont: { size: 10 } },
      },
      customdata: points.map((p, i) => [i, p[ix(colorObj)] ?? 0]),
      hovertemplate: `GHG %{x:,.0f} kt · cost %{y:,.1f} M$<br>${OBJ_SHORT[colorObj]} %{customdata[1]:,.0f}<extra></extra>`,
    },
    ...(knee >= 0 ? [{
      type: "scatter", mode: "markers+text", name: "Recommended (knee)", x: [points[knee][ix("emissions")] / 1000], y: [points[knee][ix("cost")]],
      marker: { size: 16, color: "rgba(0,0,0,0)", line: { color: t.accent, width: 2.5 } },
      text: ["Recommended"], textposition: "top center", textfont: { color: t["text-primary"], size: 11 }, hoverinfo: "skip",
    }] : []),
    ...baselines.map((b) => ({
      type: "scatter", mode: "markers+text", name: b.name, x: [b.o.emissions / 1000], y: [b.o.cost],
      marker: { size: 11, symbol: b.symbol, color: t["text-muted"], line: { color: t["surface-1"], width: 1 } },
      text: [b.name], textposition: "bottom center", textfont: { color: t["text-secondary"], size: 11 },
      hovertemplate: `${b.name}<br>GHG %{x:,.0f} kt · cost %{y:,.1f} M$<extra></extra>`,
    })),
  ] : [];

  const scatter3d: any[] = objs.length >= 3 ? [{
    type: "scatter3d", mode: "markers", name: "Pareto front",
    x: points.map((p) => p[0]), y: points.map((p) => p[1]), z: points.map((p) => p[2]),
    marker: { size: 4, color: t["series-1"], line: { color: t["surface-1"], width: 1 } },
    customdata: points.map((_, i) => [i]),
    hovertemplate: `${OBJ_SHORT[objs[0]]} %{x:,.0f}<br>${OBJ_SHORT[objs[1]]} %{y:,.0f}<br>${OBJ_SHORT[objs[2]]} %{z:,.1f}<extra></extra>`,
  }] : [];

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="page-head">
        <div>
          <h1>Fleet optimizer</h1>
          <p>Choose vessel mix, capacity, speed, fuel and shore power for every service, minimising fuel, well-to-wake
            emissions and cost under demand, schedule, fleet, CII and FuelEU constraints.</p>
        </div>
      </div>
      <ScenarioPanel />
      <div className="card">
        <div className="filters">
          <label className="field">Algorithm
            <select value={algorithm} onChange={(e) => setAlgorithm(e.target.value)}>
              {meta && Object.entries(meta.algorithms).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="field">Evaluation budget
            <select value={budget} onChange={(e) => setBudget(Number(e.target.value))}>
              {[2000, 4000, 6000, 10000, 20000].map((b) => <option key={b} value={b}>{fmt(b)} fleet plans</option>)}
            </select>
          </label>
          <button className="btn primary" onClick={run} disabled={running || !scenario} style={{ height: 36 }}>
            {running ? "Optimizing…" : "Run optimization"}
          </button>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div className="range-row"><span>{running ? (feasibleSoFar ? "searching the Pareto front" : "looking for feasible plans") : result ? `${result.solutions.length} Pareto-optimal plans · ${fmt(result.evaluations)} evaluated` : "idle"}</span>
              <span className="num">{Math.round(progress * 100)}%</span></div>
            <div className="progress"><div style={{ width: `${progress * 100}%` }} /></div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div><h3>Trade-off: emissions vs cost</h3>
            <p className="muted small">Each dot is a complete fleet plan that no other plan beats on every objective. Colour = {OBJ_SHORT[colorObj].toLowerCase()} ({OBJ_UNITS[colorObj]}).</p></div>
          <div className="segmented">
            <button className={view === "2d" ? "on" : ""} onClick={() => setView("2d")}>2-D</button>
            <button className={view === "3d" ? "on" : ""} onClick={() => setView("3d")}>3-D</button>
          </div>
        </div>
        {points.length === 0 ? (
          <div className="empty">Run the optimizer to watch the Pareto front emerge live.<br />The grey markers show today's reference plans.</div>
        ) : view === "2d" ? (
          <Plot ariaLabel="Pareto front of emissions versus cost" height={420} data={scatter2d}
            onClick={(e) => {
              const pt = e.points?.[0];
              if (pt && pt.curveNumber === 0 && result) choose(pt.customdata[0], `Plan #${pt.customdata[0] + 1}`);
            }}
            layout={{ xaxis: { title: { text: "Well-to-wake GHG (kt CO₂e / yr)" } }, yaxis: { title: { text: "Annual cost (M USD)" } }, showlegend: true }} />
        ) : (
          <Plot ariaLabel="3-D Pareto front" height={460} data={scatter3d}
            onClick={(e) => { const pt = e.points?.[0]; if (pt && result) choose(pt.customdata[0], `Plan #${pt.customdata[0] + 1}`); }}
            layout={{ margin: { l: 0, r: 0, t: 0, b: 0 }, scene: {
              xaxis: { title: { text: OBJ_SHORT[objs[0]] } }, yaxis: { title: { text: OBJ_SHORT[objs[1]] } }, zaxis: { title: { text: OBJ_SHORT[objs[2]] } } } }} />
        )}
        {result && (
          <div className="btn-row" style={{ marginTop: 8 }}>
            <span className="small muted">Jump to:</span>
            {Object.entries(result.picks).map(([k, i]) => (
              <button key={k} className="btn" onClick={() => choose(i, PICK_LABEL[k] ?? k)}>{PICK_LABEL[k] ?? k}</button>
            ))}
          </div>
        )}
      </div>

      {selected && scenario && (
        <PlanDetails plan={selected.plan} genes={selected.genes} scenario={scenario} network={network} meta={meta}
          label={selected.label} algorithm={result?.algorithm} />
      )}
    </div>
  );
}
