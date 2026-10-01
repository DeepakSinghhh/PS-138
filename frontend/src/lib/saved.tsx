import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { Genes, Plan, Scenario } from "./types";

/**
 * Saved plans: any plan (with the scenario it was optimised for) can be kept in this browser, compared side by side
 * on the Compare page and re-opened in the optimizer. Stored in localStorage, so it survives reloads but stays on
 * this device; route geometry is dropped to keep entries small.
 */
export interface SavedPlan {
  id: string;
  label: string;
  savedAt: number;
  scenario: Scenario;
  genes: Genes;
  plan: Plan;
  algorithm?: string;
}

const KEY = "qgf-saved-plans";
const MAX = 12;

function load(): SavedPlan[] {
  try {
    const raw = localStorage.getItem(KEY);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((p) => p && p.id && p.plan && p.scenario) : [];
  } catch { return []; }
}

function persist(list: SavedPlan[]) {
  try { localStorage.setItem(KEY, JSON.stringify(list)); } catch { /* private mode or quota: keep in memory only */ }
}

interface Ctx {
  saved: SavedPlan[];
  save: (p: Omit<SavedPlan, "id" | "savedAt">) => string;
  remove: (id: string) => void;
  rename: (id: string, label: string) => void;
}
const SavedCtx = createContext<Ctx | null>(null);

export function SavedPlansProvider({ children }: { children: ReactNode }) {
  const [saved, setSaved] = useState<SavedPlan[]>(load);
  const update = useCallback((f: (l: SavedPlan[]) => SavedPlan[]) => {
    setSaved((l) => { const n = f(l); persist(n); return n; });
  }, []);
  const save = useCallback((p: Omit<SavedPlan, "id" | "savedAt">) => {
    const id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    const plan = { ...p.plan, routes: p.plan.routes.map((r) => ({ ...r, geometry: [] })) };
    update((l) => [{ ...p, plan, id, savedAt: Date.now() }, ...l].slice(0, MAX));
    return id;
  }, [update]);
  const remove = useCallback((id: string) => update((l) => l.filter((p) => p.id !== id)), [update]);
  const rename = useCallback((id: string, label: string) =>
    update((l) => l.map((p) => (p.id === id ? { ...p, label } : p))), [update]);
  const value = useMemo(() => ({ saved, save, remove, rename }), [saved, save, remove, rename]);
  return <SavedCtx.Provider value={value}>{children}</SavedCtx.Provider>;
}

export function useSaved(): Ctx {
  const v = useContext(SavedCtx);
  if (!v) throw new Error("SavedPlansProvider missing");
  return v;
}

/** One-line description of what makes a scenario different from the default India 2030 case. */
export function describeScenario(s: Scenario, networks?: Record<string, { name: string }>): string {
  const parts = [s.custom_routes ? `uploaded network (${s.custom_routes.length} routes)` : (networks?.[s.network]?.name ?? s.network), String(s.year)];
  if (s.red_sea_diversion) parts.push("Red Sea closed");
  if (s.monsoon) parts.push("SW monsoon");
  if (s.ets_price_eur !== null && s.ets_price_eur !== undefined) parts.push(`ETS €${s.ets_price_eur}/t`);
  if (s.global_levy_usd) parts.push(`levy $${s.global_levy_usd}/t`);
  if (s.fuel_price_multiplier && s.fuel_price_multiplier !== 1) parts.push(`fuel price ×${s.fuel_price_multiplier}`);
  if (s.fueleu_mode === "hard") parts.push("FuelEU must comply");
  if (s.cii_min_rating && s.cii_min_rating !== "C") parts.push(`CII ≥ ${s.cii_min_rating}`);
  return parts.join(" · ");
}
