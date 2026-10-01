import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useT } from "../lib/i18n";

/** Start the guided tour from anywhere (e.g. a button on the overview page). */
export const startTour = () => window.dispatchEvent(new CustomEvent("qgf:tour"));

/** Tour targets carry data-tour markers, so the tour works in every language. */
const byTour = (key: string) => () => document.querySelector(`[data-tour="${key}"]`);

async function waitFor<T>(find: () => T | null, ms: number): Promise<T | null> {
  const t0 = Date.now();
  for (;;) {
    const el = find();
    if (el || Date.now() - t0 > ms) return el;
    await new Promise((r) => setTimeout(r, 120));
  }
}

interface Step {
  path: string;
  find: () => Element | null;
  title: string;   // English text; translated with t() when shown
  body: string;
  prepare?: () => Promise<void>;
}

const STEPS: Step[] = [
  {
    path: "/", find: byTour("footprint"), title: "Start here: today's footprint",
    body: "The India coastal and near-sea network in 2030, 12 services. The big number is the fleet's well-to-wake emissions if it keeps running as it does today: VLSFO at the fastest schedule-feasible speed.",
  },
  {
    path: "/", find: byTour("network"), title: "The network on real sea lanes",
    body: "Every service follows its real sea route. Once a plan is chosen, the map colours each route by the fuel it burns.",
  },
  {
    path: "/optimize", find: byTour("run"), title: "Optimise the whole fleet",
    body: "Deliverables 2–3. QMOEA-H, our quantum-inspired optimizer, picks the vessel class, number of ships, speed, fuel and shore power for every service at once, minimising fuel, well-to-wake emissions and cost under demand, schedule, CII and FuelEU constraints. Press Next and the tour runs it for you.",
  },
  {
    path: "/optimize", find: byTour("tradeoff"), title: "Trade-offs, not a single answer",
    body: "Each dot is a complete fleet plan that no other plan beats on every objective (a Pareto front). The ringed dot is the balanced recommendation; the grey markers are today's practice and slow steaming. Click any dot to inspect that plan.",
    prepare: async () => {
      // the optimizer's status line carries data-opt-done once a run has finished
      const done = () => document.querySelector('[data-opt-done="1"]');
      if (done()) return;
      const run = byTour("run")() as HTMLButtonElement | null;
      if (run && !run.disabled) run.click();
      await waitFor(done, 180000);
    },
  },
  {
    path: "/optimize", find: byTour("allocation"), title: "The plan, service by service",
    body: "Vessel mix, ships, speed, fuel and shore power for each service, with a fleet map, an emission profile and a one-click decision report (Deliverable 4).",
  },
  {
    path: "/predict", find: byTour("speedfuel"), title: "Fuel prediction",
    body: "Deliverable 1. Q-PHYS predicts daily fuel from speed, load, weather and vessel type: a physics prior plus a tensor-network (MPS) model and monotone gradient boosting. The band is a 90 % conformal prediction interval. Move the sliders to see it respond.",
  },
  {
    path: "/lab", find: byTour("pathway"), title: "2025 → 2050 scenarios",
    body: "Scenario simulation: every milestone year is re-optimised as the CII and FuelEU limits tighten, prices change and green fuels reach more ports. Fuel prices, carbon price and disruptions such as a Red Sea diversion are set in the scenario panel.",
  },
  {
    path: "/lab", find: byTour("qaoa"), title: "A real quantum circuit",
    body: "Four services competing for scarce ships, written as a 12-qubit QAOA circuit. It is simulated exactly and trained here, and it downloads as OpenQASM 2.0 that runs on IBM Quantum or any QASM toolchain.",
  },
  {
    path: "/compliance", find: byTour("cii"), title: "Regulatory compliance",
    body: "The chosen plan checked against IMO CII ratings per ship, the FuelEU Maritime GHG-intensity limit (with pooling) and EU ETS costs, year by year.",
  },
  {
    path: "/benchmarks", find: byTour("frontquality"), title: "Honest benchmarks",
    body: "Deliverable 5. QMOEA-H against NSGA-II, NSGA-III, SPEA2, MOEA/D, MOPSO and ablations over 10 seeds, with gaps to the exact MILP optimum and a scalability sweep up to 200 routes. Wins, ties and losses are all reported.",
  },
];

export default function Tour() {
  const [step, setStep] = useState<number | null>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [waiting, setWaiting] = useState(false);
  const target = useRef<Element | null>(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const t = useT();

  useEffect(() => {
    const open = () => setStep(0);
    window.addEventListener("qgf:tour", open);
    return () => window.removeEventListener("qgf:tour", open);
  }, []);

  const close = useCallback(() => { setStep(null); setRect(null); target.current = null; }, []);

  // go to the step's page, run its preparation, find and frame its target
  useEffect(() => {
    if (step === null) return;
    const s = STEPS[step];
    let cancelled = false;
    setRect(null);
    target.current = null;
    if (pathname !== s.path) { navigate(s.path); return; }
    (async () => {
      if (s.prepare) { setWaiting(true); await s.prepare(); setWaiting(false); }
      const el = await waitFor(s.find, 6000);
      if (cancelled) return;
      target.current = el;
      if (el) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        setTimeout(() => { if (!cancelled && target.current) setRect(target.current.getBoundingClientRect()); }, 450);
      } else {
        setRect(new DOMRect(window.innerWidth / 2, window.innerHeight / 2, 0, 0));
      }
    })();
    return () => { cancelled = true; };
  }, [step, pathname, navigate]);

  useLayoutEffect(() => {
    if (step === null) return;
    const update = () => { if (target.current) setRect(target.current.getBoundingClientRect()); };
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => { window.removeEventListener("scroll", update, true); window.removeEventListener("resize", update); };
  }, [step]);

  useEffect(() => {
    if (step === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "ArrowRight" && !waiting) setStep((k) => (k !== null && k < STEPS.length - 1 ? k + 1 : k));
      if (e.key === "ArrowLeft" && !waiting) setStep((k) => (k ? k - 1 : k));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, waiting, close]);

  if (step === null) return null;
  const s = STEPS[step];
  const last = step === STEPS.length - 1;
  const W = Math.min(380, window.innerWidth - 32);
  const pad = 8;
  let style: React.CSSProperties = { width: W, left: 16, top: 16 };
  if (rect) {
    const tall = rect.height > window.innerHeight * 0.55;
    const left = Math.max(16, Math.min(rect.left, window.innerWidth - W - 16));
    if (tall || rect.width === 0) style = { width: W, right: 24, bottom: 24 };
    else if (rect.bottom + 230 < window.innerHeight) style = { width: W, left, top: rect.bottom + pad + 10 };
    else style = { width: W, left, top: Math.max(16, rect.top - pad - 10), transform: "translateY(-100%)" };
  }
  return (
    <div className="tour" role="dialog" aria-modal="false" aria-labelledby="tour-title">
      {rect && rect.width > 0 && (
        <div className="tour-highlight" style={{ left: rect.left - pad, top: rect.top - pad, width: rect.width + 2 * pad, height: rect.height + 2 * pad }} />
      )}
      <div className="tour-callout" style={style}>
        <div className="tour-count">{t("Guided tour · {i} / {n}", { i: step + 1, n: STEPS.length })}</div>
        <h4 id="tour-title">{t(s.title)}</h4>
        <p>{waiting ? t("Running the optimizer… the Pareto front builds up on the page.") : t(s.body)}</p>
        <div className="tour-actions">
          <button className="btn" onClick={close}>{t("Close")}</button>
          <span style={{ flex: 1 }} />
          {step > 0 && <button className="btn" disabled={waiting} onClick={() => setStep(step - 1)}>{t("Back")}</button>}
          <button className="btn primary" disabled={waiting} onClick={() => (last ? close() : setStep(step + 1))}>{last ? t("Finish") : t("Next")}</button>
        </div>
      </div>
    </div>
  );
}
