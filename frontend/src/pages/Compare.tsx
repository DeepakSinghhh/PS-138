import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Plot from "../components/Plot";
import { useMoney } from "../lib/currency";
import { useT } from "../lib/i18n";
import { compact, fmt, pct } from "../lib/format";
import { describeScenario, useSaved, type SavedPlan } from "../lib/saved";
import { useStore } from "../lib/store";
import { FAMILY_LABEL, familyColor, useTheme } from "../lib/theme";
import type { Meta, Plan, RoutePlan } from "../lib/types";

const FAMILIES = ["conventional", "lng", "methanol", "ammonia", "hydrogen"];

/** Energy share per fuel family (pilot fuel counts as conventional). */
function familyShares(plan: Plan, meta: Meta | null): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [fid, share] of Object.entries(plan.fleet.fuel_mix_energy_share)) {
    const fam = meta?.fuels.find((f) => f.id === fid)?.family ?? "conventional";
    out[fam] = (out[fam] ?? 0) + share;
  }
  return out;
}

const ciiOk = (p: Plan) => p.routes.filter((r) => "ABC".includes(r.cii.rating)).length;
const routeCost = (r: RoutePlan) => Object.values(r.cost_usd).reduce((a, b) => a + b, 0);
/** "+1,234" / "−56" / "0": rounded first, so tiny differences never show as "-0" */
const signed = (v: number, digits: number) => {
  const r = Number(v.toFixed(digits));
  return r === 0 ? "0" : `${r > 0 ? "+" : "−"}${fmt(Math.abs(r), digits)}`;
};
const summary = (r?: RoutePlan) => (r ? `${r.ships} × ${r.vessel_label.split(" (")[0]} · ${r.speed_kn.toFixed(1)} kn · ${r.fuel_label}${r.shore_power ? " · shore power" : ""}` : "–");

export default function Compare() {
  const { saved, remove, rename } = useSaved();
  const { meta, setScenario, setSelected } = useStore();
  const money = useMoney();
  const t = useTheme();
  const navigate = useNavigate();
  const tr = useT();
  const [aId, setA] = useState<string | null>(null);
  const [bId, setB] = useState<string | null>(null);
  // default pair: the two most recently saved plans (older = A, newer = B)
  const A = saved.find((p) => p.id === aId) ?? saved[1] ?? null;
  const B = saved.find((p) => p.id === bId) ?? (saved[0] && saved[0].id !== A?.id ? saved[0] : saved[1]) ?? null;

  const open = (p: SavedPlan) => {
    setScenario(p.scenario);
    setSelected({ genes: p.genes, plan: p.plan, label: p.label });
    navigate("/optimize");
  };

  const rows = useMemo(() => {
    if (!A || !B) return [];
    const ids = Array.from(new Set([...A.plan.routes, ...B.plan.routes].map((r) => r.route_id))).sort();
    return ids.map((id) => {
      const ra = A.plan.routes.find((r) => r.route_id === id), rb = B.plan.routes.find((r) => r.route_id === id);
      const same = !!ra && !!rb && ra.vessel_class === rb.vessel_class && ra.ships === rb.ships && ra.fuel === rb.fuel
        && ra.shore_power === rb.shore_power && Math.abs(ra.speed_kn - rb.speed_kn) < 0.05;
      return { id, name: (ra ?? rb)!.name, ra, rb, same, dGhg: ra && rb ? rb.wtw_co2e_t - ra.wtw_co2e_t : null };
    });
  }, [A, B]);

  // lowerIsBetter: true / false colours the change; null leaves it neutral (e.g. ship count)
  const metric = (label: string, a: number, b: number, show: (v: number) => string, lowerIsBetter: boolean | null = true) => {
    const d = a ? (100 * (b - a)) / Math.abs(a) : null;
    const better = d === null || Math.abs(d) < 0.05 || lowerIsBetter === null ? null : (d < 0) === lowerIsBetter;
    return (
      <tr key={label}>
        <td>{label}</td><td className="n">{show(a)}</td><td className="n">{show(b)}</td>
        <td className="n">{d === null ? "–" : <span className={better === null ? "muted" : `delta ${better ? "good" : "bad"}`}>{pct(d)}</span>}</td>
      </tr>
    );
  };

  return (
    <div className="grid page">
      <div className="page-head">
        <div>
          <span className="kicker">{tr("Plans · scenarios · trade-offs")}</span>
          <h1>{tr("Compare plans")}</h1>
          <p>{tr("Save any plan from the optimizer, then put two side by side: the same network under different scenarios (a Red Sea closure, a higher carbon price) or two points on one trade-off curve.")}</p>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h3>{tr("Saved plans")}</h3><span className="muted small">kept in this browser · {saved.length} of 12</span></div>
        {saved.length === 0 ? (
          <div className="empty">No saved plans yet. In the Fleet optimizer, pick a plan and press “Save plan”, then change the
            scenario, optimise again and save a second one.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>A</th><th>B</th><th>Plan</th><th>Scenario</th><th className="n">Fuel t</th><th className="n">GHG t CO₂e</th>
                <th className="n">Cost {money.bigUnit}</th><th className="n">Ships</th><th>Saved</th><th /></tr></thead>
              <tbody>
                {saved.map((p) => (
                  <tr key={p.id} className={p.id === A?.id || p.id === B?.id ? "mark" : undefined}>
                    <td><input type="radio" name="pick-a" aria-label={`Use ${p.label} as plan A`} checked={p.id === A?.id} onChange={() => setA(p.id)} /></td>
                    <td><input type="radio" name="pick-b" aria-label={`Use ${p.label} as plan B`} checked={p.id === B?.id} onChange={() => setB(p.id)} /></td>
                    <td className="wrap">
                      <input type="text" className="inline-edit" value={p.label} aria-label="Plan name"
                        onChange={(e) => rename(p.id, e.target.value)} />
                    </td>
                    <td className="wrap small">{describeScenario(p.scenario, meta?.networks)}</td>
                    <td className="n">{compact(p.plan.objectives.fuel)}</td>
                    <td className="n">{compact(p.plan.objectives.emissions)}</td>
                    <td className="n">{fmt(money.bigValue(p.plan.objectives.cost), money.inr ? 0 : 1)}</td>
                    <td className="n">{p.plan.fleet.ships}</td>
                    <td className="small muted">{new Date(p.savedAt).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })}</td>
                    <td><div className="btn-row" style={{ flexWrap: "nowrap" }}>
                      <button className="btn" onClick={() => open(p)}>Open</button>
                      <button className="btn" aria-label={`Delete ${p.label}`} onClick={() => remove(p.id)}>Delete</button>
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {A && B && A.id !== B.id ? (
        <>
          <div className="grid cols-2">
            <div className="card">
              <div className="card-head"><h3>{tr("Side by side")}</h3><span className="muted small">B relative to A</span></div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th /><th className="n">A · {A.label}</th><th className="n">B · {B.label}</th><th className="n">B vs A</th></tr></thead>
                  <tbody>
                    {metric("Fuel, t HFO-eq / yr", A.plan.objectives.fuel, B.plan.objectives.fuel, (v) => fmt(v))}
                    {metric("Well-to-wake GHG, t CO₂e / yr", A.plan.objectives.emissions, B.plan.objectives.emissions, (v) => fmt(v))}
                    {metric("Annual cost", A.plan.objectives.cost, B.plan.objectives.cost, (v) => money.big(v))}
                    {metric("Ships", A.plan.fleet.ships, B.plan.fleet.ships, (v) => fmt(v), null)}
                    {metric("Services with CII ≥ C", ciiOk(A.plan), ciiOk(B.plan), (v) => fmt(v), false)}
                    {metric("Services on shore power", A.plan.fleet.shore_power_routes, B.plan.fleet.shore_power_routes, (v) => fmt(v), false)}
                    {metric("FuelEU penalty", A.plan.fleet.fueleu.penalty_usd / 1e6, B.plan.fleet.fueleu.penalty_usd / 1e6, (v) => money.big(v))}
                    <tr><td>All constraints met</td><td className="n">{A.plan.feasible ? "yes" : "no"}</td><td className="n">{B.plan.feasible ? "yes" : "no"}</td><td /></tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div className="card">
              <div className="card-head"><h3>{tr("Fuel mix")}</h3><span className="muted small">share of fleet energy</span></div>
              <Plot ariaLabel="Fuel mix of plan A and plan B" height={250} config={{ displayModeBar: false }}
                data={FAMILIES.filter((f) => (familyShares(A.plan, meta)[f] ?? 0) + (familyShares(B.plan, meta)[f] ?? 0) > 0.001).map((f) => ({
                  type: "bar", orientation: "h", name: FAMILY_LABEL[f] ?? f, marker: { color: familyColor(t, f), line: { color: t["surface-1"], width: 2 } },
                  y: [`B · ${B.label}`, `A · ${A.label}`],
                  x: [100 * (familyShares(B.plan, meta)[f] ?? 0), 100 * (familyShares(A.plan, meta)[f] ?? 0)],
                  hovertemplate: `%{y}: %{x:.1f}% ${FAMILY_LABEL[f] ?? f}<extra></extra>`,
                }))}
                layout={{ barmode: "stack", xaxis: { range: [0, 100], title: { text: "% of energy" } }, margin: { l: 150, r: 16, t: 8, b: 44 },
                  legend: { orientation: "h", y: -0.45 }, bargap: 0.45 }} />
              <p className="note">Scenario A: {describeScenario(A.scenario, meta?.networks)}<br />Scenario B: {describeScenario(B.scenario, meta?.networks)}</p>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>{tr("Route by route")}</h3><span className="muted small">{rows.filter((r) => !r.same).length} of {rows.length} services differ</span></div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Route</th><th>Service</th><th>A</th><th>B</th><th className="n">Δ GHG t CO₂e</th><th className="n">Δ cost {money.bigUnit}</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className={r.same ? undefined : "mark"}>
                      <td><b>{r.id}</b></td><td className="wrap">{r.name}</td>
                      <td className="wrap small">{summary(r.ra)}</td><td className="wrap small">{summary(r.rb)}</td>
                      <td className="n">{r.dGhg === null ? "–" : signed(r.dGhg, 0)}</td>
                      <td className="n">{r.ra && r.rb ? signed(money.bigValue((routeCost(r.rb) - routeCost(r.ra)) / 1e6), money.inr ? 0 : 2) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="note">Marked rows are services where the vessel class, number of ships, speed, fuel or shore power differ.</p>
          </div>
        </>
      ) : saved.length === 1 ? (
        <div className="empty">Save one more plan to compare.</div>
      ) : null}
    </div>
  );
}
