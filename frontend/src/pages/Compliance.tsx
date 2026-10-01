import Plot from "../components/Plot";
import { useMoney } from "../lib/currency";
import { fmt } from "../lib/format";
import { useStore } from "../lib/store";
import { useTheme } from "../lib/theme";

export default function Compliance() {
  const { selected, meta, network, scenario } = useStore();
  const t = useTheme();
  const money = useMoney();
  const plan = selected?.plan;
  if (!plan || !meta || !scenario) return <div className="empty">Select a plan in the optimizer first.</div>;
  const fe = plan.fleet.fueleu;
  const routes = plan.routes;
  const ciiYears = Object.keys(meta.regulations.cii_reduction_pct).map(Number);
  const feYears = Object.keys(meta.regulations.fueleu_targets).map(Number);
  const etsTotal = routes.reduce((a, r) => a + r.cost_usd.eu_ets, 0);

  return (
    <div className="grid page">
      <div className="page-head"><div><span className="kicker">IMO CII · FuelEU Maritime · EU ETS</span><h1>Regulatory compliance</h1>
        <p>{selected!.label} in {scenario.year}: IMO Carbon Intensity Indicator per ship, FuelEU Maritime pooled GHG intensity and EU ETS exposure.</p></div></div>

      <div className="grid cols-3">
        <div className="card stat">
          <span className="label">IMO CII (≥ {scenario.cii_min_rating} required)</span>
          <span className="value">{routes.filter((r) => r.cii.rating <= scenario.cii_min_rating).length} / {routes.length}</span>
          <span className="unit">services compliant · {["A", "B", "C", "D", "E"].map((k) => `${k}×${routes.filter((r) => r.cii.rating === k).length}`).join(" ")}</span>
        </div>
        <div className="card stat">
          <span className="label">FuelEU pool intensity</span>
          <span className="value">{fe.in_scope_energy_gj > 0 ? `${fe.intensity_g_per_mj.toFixed(1)}` : "n/a"}</span>
          <span className="unit">gCO₂e/MJ vs target {fe.target_g_per_mj.toFixed(1)} · balance {fmt(fe.balance_t_co2e)} t · penalty {money.big(fe.penalty_usd / 1e6)}</span>
          <span className="status"><span className="dot" style={{ background: fe.balance_t_co2e >= 0 ? t.good : t.critical }} />{fe.balance_t_co2e >= 0 ? "Compliant" : "Deficit"}</span>
        </div>
        <div className="card stat">
          <span className="label">EU ETS cost</span>
          <span className="value">{money.big(etsTotal / 1e6)}</span>
          <span className="unit">per year · CH₄ and N₂O included from 2026</span>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><div><h3>CII: attained ÷ required per service</h3><p className="muted small">Below 1.0 beats the required line; rating boundaries follow IMO dd-vectors per ship type (hover for rating).</p></div></div>
        <Plot ariaLabel="CII ratio per route" height={340} data={[{
          type: "bar", x: routes.map((r) => r.route_id), y: routes.map((r) => r.cii.ratio), width: 0.3,
          marker: { color: routes.map((r) => ({ A: t.good, B: t.good, C: t.warning, D: t.serious, E: t.critical } as Record<string, string>)[r.cii.rating]) },
          text: routes.map((r) => r.cii.rating), textposition: "outside", textfont: { color: t["text-secondary"] }, cliponaxis: false,
          customdata: routes.map((r) => [r.name, r.vessel_label, r.cii.attained.toFixed(2), r.cii.required.toFixed(2)]),
          hovertemplate: "%{customdata[0]}<br>%{customdata[1]}<br>attained %{customdata[2]} vs required %{customdata[3]} g/(cap·nm)<extra>rating %{text}</extra>",
        }]} layout={{ yaxis: { title: { text: "attained / required" }, rangemode: "tozero" }, showlegend: false,
          shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 1, y1: 1, line: { color: t["text-muted"], width: 1 } }],
          annotations: [{ xref: "paper", x: 1, y: 1, text: "required", showarrow: false, xanchor: "right", yanchor: "bottom", font: { size: 10, color: t["text-muted"] } }] }} />
        <p className="small muted">Status colours always appear with the rating letter, never on their own.</p>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-head"><h3>FuelEU Maritime GHG-intensity limit</h3><span className="muted small">gCO₂e / MJ, well-to-wake</span></div>
          <Plot ariaLabel="FuelEU targets" height={280} data={[
            { type: "scatter", mode: "lines", line: { shape: "hv", color: t["neutral-series"], width: 2 }, name: "limit",
              x: [...feYears, 2051], y: [...feYears.map((y) => meta.regulations.fueleu_targets[y]), meta.regulations.fueleu_targets[2050]],
              hovertemplate: "%{x}: %{y:.1f}<extra>limit</extra>" },
            ...(fe.in_scope_energy_gj > 0 ? [{ type: "scatter" as const, mode: "markers" as const, name: "this plan", x: [scenario.year], y: [fe.intensity_g_per_mj],
              marker: { size: 11, color: t["series-1"], line: { color: t["surface-1"], width: 2 } }, hovertemplate: "plan: %{y:.1f}<extra></extra>" }] : []),
          ]} layout={{ yaxis: { title: { text: "gCO₂e / MJ" }, rangemode: "tozero" }, xaxis: { title: { text: "year" } } }} />
        </div>
        <div className="card">
          <div className="card-head"><h3>CII reduction factor Z</h3><span className="muted small">% below the 2019 reference (MEPC.338 / MEPC.400)</span></div>
          <Plot ariaLabel="CII reduction factors" height={280} data={[{
            type: "scatter", mode: "lines+markers", line: { shape: "hv", color: t["series-1"], width: 2 }, marker: { size: 8, line: { color: t["surface-1"], width: 2 } },
            x: ciiYears, y: ciiYears.map((y) => meta.regulations.cii_reduction_pct[y]), hovertemplate: "%{x}: %{y:.3f}%<extra></extra>", name: "Z",
          }]} layout={{ yaxis: { title: { text: "Z (%)" }, rangemode: "tozero" }, xaxis: { title: { text: "year" } }, showlegend: false }} />
          <p className="note">After 2030 the optimizer extrapolates at the 2027–2030 slope (assumption, not yet set by IMO).</p>
        </div>
      </div>
      {network && <p className="note">Grid electricity for shore power is counted at the local grid factor in the WtW objective, and as zero-emission in FuelEU (as the regulation prescribes).</p>}
    </div>
  );
}
