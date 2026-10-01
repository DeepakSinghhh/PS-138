import { useState } from "react";
import { api } from "../lib/api";
import { useMoney } from "../lib/currency";
import { useT } from "../lib/i18n";
import { shareUrl } from "../lib/share";
import { useStore } from "../lib/store";
import type { Obj } from "../lib/types";

export default function ScenarioPanel({ compact = false }: { compact?: boolean }) {
  const { scenario, patchScenario, meta, network, setError } = useStore();
  const t = useT();
  const [csv, setCsv] = useState("");
  const [showCsv, setShowCsv] = useState(false);
  const [showPrices, setShowPrices] = useState(false);
  const [copied, setCopied] = useState(false);
  if (!scenario || !meta) return null;
  const share = async () => {
    const url = shareUrl(scenario, { ...meta.default_scenario, network: "india", year: 2030 });
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy this link to share the scenario", url);
    }
  };
  const objs: Obj[] = ["fuel", "emissions", "cost", "schedule_risk"];
  const toggleObj = (o: Obj) => {
    const has = scenario.objectives.includes(o);
    const next = has ? scenario.objectives.filter((x) => x !== o) : [...scenario.objectives, o];
    if (next.length >= 2) patchScenario({ objectives: next });
  };

  return (
    <div className="card">
      <div className="card-head"><h3>{t("Scenario")}</h3>
        {scenario.custom_routes && <span className="chip">custom network · {scenario.custom_routes.length} routes</span>}
      </div>
      <div className="filters">
        <label className="field">{t("Network")}
          <select value={scenario.custom_routes ? "custom" : scenario.network}
            onChange={(e) => e.target.value !== "custom" && patchScenario({ network: e.target.value, custom_routes: null })}>
            {Object.entries(meta.networks).map(([k, v]) => <option key={k} value={k}>{t(v.name)}</option>)}
            {scenario.custom_routes && <option value="custom">Custom (uploaded)</option>}
          </select>
        </label>
        <label className="field">{t("Year")}
          <select value={scenario.year} onChange={(e) => patchScenario({ year: Number(e.target.value) })}>
            {[2025, 2026, 2027, 2028, 2030, 2032, 2035, 2040, 2045, 2050].map((y) => <option key={y}>{y}</option>)}
          </select>
        </label>
        <label className="field">{t("EU ETS price (€/t)")}
          <input type="number" min={0} step={10} placeholder="auto" value={scenario.ets_price_eur ?? ""}
            onChange={(e) => patchScenario({ ets_price_eur: e.target.value === "" ? null : Number(e.target.value) })} />
        </label>
        <label className="field">{t("Global carbon levy ($/t)")}
          <input type="number" min={0} step={10} placeholder="0" value={scenario.global_levy_usd ?? ""}
            onChange={(e) => patchScenario({ global_levy_usd: e.target.value === "" ? null : Number(e.target.value) })} />
        </label>
        <label className="field">{t("Fuel price ×")}
          <input type="number" min={0.3} max={3} step={0.1} value={scenario.fuel_price_multiplier}
            onChange={(e) => patchScenario({ fuel_price_multiplier: Number(e.target.value) || 1 })} />
        </label>
        <label className="field">FuelEU
          <select value={scenario.fueleu_mode} onChange={(e) => patchScenario({ fueleu_mode: e.target.value as "penalty" | "hard" })}>
            <option value="penalty">{t("pay penalty if non-compliant")}</option>
            <option value="hard">{t("must comply")}</option>
          </select>
        </label>
        {!compact && (
          <label className="field">{t("Min. on-time probability")}
            <input type="number" min={0.5} max={0.99} step={0.05} value={scenario.on_time_min}
              onChange={(e) => patchScenario({ on_time_min: Number(e.target.value) })} />
          </label>
        )}
        {!compact && (
          <label className="field">{t("Min. CII rating")}
            <select value={scenario.cii_min_rating} onChange={(e) => patchScenario({ cii_min_rating: e.target.value })}>
              {["A", "B", "C", "D", "E"].map((r) => <option key={r}>{r}</option>)}
            </select>
          </label>
        )}
      </div>
      <div className="btn-row" style={{ marginTop: 12 }}>
        <label className="check"><input type="checkbox" checked={scenario.red_sea_diversion}
          onChange={(e) => patchScenario({ red_sea_diversion: e.target.checked })} />{t("Red Sea closed (divert via Cape)")}</label>
        <label className="check"><input type="checkbox" checked={scenario.monsoon}
          onChange={(e) => patchScenario({ monsoon: e.target.checked })} />{t("SW-monsoon sea state (+1 Bf)")}</label>
        {!compact && (
          <span className="btn-row" style={{ marginLeft: "auto" }}>
            <span className="small muted">{t("Objectives:")}</span>
            {objs.map((o) => (
              <label key={o} className="check"><input type="checkbox" checked={scenario.objectives.includes(o)} onChange={() => toggleObj(o)} />
                {t(meta.objectives[o].split(" (")[0])}</label>
            ))}
          </span>
        )}
      </div>
      {!compact && (
        <div style={{ marginTop: 10 }}>
          <div className="head-actions">
            <button className="btn" onClick={() => setShowCsv((s) => !s)}>{showCsv ? t("Hide") : t("Upload your own routes (CSV)")}</button>
            <button className="btn" onClick={() => setShowPrices((v) => !v)}>
              {showPrices ? t("Hide fuel prices") : `${t("Fuel prices")}${Object.keys(scenario.fuel_prices).length ? ` (${Object.keys(scenario.fuel_prices).length} edited)` : ""}`}</button>
            <button className="btn" onClick={share} title="Copy a link that opens the dashboard with this scenario">{copied ? t("Link copied") : t("Copy share link")}</button>
          </div>
          {showPrices && network && <PriceEditor />}
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

/** Per-fuel price overrides (USD per tonne, the currency bunker prices are quoted in), next to the scenario default. */
function PriceEditor() {
  const { scenario, patchScenario, meta, network } = useStore();
  const money = useMoney();
  if (!scenario || !meta || !network) return null;
  const used = Array.from(new Set(network.routes.flatMap((r) => r.fuels.map((f) => f.id))));
  const defaults = network.prices.fuel_default_usd_per_t ?? network.prices.fuel_usd_per_t;
  const fuels = meta.fuels.filter((f) => used.includes(f.id));
  const set = (id: string, v: string) => {
    const next = { ...scenario.fuel_prices };
    if (v === "" || Number.isNaN(Number(v))) delete next[id]; else next[id] = Math.max(0, Number(v));
    patchScenario({ fuel_prices: next });
  };
  const basis = meta.price_basis;
  return (
    <div style={{ marginTop: 14 }}>
      <p className="small muted" style={{ maxWidth: 760 }}>
        {basis?.as_of ? `Price basis: ${basis.as_of}. ` : ""}{basis?.note ?? "Scenario defaults, not a live market feed."} Defaults
        for {scenario.year}{scenario.fuel_price_multiplier !== 1 ? `, × ${scenario.fuel_price_multiplier}` : ""}; prices are entered in
        USD per tonne, as bunker fuel is traded{money.inr ? ` (₹ at ${money.rate} per USD)` : ""}.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Fuel</th><th className="n">Default USD / t</th>{money.inr && <th className="n">≈ ₹ / t</th>}<th>Your price, USD / t</th><th /></tr></thead>
          <tbody>
            {fuels.map((f) => {
              const own = scenario.fuel_prices[f.id];
              const eff = own ?? defaults[f.id];
              return (
                <tr key={f.id} className={own !== undefined ? "mark" : undefined}>
                  <td>{f.label}</td>
                  <td className="n">{Math.round(defaults[f.id] ?? 0).toLocaleString("en-US")}</td>
                  {money.inr && <td className="n">{money.unit(eff)}</td>}
                  <td><input type="number" min={0} step={10} aria-label={`${f.label} price, USD per tonne`} style={{ width: 130 }}
                    placeholder={String(Math.round(defaults[f.id] ?? 0))} value={own ?? ""} onChange={(e) => set(f.id, e.target.value)} /></td>
                  <td>{own !== undefined && <button className="btn" onClick={() => set(f.id, "")}>Reset</button>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
