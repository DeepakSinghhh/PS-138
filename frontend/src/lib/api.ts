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
  qaoa: (scenario: Scenario, weights: Record<string, number>, services = 4, options = 3, layers = 3) =>
    req<JobSummary>("/qaoa", { scenario, weights, services, options, layers }),
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

async function fetchReport(scenario: Scenario, genes: Genes, algorithm?: string, currency = "INR"): Promise<Blob> {
  const res = await fetch("/api/report", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario, genes, algorithm, include_macc: true, include_robustness: true, currency }),
  });
  if (!res.ok) throw new Error("report failed");
  return res.blob();
}

/**
 * Open the decision report in a new tab and start the browser's print dialog, where "Save as PDF" writes the file.
 * The tab is opened before the request (still inside the click) so pop-up blockers allow it.
 */
export async function printReport(scenario: Scenario, genes: Genes, algorithm?: string, currency = "INR") {
  const w = window.open("", "_blank");
  if (!w) throw new Error("Allow pop-ups for this site to save the report as PDF");
  w.document.write("<p style=\"font:14px system-ui;padding:24px\">Preparing the report…</p>");
  try {
    const html = await (await fetchReport(scenario, genes, algorithm, currency)).text();
    const auto = "<script>window.addEventListener('load',function(){setTimeout(function(){window.print()},400)})</script>";
    w.document.open();
    w.document.write(html.includes("</body>") ? html.replace("</body>", `${auto}</body>`) : html + auto);
    w.document.close();
  } catch (e) {
    w.close();
    throw e;
  }
}

export async function downloadReport(scenario: Scenario, genes: Genes, algorithm?: string, currency = "INR") {
  const blob = await fetchReport(scenario, genes, algorithm, currency);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `qgreenfleet_${scenario.network}_${scenario.year}.html`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  window.open(url, "_blank");
}
