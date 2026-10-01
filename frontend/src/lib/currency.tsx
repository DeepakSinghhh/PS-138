import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useLang } from "./i18n";
import { useStore } from "./store";

/**
 * Display currency. The model works in US dollars (bunker fuel, charter and shipping finance are quoted in USD);
 * the dashboard shows rupees by default at the editable rate in backend/config/prices.yaml (meta.fx.usd_to_inr).
 * Large amounts arrive in million USD and are shown in crore (1 crore = 10 million rupees).
 */
export type Currency = "INR" | "USD";

const Ctx = createContext<{ currency: Currency; setCurrency: (c: Currency) => void } | null>(null);
const KEY = "qgf-currency";

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [currency, setCurrency] = useState<Currency>(() => {
    try { return localStorage.getItem(KEY) === "USD" ? "USD" : "INR"; } catch { return "INR"; }
  });
  useEffect(() => { try { localStorage.setItem(KEY, currency); } catch { /* private mode */ } }, [currency]);
  const value = useMemo(() => ({ currency, setCurrency }), [currency]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCurrency() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("CurrencyProvider missing");
  return ctx;
}

export interface Money {
  currency: Currency;
  inr: boolean;
  rate: number;
  /** million USD -> value in the display unit (crore or M USD), for charts */
  bigValue: (musd: number) => number;
  /** "crore ₹" or "M USD" */
  bigUnit: string;
  /** million USD -> "₹4,897 crore" / "$556.5 M" */
  big: (musd: number | null | undefined, digits?: number) => string;
  /** million USD split for stat tiles: { value: "₹4,897", unit: "crore" } / { value: "$556.5", unit: "million" } */
  bigSplit: (musd: number | null | undefined) => { value: string; unit: string };
  /** plain USD (e.g. per tonne) -> value in the display unit */
  unitValue: (usd: number) => number;
  /** "₹" or "USD" for per-unit labels */
  unitLabel: string;
  /** plain USD -> "₹52,800" / "$600" */
  unit: (usd: number | null | undefined, digits?: number) => string;
  /** rewrite "USD 21.73 M" / "21.7 M USD" inside backend sentences into the display currency */
  text: (s: string) => string;
}

export function useMoney(): Money {
  const { currency } = useCurrency();
  const { meta } = useStore();
  const { lang } = useLang();
  const crore = lang === "hi" ? "करोड़" : "crore";
  const rate = (meta as { fx?: { usd_to_inr?: number } } | null)?.fx?.usd_to_inr ?? 88;
  return useMemo(() => {
    const inr = currency === "INR";
    const nf = (v: number, d: number) =>
      new Intl.NumberFormat(inr ? "en-IN" : "en-US", { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
    const bigValue = (musd: number) => (inr ? (musd * rate) / 10 : musd);
    const big = (musd: number | null | undefined, digits?: number) => {
      if (musd === null || musd === undefined || Number.isNaN(musd)) return "–";
      const v = bigValue(musd);
      if (v === 0) return inr ? "₹0" : "$0"; // "₹0.0 crore" reads oddly for a zero penalty
      return inr ? `₹${nf(v, digits ?? (Math.abs(v) < 10 ? 1 : 0))} ${crore}` : `$${nf(v, digits ?? 1)} M`;
    };
    const bigSplit = (musd: number | null | undefined) => {
      if (musd === null || musd === undefined || Number.isNaN(musd)) return { value: "–", unit: "" };
      const v = bigValue(musd);
      return inr ? { value: `₹${nf(v, Math.abs(v) < 10 ? 1 : 0)}`, unit: crore } : { value: `$${nf(v, 1)}`, unit: "million" };
    };
    const unitValue = (usd: number) => (inr ? usd * rate : usd);
    const unit = (usd: number | null | undefined, digits = 0) =>
      usd === null || usd === undefined || Number.isNaN(usd) ? "–" : `${inr ? "₹" : "$"}${nf(unitValue(usd), digits)}`;
    const text = (s: string) =>
      s.replace(/USD\s*([\d,.]+)\s*M\b/g, (_, x) => big(parseFloat(x.replace(/,/g, ""))))
        .replace(/([\d,.]+)\s*M USD\b/g, (_, x) => big(parseFloat(x.replace(/,/g, ""))));
    return { currency, inr, rate, bigValue, bigUnit: inr ? `${crore} ₹` : "M USD", big, bigSplit, unitValue,
      unitLabel: inr ? "₹" : "USD", unit, text };
  }, [currency, rate, crore]);
}
