import { useEffect, useState } from "react";

export type ThemeTokens = Record<string, string>;
const NAMES = [
  "surface-1", "surface-2", "text-primary", "text-secondary", "text-muted", "grid", "axis", "border", "accent",
  "series-1", "series-2", "series-3", "series-4", "series-5", "series-6", "series-7", "series-8", "neutral-series",
  "seq-100", "seq-300", "seq-500", "seq-700", "good", "warning", "serious", "critical", "sea", "land", "coast", "ink", "page", "line",
];

function read(): ThemeTokens {
  const cs = getComputedStyle(document.documentElement);
  return Object.fromEntries(NAMES.map((n) => [n, cs.getPropertyValue(`--${n}`).trim()]));
}

/** Resolved CSS tokens; re-reads when the OS scheme or the in-app toggle changes. */
export function useTheme(): ThemeTokens {
  const [tokens, setTokens] = useState<ThemeTokens>(read);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setTokens(read());
    mq.addEventListener("change", update);
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => { mq.removeEventListener("change", update); obs.disconnect(); };
  }, []);
  return tokens;
}

/** Fuel family -> colour slot (fixed order, never cycled). Conventional oil is the neutral reference. */
export const FAMILY_SLOT: Record<string, string> = {
  conventional: "neutral-series", lng: "series-1", methanol: "series-2", ammonia: "series-3", hydrogen: "series-4",
};
export const FAMILY_LABEL: Record<string, string> = {
  conventional: "Conventional oil", lng: "LNG / bio-LNG", methanol: "Methanol", ammonia: "Ammonia", hydrogen: "Hydrogen",
};
export const familyColor = (t: ThemeTokens, family: string) => t[FAMILY_SLOT[family] ?? "neutral-series"];

/** Algorithm -> slot; ours always slot 1. */
export const ALGO_SLOT: Record<string, string> = {
  "QMOEA-H": "series-1", MOPSO: "series-2", "NSGA-II": "series-3", "NSGA-III": "series-4",
  MOQPSO: "series-5", SPEA2: "series-6", "QMOEA-R": "series-7", "MOEA/D": "series-8", Random: "neutral-series",
};
export function algoColor(t: ThemeTokens, name: string): string {
  // exact match on the first token: a prefix match would give NSGA-III the NSGA-II colour
  return t[ALGO_SLOT[name.split(" ")[0]] ?? "neutral-series"];
}
