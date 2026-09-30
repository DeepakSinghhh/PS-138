import { useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../lib/store";
import type { Obj } from "../lib/types";

export default function ScenarioPanel({ compact = false }: { compact?: boolean }) {
  const { scenario, patchScenario, meta, setError } = useStore();
  const [csv, setCsv] = useState("");
  const [showCsv, setShowCsv] = useState(false);
  if (!scenario || !meta) return null;
  const objs: Obj[] = ["fuel", "emissions", "cost", "schedule_risk"];
  const toggleObj = (o: Obj) => {
    const has = scenario.objectives.includes(o);
    const next = has ? scenario.objectives.filter((x) => x !== o) : [...scenario.objectives, o];
    if (next.length >= 2) patchScenario({ objectives: next });
  };

  return (
    <div className="card">
      <div className="card-head"><h3>Scenario</h3>
        {scenario.custom_routes && <span className="chip">custom network · {scenario.custom_routes.length} routes</span>}
      </div>
      <div className="filters">
        <label className="field">Network
          <select value={scenario.custom_routes ? "custom" : scenario.network}
            onChange={(e) => e.target.value !== "custom" && patchScenario({ network: e.target.value, custom_routes: null })}>
            {Object.entries(meta.networks).map(([k, v]) => <option key={k} value={k}>{v.name}</option>)}
            {scenario.custom_routes && <option value="custom">Custom (uploaded)</option>}
          </select>
        </label>
        <label className="field">Year
          <select value={scenario.year} onChange={(e) => patchScenario({ year: Number(e.target.value) })}>
            {[2025, 2026, 2027, 2028, 2030, 2032, 2035, 2040, 2045, 2050].map((y) => <option key={y}>{y}</option>)}
          </select>
        </label>
        <label className="field">EU ETS price (€/t)
          <input type="number" min={0} step={10} placeholder="auto" value={scenario.ets_price_eur ?? ""}
            onChange={(e) => patchScenario({ ets_price_eur: e.target.value === "" ? null : Number(e.target.value) })} />
        </label>
        <label className="field">Global carbon levy ($/t)
          <input type="number" min={0} step={10} placeholder="0" value={scenario.global_levy_usd ?? ""}
            onChange={(e) => patchScenario({ global_levy_usd: e.target.value === "" ? null : Number(e.target.value) })} />
        </label>
        <label className="field">Fuel price ×
          <input type="number" min={0.3} max={3} step={0.1} value={scenario.fuel_price_multiplier}
            onChange={(e) => patchScenario({ fuel_price_multiplier: Number(e.target.value) || 1 })} />
        </label>
        <label className="field">FuelEU
          <select value={scenario.fueleu_mode} onChange={(e) => patchScenario({ fueleu_mode: e.target.value as "penalty" | "hard" })}>
            <option value="penalty">pay penalty if non-compliant</option>
            <option value="hard">must comply</option>
          </select>
        </label>
        {!compact && (
          <label className="field">Min. on-time probability
            <input type="number" min={0.5} max={0.99} step={0.05} value={scenario.on_time_min}
              onChange={(e) => patchScenario({ on_time_min: Number(e.target.value) })} />
          </label>
        )}
        {!compact && (
          <label className="field">Min. CII rating
            <select value={scenario.cii_min_rating} onChange={(e) => patchScenario({ cii_min_rating: e.target.value })}>
              {["A", "B", "C", "D", "E"].map((r) => <option key={r}>{r}</option>)}
            </select>
          </label>
        )}
      </div>
      <div className="btn-row" style={{ marginTop: 12 }}>
        <label className="check"><input type="checkbox" checked={scenario.red_sea_diversion}
          onChange={(e) => patchScenario({ red_sea_diversion: e.target.checked })} />Red Sea closed (divert via Cape)</label>
        <label className="check"><input type="checkbox" checked={scenario.monsoon}
          onChange={(e) => patchScenario({ monsoon: e.target.checked })} />SW-monsoon sea state (+1 Bf)</label>
        {!compact && (
          <span className="btn-row" style={{ marginLeft: "auto" }}>
            <span className="small muted">Objectives:</span>
            {objs.map((o) => (
              <label key={o} className="check"><input type="checkbox" checked={scenario.objectives.includes(o)} onChange={() => toggleObj(o)} />
                {meta.objectives[o].split(" (")[0]}</label>
            ))}
          </span>
        )}
      </div>
      {!compact && (
        <div style={{ marginTop: 10 }}>
          <button className="btn" onClick={() => setShowCsv((s) => !s)}>{showCsv ? "Hide" : "Upload your own routes (CSV)"}</button>
          {showCsv && (
            <div className="grid" style={{ marginTop: 10 }}>
              <p className="small muted">Columns: <span className="kbd">id,name,port_a,port_b,service,cargo,demand,classes</span> ·
                ports use IDs such as JNPT, MUNDRA, SINGAPORE, ROTTERDAM · <a href="/api/routes/example.csv" target="_blank" rel="noreferrer">example file</a></p>
              <textarea rows={6} value={csv} onChange={(e) => setCsv(e.target.value)} placeholder="id,name,port_a,port_b,service,cargo,demand,classes" />
              <div className="btn-row">
                <button className="btn primary" onClick={async () => {
                  try {
                    const { routes } = await api.parseRoutes(csv);
                    patchScenario({ custom_routes: routes, network: "custom" });
                    setShowCsv(false);
                  } catch (e) { setError((e as Error).message); }
                }}>Use this network</button>
                <button className="btn" onClick={async () => setCsv(await (await fetch("/api/routes/example.csv")).text())}>Load example</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
