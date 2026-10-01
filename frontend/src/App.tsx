import { lazy, Suspense, useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import { Wordmark } from "./components/Logo";
import Tour, { startTour } from "./components/Tour";
import { useCurrency } from "./lib/currency";
import { useStore } from "./lib/store";

// each page is its own chunk, fetched the first time it is opened
const About = lazy(() => import("./pages/About"));
const Benchmarks = lazy(() => import("./pages/Benchmarks"));
const Compliance = lazy(() => import("./pages/Compliance"));
const Lab = lazy(() => import("./pages/Lab"));
const Optimize = lazy(() => import("./pages/Optimize"));
const Overview = lazy(() => import("./pages/Overview"));
const Predict = lazy(() => import("./pages/Predict"));

const NAV = [
  { to: "/", label: "Overview" },
  { to: "/optimize", label: "Fleet optimizer" },
  { to: "/predict", label: "Fuel prediction" },
  { to: "/lab", label: "Fuel & policy lab" },
  { to: "/compliance", label: "Compliance" },
  { to: "/benchmarks", label: "Benchmarks" },
  { to: "/about", label: "Methodology" },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<string>(() => {
    try { return localStorage.getItem("qgf-theme") ?? "auto"; } catch { return "auto"; }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", theme);
    try { localStorage.setItem("qgf-theme", theme); } catch { /* private mode */ }
  }, [theme]);
  return (
    <div className="segmented theme-toggle" role="group" aria-label="Colour theme">
      {["auto", "light", "dark"].map((k) => <button key={k} className={theme === k ? "on" : ""} onClick={() => setTheme(k)}>{k}</button>)}
    </div>
  );
}

function CurrencyToggle() {
  const { currency, setCurrency } = useCurrency();
  return (
    <div className="segmented theme-toggle" role="group" aria-label="Currency">
      {([["INR", "₹ INR"], ["USD", "$ USD"]] as const).map(([k, l]) => (
        <button key={k} className={currency === k ? "on" : ""} onClick={() => setCurrency(k)}>{l}</button>))}
    </div>
  );
}

export default function App() {
  const { error, setError } = useStore();
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);  // each page opens at the top
  useEffect(() => {  // warm the chart library after the first paint so later pages open instantly
    const t = window.setTimeout(() => { void import("./components/Plot").then((m) => m.preloadCharts()); }, 1200);
    return () => window.clearTimeout(t);
  }, []);
  // section number shown before each page's kicker ("02 — …"), matching the numbered navigation
  const section = `"${String(Math.max(0, NAV.findIndex((n) => n.to === pathname)) + 1).padStart(2, "0")}"`;
  return (
    <div className="app">
      <aside className="sidebar">
        <Wordmark sub="green fleet decisions" />
        <nav className="nav">
          {NAV.map((n) => <NavLink key={n.to} to={n.to} end={n.to === "/"}>{n.label}</NavLink>)}
        </nav>
        <button className="tour-link" onClick={startTour}>Guided tour (2 min)</button>
        <div className="sidebar-foot">
          <span className="foot-credit"><b>SIH 2026</b> · PS 26138<br />Egreen Quanta</span>
          <CurrencyToggle />
          <ThemeToggle />
        </div>
      </aside>
      <main className="main" style={{ "--n": section } as React.CSSProperties}>
        {error && (
          <div className="card" style={{ borderTopColor: "var(--critical)", marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <span className="status"><span className="dot" style={{ background: "var(--critical)" }} />{error}</span>
            <button className="btn" onClick={() => setError(null)}>Dismiss</button>
          </div>
        )}
        <ErrorBoundary resetKey={pathname}>
        <Suspense fallback={<div className="plot-loading" style={{ minHeight: 240 }}>Loading…</div>}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/optimize" element={<Optimize />} />
          <Route path="/predict" element={<Predict />} />
          <Route path="/lab" element={<Lab />} />
          <Route path="/compliance" element={<Compliance />} />
          <Route path="/benchmarks" element={<Benchmarks />} />
          <Route path="/about" element={<About />} />
        </Routes>
        </Suspense>
        </ErrorBoundary>
      </main>
      <Tour />
    </div>
  );
}
