import type { Scenario } from "./types";

/** Scenario <-> compact URL parameter (only the fields that differ from the defaults, base64url JSON). */
export function encodeScenario(sc: Scenario, defaults: Record<string, unknown>): string {
  const diff: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(sc)) {
    if (JSON.stringify(v) !== JSON.stringify(defaults[k])) diff[k] = v;
  }
  const bytes = new TextEncoder().encode(JSON.stringify(diff));
  let bin = "";
  bytes.forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function decodeScenario(param: string | null): Record<string, unknown> | null {
  if (!param) return null;
  try {
    const bin = atob(param.replace(/-/g, "+").replace(/_/g, "/"));
    const obj = JSON.parse(new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0))));
    return obj && typeof obj === "object" && !Array.isArray(obj) ? obj : null;
  } catch {
    return null;
  }
}

export function shareUrl(sc: Scenario, defaults: Record<string, unknown>): string {
  const url = new URL(window.location.href);
  url.search = "";
  url.hash = "";
  url.searchParams.set("s", encodeScenario(sc, defaults));
  return url.toString();
}
