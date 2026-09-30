import { useState } from "react";
import Plot from "./Plot";
import Stat from "./Stat";
import FleetMap from "./FleetMap";
import { downloadReport } from "../lib/api";
import { compact, fmt, pct } from "../lib/format";
import { FAMILY_LABEL, familyColor, useTheme } from "../lib/theme";
import type { Genes, Meta, NetworkInfo, Plan, Scenario } from "../lib/types";

interface Props {
  plan: Plan; genes: Genes; scenario: Scenario; network: NetworkInfo | null; meta: Meta | null;
  label: string; algorithm?: string;
}

export default function PlanDetails({ plan, genes, scenario, network, meta, label, algorithm }: Props) {
  const t = useTheme();
  const [busy, setBusy] = useState(false);
  const ex = plan.explanation;
  const d = ex?.delta_pct ?? {};
  const routes = [...plan.routes].sort((a, b) => b.wtw_co2e_t - a.wtw_co2e_t);
  const fe = plan.fleet.fueleu;
  const ratings = plan.routes.map((r) => r.cii.rating);
  const families = Array.from(new Set(plan.routes.map((r) => r.fuel_family)));

  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="card-head" style={{ marginBottom: 0 }}>
        <div>
          <h2>{label}</h2>
          <p className="muted small">{plan.fleet.ships} ships on {plan.routes.length} services · {plan.feasible
            ? "all constraints satisfied" : `violates: ${Object.entries(plan.violations).filter(([, v]) => v > 0).map(([k]) => k).join(", ")}`}</p>
        </div>
        <button className="btn primary" disabled={busy} onClick={async () => {
          setBusy(true);
          try { await downloadReport(scenario, genes, algorithm); } finally { setBusy(false); }
        }}>{busy ? "Building report…" : "Download decision report"}</button>
      </div>

      <div className="grid cols-4">
        <Stat label="Fuel" value={compact(plan.objectives.fuel)} unit="t HFO-eq / yr" delta={d.fuel} />
        <Stat label="Well-to-wake GHG" value={compact(plan.objectives.emissions)} unit="t CO₂e / yr" delta={d.emissions} />
        <Stat label="Annual cost" value={fmt(plan.objectives.cost, 1)} unit="M USD / yr" delta={d.cost} />
        <div className="card stat">
          <span className="label">Compliance</span>
          <span className="value" style={{ fontSize: 20 }}>{ratings.filter((r) => "ABC".includes(r)).length}/{ratings.length} CII ≥ C</span>
          <span className="status">
            <span className="dot" style={{ background: fe.balance_t_co2e >= 0 ? t.good : t.critical }} />
            FuelEU {fe.in_scope_energy_gj > 0 ? (fe.balance_t_co2e >= 0 ? "compliant (pool surplus)" : `deficit · penalty $${compact(fe.penalty_usd)}`) : "not in scope"}
          </span>
        </div>
      </div>

      {ex && (
        <div className="explain">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{ex.sentences.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </div>
      )}

      <div className="grid cols-2">
        <div className="card">
          <div className="card-head"><h3>Fleet allocation map</h3><span className="muted small">hover a route for details</span></div>
          <FleetMap network={network} plan={plan} meta={meta} height={380} />
        </div>
        <div className="card">
          <div className="card-head"><h3>Emission profile by service</h3><span className="muted small">t CO₂e / yr, well-to-wake</span></div>
          <Plot ariaLabel="Well-to-wake emissions per route" height={380}
            data={families.map((f) => {
              const rs = routes.filter((r) => r.fuel_family === f);
              return {
                type: "bar", orientation: "h", name: FAMILY_LABEL[f] ?? f,
                y: rs.map((r) => `${r.route_id} ${r.name.slice(0, 22)}`), x: rs.map((r) => r.wtw_co2e_t),
                marker: { color: familyColor(t, f) }, width: 0.6,
                text: rs.map((r) => compact(r.wtw_co2e_t)), textposition: "outside", textfont: { color: t["text-secondary"], size: 11 },
                cliponaxis: false,
                customdata: rs.map((r) => [r.fuel_label, r.ships, r.speed_kn.toFixed(1)]),
                hovertemplate: "%{y}<br>%{x:,.0f} t CO₂e · %{customdata[0]}<br>%{customdata[1]} ships @ %{customdata[2]} kn<extra></extra>",
              };
            })}
            layout={{
              barmode: "overlay", margin: { l: 190, r: 50, t: 8, b: 40 }, showlegend: true,
              yaxis: { categoryorder: "array", categoryarray: [...routes].reverse().map((r) => `${r.route_id} ${r.name.slice(0, 22)}`), gridcolor: "rgba(0,0,0,0)" },
              xaxis: { title: { text: "t CO₂e / yr" } },
            }} />
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h3>Fleet allocation</h3><span className="muted small">vessel mix, capacity, speed and fuel per service</span></div>
        <div className="table-wrap">
          <table>
            <thead><tr>
              <th>Route</th><th>Service</th><th>Vessel class</th><th className="n">Ships</th><th className="n">Speed kn</th>
              <th>Fuel</th><th>Shore power</th><th className="n">Fuel t HFO-eq</th><th className="n">WtW t CO₂e</th>
              <th className="n">Cost M$</th><th>CII</th><th className="n">On time</th>
            </tr></thead>
            <tbody>
              {plan.routes.map((r) => (
                <tr key={r.route_id}>
                  <td><b>{r.route_id}</b></td>
                  <td className="wrap">{r.name}</td>
                  <td className="wrap">{r.vessel_label}</td>
                  <td className="n">{r.ships}{r.ships > r.min_ships ? <span className="muted"> (+{r.ships - r.min_ships})</span> : null}</td>
                  <td className="n" title={`feasible range ${r.speed_range_kn[0].toFixed(1)}–${r.speed_range_kn[1].toFixed(1)} kn`}>{r.speed_kn.toFixed(1)}</td>
                  <td className="wrap"><span className="chip"><i className="swatch" style={{ background: familyColor(t, r.fuel_family) }} />{r.fuel_label}</span></td>
                  <td>{r.shore_power ? "Yes" : "–"}</td>
                  <td className="n">{fmt(r.fuel_hfo_eq_t)}</td>
                  <td className="n">{fmt(r.wtw_co2e_t)}</td>
                  <td className="n">{fmt(Object.values(r.cost_usd).reduce((a, b) => a + b, 0) / 1e6, 1)}</td>
                  <td><span className={`rating ${r.cii.rating}`} title={`attained/required ${r.cii.ratio.toFixed(2)}`}>{r.cii.rating}</span></td>
                  <td className="n">{(100 * r.on_time_probability).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {ex && (
          <p className="note" style={{ marginTop: 10 }}>
            Against a slow-steaming VLSFO fleet: GHG {pct(ex.delta_pct_vs_slow_steaming.emissions)}, fuel {pct(ex.delta_pct_vs_slow_steaming.fuel)},
            cost {pct(ex.delta_pct_vs_slow_steaming.cost)}. FuelEU pool intensity {fe.intensity_g_per_mj.toFixed(1)} vs target {fe.target_g_per_mj.toFixed(1)} gCO₂e/MJ.
          </p>
        )}
      </div>
    </div>
  );
}
