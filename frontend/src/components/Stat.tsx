import { pct } from "../lib/format";

interface Props { label: string; value: string; unit?: string; delta?: number | null; deltaLabel?: string; upIsGood?: boolean }

export default function Stat({ label, value, unit, delta, deltaLabel = "vs current practice", upIsGood = false }: Props) {
  const good = delta === undefined || delta === null ? null : (delta < 0) !== upIsGood;
  return (
    <div className="card stat">
      <span className="label">{label}</span>
      <span className={value.length >= 9 ? "value long" : "value"}>{value}</span>
      {unit && <span className="unit">{unit}</span>}
      {delta !== undefined && delta !== null && (
        <span className={`delta ${good ? "good" : "bad"}`}>{good ? "▼" : "▲"} {pct(delta)} <span className="muted" style={{ fontWeight: 400 }}>{deltaLabel}</span></span>
      )}
    </div>
  );
}
