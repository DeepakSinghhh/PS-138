export const fmt = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });

export const compact = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `${(v / 1e3).toFixed(1)}K`;
  return fmt(v, a < 10 ? 2 : 0);
};

export const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;

export const OBJ_UNITS: Record<string, string> = {
  fuel: "t HFO-eq / yr", emissions: "t CO₂e / yr", cost: "M USD / yr", schedule_risk: "% late",
};
export const OBJ_SHORT: Record<string, string> = {
  fuel: "Fuel", emissions: "WtW GHG", cost: "Cost", schedule_risk: "Schedule risk",
};
