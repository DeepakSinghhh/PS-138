import { useEffect, useState } from "react";
import Plot from "../components/Plot";
import Stat from "../components/Stat";
import { api } from "../lib/api";
import { fmt } from "../lib/format";
import { useStore } from "../lib/store";
import { useTheme } from "../lib/theme";

interface Inputs {
  vessel_class: string; speed_kn: number; load_ratio: number; wind_speed_ms: number; wind_rel_deg: number;
  wave_height_m: number; wave_rel_deg: number; days_since_cleaning: number; fuel: string;
}

const FEATURE_LABEL: Record<string, string> = {
  log_prior: "Physics prior", speed_kn: "Speed", design_speed_kn: "Design speed", mcr_kw: "Engine power (MCR)",
  load_ratio: "Cargo load", draft_ratio: "Draft", trim_m: "Trim", days_since_cleaning: "Days since hull cleaning",
  hull_age_years: "Hull age", head_wind_ms: "Head wind", wind_speed_ms: "Wind speed", wave_height_m: "Wave height",
  head_wave_m: "Head waves", current_kn: "Current", capacity: "Capacity", dwt: "Deadweight",
};

function Slider({ label, value, min, max, step, unit, onChange }: { label: string; value: number; min: number; max: number; step: number; unit: string; onChange: (v: number) => void }) {
  return (
    <label className="field">
      <span className="range-row"><span>{label}</span><span className="num">{value} {unit}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

export default function Predict() {
  const { meta, setError } = useStore();
  const t = useTheme();
  const [inp, setInp] = useState<Inputs>({ vessel_class: "PANAMAX_C", speed_kn: 16, load_ratio: 0.85, wind_speed_ms: 8,
    wind_rel_deg: 30, wave_height_m: 2, wave_rel_deg: 30, days_since_cleaning: 365, fuel: "VLSFO" });
  const [res, setRes] = useState<Record<string, any> | null>(null);
  const [card, setCard] = useState<Record<string, any> | null>(null);
  const vc = meta?.vessel_classes.find((v) => v.id === inp.vessel_class);

  useEffect(() => { api.model().then(setCard).catch(() => setCard(null)); }, []);
  useEffect(() => {
    const h = setTimeout(() => api.predict({ ...inp }).then(setRes).catch((e) => setError(e.message)), 200);
    return () => clearTimeout(h);
  }, [inp, setError]);
  const set = (p: Partial<Inputs>) => setInp((s) => ({ ...s, ...p }));

  const curve = res?.curve;
  const imp = card?.feature_importance ? Object.entries(card.feature_importance as Record<string, number>).slice(0, 10) : [];
  const featureName = (k: string) => FEATURE_LABEL[k] ?? (k.startsWith("vt_") ? `Type: ${k.slice(3).replace(/_/g, " ")}` : k.replace(/_/g, " "));
  const ent: number[] = card?.report?.mps?.entanglement_entropy ?? [];
  const bonds: string[] = card?.report?.mps?.bond_features ?? [];
  const beaufort = Math.round((inp.wind_speed_ms / 0.836) ** (2 / 3));

  return (
    <div className="grid page">
      <div className="page-head">
        <div>
          <span className="kicker">Deliverable 1 · Prediction</span>
          <h1>Fuel consumption prediction</h1>
          <p>Q-PHYS combines ship physics with a QPSO-tuned monotone booster and a Matrix-Product-State tensor network
            (a quantum-inspired model). Inputs follow the PS: speed, load, weather and vessel type.</p>
        </div>
        {card?.available && <span className="chip">test MAPE {card.test_metrics.MAPE.toFixed(2)}% · R² {card.test_metrics.R2.toFixed(3)} · 90% interval coverage {(100 * card.conformal.coverage).toFixed(0)}%</span>}
      </div>

      <div className="grid split-controls">
        <div className="card grid" style={{ alignContent: "start", gap: 14 }}>
          <label className="field">Vessel type & class
            <select value={inp.vessel_class} onChange={(e) => {
              const v = meta?.vessel_classes.find((x) => x.id === e.target.value);
              set({ vessel_class: e.target.value, speed_kn: v ? Math.round(v.design_speed_kn * 0.8) : inp.speed_kn });
            }}>
              {meta?.vessel_classes.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
          </label>
          {vc && <Slider label="Speed through water" value={inp.speed_kn} min={vc.min_speed_kn} max={vc.max_speed_kn} step={0.5} unit="kn" onChange={(v) => set({ speed_kn: v })} />}
          <Slider label="Cargo load" value={inp.load_ratio} min={0} max={1} step={0.05} unit="of full" onChange={(v) => set({ load_ratio: v })} />
          <Slider label={`Wind speed (≈ Beaufort ${beaufort})`} value={inp.wind_speed_ms} min={0} max={25} step={0.5} unit="m/s" onChange={(v) => set({ wind_speed_ms: v })} />
          <Slider label="Wind angle (0 = head)" value={inp.wind_rel_deg} min={0} max={180} step={5} unit="°" onChange={(v) => set({ wind_rel_deg: v, wave_rel_deg: v })} />
          <Slider label="Significant wave height" value={inp.wave_height_m} min={0} max={7} step={0.25} unit="m" onChange={(v) => set({ wave_height_m: v })} />
          <Slider label="Days since hull cleaning" value={inp.days_since_cleaning} min={0} max={900} step={15} unit="d" onChange={(v) => set({ days_since_cleaning: v })} />
          <label className="field">Fuel system
            <select value={inp.fuel} onChange={(e) => set({ fuel: e.target.value })}>
              {meta?.fuels.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
          </label>
          <p className="note">New ships are predicted by the fleet head (trained on other ships and calibrated on held-out
            ships), so intervals are honest for vessels the model has never seen.</p>
        </div>

        <div className="grid" style={{ alignContent: "start" }}>
          <div className="grid cols-4">
            <Stat label="Predicted fuel" value={res ? fmt(res.fuel_hfo_eq_tpd, 1) : "–"} unit="t HFO-equivalent / day" />
            <Stat label="90 % interval" value={res ? `${fmt(res.interval_tpd[0], 1)}–${fmt(res.interval_tpd[1], 1)}` : "–"} unit="t / day (split-conformal)" />
            <Stat label={`${res?.fuel_label ?? "Fuel"} burned`} value={res ? fmt(Object.values(res.fuel_mass_tpd as Record<string, number>).reduce((a, b) => a + b, 0), 1) : "–"}
              unit={res ? Object.entries(res.fuel_mass_tpd as Record<string, number>).map(([k, v]) => `${k} ${fmt(v, 1)} t`).join(" + ") : ""} />
            <Stat label="Well-to-wake GHG" value={res ? fmt(res.wtw_co2e_tpd, 1) : "–"} unit={res ? `t CO₂e / day · TtW CO₂ ${fmt(res.co2_ttw_tpd, 1)} t` : ""} />
          </div>
          <div className="card">
            <div className="card-head"><h3>Speed-fuel curve at these conditions</h3><span className="muted small">{res?.source}</span></div>
            {curve ? (
              <Plot ariaLabel="Fuel consumption versus speed with prediction interval" height={330} data={[
                { type: "scatter", mode: "lines", x: curve.speed_kn, y: curve.hi, line: { width: 0 }, hoverinfo: "skip", showlegend: false },
                { type: "scatter", mode: "lines", x: curve.speed_kn, y: curve.lo, fill: "tonexty", fillcolor: `${t["series-1"]}1f`,
                  line: { width: 0 }, name: "90 % interval", hoverinfo: "skip" },
                { type: "scatter", mode: "lines", x: curve.speed_kn, y: curve.fuel_tpd, name: "Q-PHYS", line: { color: t["series-1"], width: 2 },
                  hovertemplate: "%{x:.1f} kn → %{y:.1f} t/day<extra>Q-PHYS</extra>" },
                { type: "scatter", mode: "lines", x: curve.speed_kn, y: curve.physics_tpd, name: "Physics only (IMO GHG4 + Kwon)",
                  line: { color: t["neutral-series"], width: 2, dash: "dot" }, hovertemplate: "%{x:.1f} kn → %{y:.1f} t/day<extra>physics</extra>" },
                { type: "scatter", mode: "markers", x: [res!.speed_kn], y: [res!.fuel_hfo_eq_tpd], name: "Selected speed",
                  marker: { size: 10, color: t["series-1"], line: { color: t["surface-1"], width: 2 } }, hoverinfo: "skip" },
              ]} layout={{ xaxis: { title: { text: "speed (kn)" } }, yaxis: { title: { text: "fuel (t HFO-eq / day)" } } }} />
            ) : <div className="empty">…</div>}
          </div>
          <div className="grid cols-2">
            <div className="card">
              <div className="card-head"><h3>What drives the prediction</h3><span className="muted small">mean |SHAP|, booster</span></div>
              {imp.length ? (
                <Plot ariaLabel="Feature importance" height={300} data={[{
                  type: "bar", orientation: "h", y: imp.map(([k]) => featureName(k)), x: imp.map(([, v]) => v),
                  marker: { color: t["series-1"] }, width: 0.55, hovertemplate: "%{y}: %{x:.3f}<extra></extra>",
                }]} layout={{ margin: { l: 150, r: 16, t: 8, b: 36 }, yaxis: { autorange: "reversed", gridcolor: "rgba(0,0,0,0)" }, xaxis: { title: { text: "mean |SHAP| (log fuel)" } } }} />
              ) : <div className="empty">Train the model with <span className="kbd">make train</span></div>}
            </div>
            <div className="card">
              <div className="card-head"><h3>Inside the tensor network</h3><span className="muted small">entanglement entropy per MPS bond</span></div>
              {ent.length ? (
                <Plot ariaLabel="MPS entanglement entropy" height={300} data={[{
                  type: "bar", x: bonds.map((_, i) => i + 1), y: ent, marker: { color: t["series-3"] }, width: 0.6,
                  customdata: bonds, hovertemplate: "bond %{x}: %{customdata}<br>S = %{y:.2f} nats<extra></extra>",
                }]} layout={{ xaxis: { title: { text: "bond between neighbouring features" }, dtick: 1 }, yaxis: { title: { text: "entropy (nats)" } } }} />
              ) : <div className="empty">No MPS report available</div>}
              <p className="note">Features are encoded as spin-coherent qudit states; high entropy marks where the model couples feature groups.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
