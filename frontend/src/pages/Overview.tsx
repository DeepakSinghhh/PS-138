import { Link } from "react-router-dom";
import FleetMap from "../components/FleetMap";
import Stat from "../components/Stat";
import { compact, fmt } from "../lib/format";
import { useStore } from "../lib/store";

export default function Overview() {
  const { network, meta, selected, result, scenario } = useStore();
  const plan = selected?.plan;
  const ex = plan?.explanation;
  const base = network?.baselines.current_practice;
  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="page-head">
        <div>
          <h1>{network?.name ?? "Loading…"} · {scenario?.year}</h1>
          <p>Quantum-inspired decision support for green fleet deployment: predict fuel use, then choose vessel mix,
            capacity, speed, fuel and shore power per service to cut fuel, lifecycle emissions and cost.</p>
        </div>
        <Link to="/optimize" className="btn primary">{result ? "Back to optimizer" : "Optimize this fleet"}</Link>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 2fr)" }}>
        <div className="card" style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 8 }}>
          {ex ? (
            <>
              <span className="secondary">{selected?.label}: well-to-wake GHG vs current practice</span>
              <span className="hero">{ex.delta_pct.emissions > 0 ? "+" : ""}{ex.delta_pct.emissions.toFixed(0)}%</span>
              <span className="secondary">fuel {ex.delta_pct.fuel.toFixed(0)}% · cost {ex.delta_pct.cost > 0 ? "+" : ""}{ex.delta_pct.cost.toFixed(0)}% ·
                {" "}{plan!.fleet.ships} ships · {plan!.feasible ? "all constraints met" : "constraints violated"}</span>
            </>
          ) : (
            <>
              <span className="secondary">Current practice emits (well-to-wake)</span>
              <span className="hero">{base ? compact(base.objectives.emissions) : "–"}</span>
              <span className="secondary">t CO₂e per year · {base ? fmt(base.objectives.cost, 0) : "–"} M USD · {base?.fleet.ships ?? "–"} ships.
                Run the optimizer to find better plans.</span>
            </>
          )}
        </div>
        <div className="grid cols-3">
          <Stat label="Services" value={String(network?.routes.length ?? "–")} unit={`${fmt(network?.routes.reduce((a, r) => a + r.distance_nm, 0))} nm of sea routes`} />
          <Stat label="FuelEU target" value={network ? network.fueleu_target.toFixed(1) : "–"} unit="gCO₂e / MJ (well-to-wake)" />
          <Stat label="CII reduction" value={network ? `${network.cii_reduction_pct.toFixed(1)}%` : "–"} unit="below the 2019 reference line" />
          <Stat label="EU ETS price" value={network ? `$${fmt(network.prices.ets_usd_per_t)}` : "–"} unit="per t CO₂e" />
          <Stat label="VLSFO" value={network ? `$${fmt(network.prices.fuel_usd_per_t.VLSFO)}` : "–"} unit="per tonne" />
          <Stat label="e-Ammonia" value={network ? `$${fmt(network.prices.fuel_usd_per_t.AMMONIA_E)}` : "–"} unit="per tonne" />
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
                  <td className="n">{fmt(r.distance_nm)}</td><td>{r.classes.join(", ")}</td>
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
