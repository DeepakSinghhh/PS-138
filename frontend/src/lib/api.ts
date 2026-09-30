import type { Genes, Meta, NetworkInfo, Plan, Scenario } from "./types";

async function req<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* keep status text */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export interface JobSummary { id: string; kind: string; status: string; progress: number; error: string | null }
export interface JobEvent { type: string; [k: string]: unknown }

export const api = {
  meta: () => req<Meta>("/meta"),
  health: () => req<{ status: string; model: boolean }>("/health"),
  network: (scenario: Scenario) => req<NetworkInfo>("/network", { scenario }),
  predict: (body: Record<string, unknown>) => req<Record<string, any>>("/predict", body),
  model: () => req<Record<string, any>>("/model"),
  evaluate: (scenario: Scenario, genes: Genes) => req<Plan>("/evaluate", { scenario, genes }),
  robustness: (scenario: Scenario, genes: Genes, samples = 400) => req<Record<string, any>>("/robustness", { scenario, genes, samples }),
  macc: (scenario: Scenario) => req<Record<string, any>>("/macc", { scenario }),
  exact: (scenario: Scenario, objective: string) => req<Record<string, any>>("/exact", { scenario, objective }),
  benchmarks: () => req<Record<string, any>>("/benchmarks"),
  parseRoutes: (csv: string) => req<{ routes: Record<string, unknown>[] }>("/routes/parse", { csv }),
  optimize: (scenario: Scenario, algorithm: string, budget: number, seed = 0) =>
    req<JobSummary>("/optimize", { scenario, algorithm, budget, seed }),
  timeline: (scenario: Scenario, years: number[], budget: number, preference: string) =>
    req<JobSummary>("/timeline", { scenario, years, budget, preference }),
  qubo: (scenario: Scenario, weights: Record<string, number>, solver: string) =>
    req<JobSummary>("/qubo", { scenario, weights, solver }),
  job: <T>(id: string) => req<JobSummary & { result?: T }>(`/jobs/${id}`),
};

/** Follow a background job over SSE; resolves with its result. */
export function followJob<T>(id: string, onEvent: (e: JobEvent) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/jobs/${id}/stream`);
    const finish = async () => {
      es.close();
      try {
        const j = await api.job<T>(id);
        if (j.status === "done") resolve(j.result as T);
        else reject(new Error(j.error ?? "job failed"));
      } catch (err) { reject(err); }
    };
    es.onmessage = (msg) => {
      const ev = JSON.parse(msg.data) as JobEvent;
      onEvent(ev);
      if (ev.type === "done" || ev.type === "error") finish();
    };
    es.onerror = () => finish();
  });
}

export async function downloadReport(scenario: Scenario, genes: Genes, algorithm?: string) {
  const res = await fetch("/api/report", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario, genes, algorithm, include_macc: true, include_robustness: true }),
  });
  if (!res.ok) throw new Error("report failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `qgreenfleet_${scenario.network}_${scenario.year}.html`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  window.open(url, "_blank");
}
