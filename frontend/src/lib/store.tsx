import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import type { Genes, Meta, NetworkInfo, OptResult, Plan, Scenario } from "./types";

interface Selected { genes: Genes; plan: Plan; label: string }

interface Store {
  meta: Meta | null;
  scenario: Scenario | null;
  setScenario: (s: Scenario) => void;
  patchScenario: (p: Partial<Scenario>) => void;
  network: NetworkInfo | null;
  networkLoading: boolean;
  result: OptResult | null;
  setResult: (r: OptResult | null) => void;
  selected: Selected | null;
  setSelected: (s: Selected | null) => void;
  error: string | null;
  setError: (e: string | null) => void;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [network, setNetwork] = useState<NetworkInfo | null>(null);
  const [networkLoading, setNetworkLoading] = useState(false);
  const [result, setResult] = useState<OptResult | null>(null);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.meta().then((m) => { setMeta(m); setScenario({ ...m.default_scenario, network: "india", year: 2030 }); })
      .catch((e) => setError(`Cannot reach the API: ${e.message}. Start it with "make api".`));
  }, []);

  const key = scenario ? JSON.stringify(scenario) : "";
  useEffect(() => {
    if (!scenario) return;
    let alive = true;
    setNetworkLoading(true);
    const t = setTimeout(() => {
      api.network(scenario).then((n) => {
        if (!alive) return;
        setNetwork(n);
        setSelected((prev) => prev ?? { genes: n.baseline_genes.current_practice, plan: n.baselines.current_practice, label: "Current practice" });
      }).catch((e) => alive && setError(e.message)).finally(() => alive && setNetworkLoading(false));
    }, 250);
    return () => { alive = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const value = useMemo<Store>(() => ({
    meta, scenario, network, networkLoading, result, selected, error, setError, setResult,
    setSelected,
    setScenario: (s) => { setScenario(s); setSelected(null); setResult(null); },
    patchScenario: (p) => { setScenario((s) => (s ? { ...s, ...p } : s)); setSelected(null); setResult(null); },
  }), [meta, scenario, network, networkLoading, result, selected, error]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const v = useContext(Ctx);
  if (!v) throw new Error("StoreProvider missing");
  return v;
}
