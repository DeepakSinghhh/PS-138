import { Link } from "react-router-dom";
import FleetMap from "../components/FleetMap";
import Stat from "../components/Stat";
import { startTour } from "../components/Tour";
import { useMoney } from "../lib/currency";
import { fmt } from "../lib/format";
import { useStore } from "../lib/store";

export default function Overview() {
  const { network, meta, selected, result, scenario } = useStore();
  const money = useMoney();
  const plan = selected?.plan;
  const ex = plan?.explanation;
  const base = network?.baselines.current_practice;
  return (
    <div className="grid page">
      <div className="page-head">
        <div>
          <span className="kicker">Scenario overview · {scenario?.year}</span>
          <h1>{network?.name ?? "Loading…"}</h1>
          <p>Quantum-inspired decision support for green fleet deployment: predict fuel use, then choose vessel mix,
            capacity, speed, fuel and shore power per service to cut fuel, lifecycle emissions and cost.</p>
        </div>
        <div className="head-actions">
          <button className="btn" onClick={startTour}>Take the 2-minute tour</button>
          <Link to="/optimize" className="btn primary">{result ? "Back to optimizer" : "Optimize this fleet"}</Link>
        </div>
      </div>

      <div className="grid split-hero">
        <div className="card hero-card" style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 6 }}>
          {ex ? (
            <>
              <span className="kicker">{selected?.label} · emissions vs today</span>
              <span className="hero accent">{ex.delta_pct.emissions > 0 ? "+" : "−"}{Math.abs(ex.delta_pct.emissions).toFixed(0)}%<small>well-to-wake GHG</small></span>
              <span className="secondary">fuel {ex.delta_pct.fuel.toFixed(0)}% · cost {ex.delta_pct.cost > 0 ? "+" : ""}{ex.delta_pct.cost.toFixed(0)}% ·
                {" "}{plan!.fleet.ships} ships · {plan!.feasible ? "all constraints met" : "constraints violated"}</span>
            </>
          ) : (
            <>
              <span className="kicker">Current practice · well-to-wake emissions</span>
              <span className="hero">{base ? (base.objectives.emissions / 1e6).toFixed(2) : "–"}<small>Mt CO₂e / yr</small></span>
              <span className="secondary">{base ? money.big(base.objectives.cost) : "–"} a year · {base?.fleet.ships ?? "–"} ships.
                Run the optimizer to find better plans.</span>
            </>
          )}
        </div>
        <div className="grid cols-3">
          <Stat label="Services" value={String(network?.routes.length ?? "–")} unit={`${fmt(network?.routes.reduce((a, r) => a + r.distance_nm, 0))} nm of sea routes`} />
          <Stat label="FuelEU target" value={network ? network.fueleu_target.toFixed(1) : "–"} unit="gCO₂e / MJ (well-to-wake)" />
          <Stat label="CII reduction" value={network ? `${network.cii_reduction_pct.toFixed(1)}%` : "–"} unit="below the 2019 reference line" />
          <Stat label="EU ETS price" value={network ? money.unit(network.prices.ets_usd_per_t) : "–"} unit="per t CO₂e" />
          <Stat label="VLSFO" value={network ? money.unit(network.prices.fuel_usd_per_t.VLSFO) : "–"} unit="per tonne" />
          <Stat label="e-Ammonia" value={network ? money.unit(network.prices.fuel_usd_per_t.AMMONIA_E) : "–"} unit="per tonne" />
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h3>Network {plan ? `· ${selected?.label}` : ""}</h3>
          {network?.notes.map((n) => <span key={n} className="chip">{n}</span>)}</div>
        <FleetMap network={network} plan={plan} meta={meta} height={440} />
      </div>

      <div className="card">
        <div className="card-head"><h3>Services</h3><span className="muted small">fuels bunkerable within range in {scenario?.year}</span></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>Service</th><th>Type</th><th className="n">Demand</th><th className="n">Distance nm</th>
              <th>Vessel classes</th><th>Fuels available</th><th className="n">Shore power</th><th className="n">EU scope</th></tr></thead>
            <tbody>
              {network?.routes.map((r) => (
                <tr key={r.id}>
                  <td><b>{r.id}</b></td><td>{r.name}</td><td>{r.service} · {r.cargo}</td>
                  <td className="n">{fmt(r.demand)} {r.cargo === "container" ? "TEU" : r.cargo === "pax" ? "pax" : "t"}<span className="muted"> {r.demand_unit}</span></td>
                  <td className="n">{fmt(r.distance_nm)}</td>
                  <td className="wrap">{r.classes.map((c) => (meta?.vessel_classes.find((v) => v.id === c)?.label ?? c).split(" (")[0]).join(", ")}</td>
                  <td title={r.fuels.map((f) => f.label).join(", ")}>{r.fuels.length} fuels</td>
                  <td className="n">{r.shore_power_share ? `${Math.round(r.shore_power_share * 100)}% of berths` : "–"}</td>
                  <td className="n">{r.eu_scope ? `${r.eu_scope * 100}%` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
