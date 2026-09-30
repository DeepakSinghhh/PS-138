import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { IconBook, IconChart, IconGauge, IconHome, IconLeaf, IconShield, IconShip } from "./components/Icons";
import { Wordmark } from "./components/Logo";
import Tour, { startTour } from "./components/Tour";
import { useStore } from "./lib/store";
import About from "./pages/About";
import Benchmarks from "./pages/Benchmarks";
import Compliance from "./pages/Compliance";
import Lab from "./pages/Lab";
import Optimize from "./pages/Optimize";
import Overview from "./pages/Overview";
import Predict from "./pages/Predict";

const NAV = [
  { to: "/", label: "Overview", icon: <IconHome /> },
  { to: "/optimize", label: "Fleet optimizer", icon: <IconShip /> },
  { to: "/predict", label: "Fuel prediction", icon: <IconGauge /> },
  { to: "/lab", label: "Fuel & policy lab", icon: <IconLeaf /> },
  { to: "/compliance", label: "Compliance", icon: <IconShield /> },
  { to: "/benchmarks", label: "Benchmarks", icon: <IconChart /> },
  { to: "/about", label: "Methodology", icon: <IconBook /> },
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

export default function App() {
  const { error, setError } = useStore();
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);  // each page opens at the top
  return (
    <div className="app">
      <aside className="sidebar">
        <Wordmark sub="green fleet decisions" />
        <nav className="nav">
          {NAV.map((n) => <NavLink key={n.to} to={n.to} end={n.to === "/"}>{n.icon}{n.label}</NavLink>)}
        </nav>
        <button className="tour-link" onClick={startTour}>Guided tour (2 min)</button>
        <div className="sidebar-foot">
          <b>SIH 2026</b> · PS 26138<br />
          Egreen Quanta
          <ThemeToggle />
        </div>
      </aside>
      <main className="main">
        {error && (
          <div className="card" style={{ borderColor: "var(--critical)", marginBottom: 14, display: "flex", justifyContent: "space-between", gap: 12 }}>
            <span className="status"><span className="dot" style={{ background: "var(--critical)" }} />{error}</span>
            <button className="btn" onClick={() => setError(null)}>Dismiss</button>
          </div>
        )}
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/optimize" element={<Optimize />} />
          <Route path="/predict" element={<Predict />} />
          <Route path="/lab" element={<Lab />} />
          <Route path="/compliance" element={<Compliance />} />
          <Route path="/benchmarks" element={<Benchmarks />} />
          <Route path="/about" element={<About />} />
        </Routes>
      </main>
      <Tour />
    </div>
  );
}
