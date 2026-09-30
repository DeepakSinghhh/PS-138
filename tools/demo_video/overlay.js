// Injected into every page load: fake cursor, click ripple, captions, title cards, fast-forward badge.
(() => {
  if (window.__qgf) return;
  // capture blob downloads (the decision report) in-page instead of opening a browser download
  const origClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (this.download && String(this.href).startsWith("blob:")) {
      fetch(this.href).then((r) => r.text()).then((t) => { window.__qgfReport = t; });
      return;
    }
    return origClick.call(this);
  };
  const css = `
  #qgf-cursor { position: fixed; left: 0; top: 0; width: 30px; height: 30px; z-index: 2147483647; pointer-events: none;
    transform: translate(-100px, -100px); transition: transform 0.02s linear; filter: drop-shadow(0 1px 2px rgba(0,0,0,.35)); }
  .qgf-ripple { position: fixed; width: 14px; height: 14px; border-radius: 50%; border: 3px solid #0f6b45; z-index: 2147483646;
    pointer-events: none; transform: translate(-50%, -50%) scale(1); opacity: .9; animation: qgf-rip .55s ease-out forwards; }
  @keyframes qgf-rip { to { transform: translate(-50%, -50%) scale(4.2); opacity: 0; } }
  #qgf-cap { position: fixed; left: 50%; bottom: 40px; transform: translate(-50%, 16px); max-width: 1240px; min-width: 620px;
    z-index: 2147483645; pointer-events: none; opacity: 0; transition: opacity .45s ease, transform .45s ease;
    background: rgba(15, 45, 58, 0.95); color: #fff; border-radius: 16px; padding: 18px 30px 20px;
    box-shadow: 0 10px 30px rgba(0,0,0,.25); font-family: "IBM Plex Sans", "Segoe UI", Arial, sans-serif; }
  #qgf-cap.on { opacity: 1; transform: translate(-50%, 0); }
  #qgf-cap .k { font-size: 15px; letter-spacing: .14em; text-transform: uppercase; color: #6fd3a3; font-weight: 700; margin-bottom: 6px; }
  #qgf-cap .t { font-size: 27px; line-height: 1.38; font-weight: 500; }
  #qgf-card { position: fixed; inset: 0; z-index: 2147483644; display: flex; align-items: center; pointer-events: none;
    background: #0f2d3a; color: #fff; opacity: 0; transition: opacity .6s ease; font-family: "IBM Plex Sans", "Segoe UI", Arial, sans-serif; }
  #qgf-card.on { opacity: 1; }
  #qgf-card .wrap { margin-left: 170px; max-width: 1400px; }
  #qgf-card .kick { font-size: 21px; letter-spacing: .18em; text-transform: uppercase; color: #6fd3a3; font-weight: 700; }
  #qgf-card .num { font-family: "Fraunces Variable", Georgia, serif; font-variation-settings: "opsz" 40; font-size: 140px; font-weight: 600; color: #3fbf85; line-height: 1; margin-bottom: 8px; }
  #qgf-card h1 { font-family: "Fraunces Variable", Georgia, serif; font-variation-settings: "opsz" 40; font-size: 96px; margin: 14px 0 14px; font-weight: 600; letter-spacing: -.02em; line-height: 1.05; }
  #qgf-card p { font-size: 33px; color: #c9dde3; margin: 0; line-height: 1.4; }
  #qgf-card .foot { margin-top: 48px; font-size: 22px; color: #9fb4bc; }
  #qgf-card .mark { width: 110px; height: 110px; margin: 0 0 18px -10px; color: #f3f6f7; --brand-wave: #3fbf85; }
  #qgf-card .mark svg { width: 110px; height: 110px; }
  #qgf-ff { position: fixed; right: 26px; top: 22px; z-index: 2147483645; pointer-events: none; opacity: 0; transition: opacity .3s;
    background: rgba(15, 45, 58, 0.92); color: #6fd3a3; border-radius: 999px; padding: 8px 16px; font: 700 17px Arial, sans-serif; letter-spacing: .08em; }
  #qgf-ff.on { opacity: 1; }
  #qgf-report { position: fixed; inset: 0; z-index: 2147483600; background: rgba(15,45,58,.55); display: none; padding: 34px 90px; }
  #qgf-report.on { display: block; }
  #qgf-report iframe { width: 100%; height: 100%; border: 0; border-radius: 14px; background: #fff; box-shadow: 0 20px 60px rgba(0,0,0,.35); }
  `;
  const arrow = `<svg viewBox="0 0 24 24" width="30" height="30"><path d="M4 2 L4 20 L9 15.5 L12.5 22.5 L15.5 21 L12 14 L19 14 Z"
     fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  function mount() {
    const st = document.createElement("style");
    st.textContent = css;
    document.head.appendChild(st);
    const add = (id, html) => { const d = document.createElement("div"); d.id = id; d.innerHTML = html || ""; document.body.appendChild(d); return d; };
    const cur = add("qgf-cursor", arrow);
    const cap = add("qgf-cap", '<div class="k"></div><div class="t"></div>');
    const card = add("qgf-card", '<div class="wrap"></div>');
    const ff = add("qgf-ff", "");
    const rep = add("qgf-report", "<iframe></iframe>");
    let last = window.__qgfLast || { x: -100, y: -100 };
    const place = (x, y) => { cur.style.transform = `translate(${x - 3}px, ${y - 2}px)`; last = { x, y }; window.__qgfLast = last; };
    place(last.x, last.y);
    window.addEventListener("mousemove", (e) => place(e.clientX, e.clientY), true);
    window.addEventListener("mousedown", (e) => {
      const r = document.createElement("div");
      r.className = "qgf-ripple"; r.style.left = e.clientX + "px"; r.style.top = e.clientY + "px";
      document.body.appendChild(r); setTimeout(() => r.remove(), 700);
    }, true);
    window.__qgf = {
      caption(kicker, text) {
        cap.querySelector(".k").textContent = kicker || "";
        cap.querySelector(".t").textContent = text;
        cap.classList.add("on");
      },
      hideCaption() { cap.classList.remove("on"); },
      card(html) { card.querySelector(".wrap").innerHTML = html; card.classList.add("on"); cur.style.opacity = "0"; },
      hideCard() { card.classList.remove("on"); cur.style.opacity = "1"; },
      ff(on, label) { ff.textContent = label || "FAST-FORWARD 4×"; ff.classList.toggle("on", !!on); },
      report(html) { rep.querySelector("iframe").srcdoc = html; rep.classList.add("on"); },
      reportScroll(y) { const w = rep.querySelector("iframe").contentWindow; w.scrollTo({ top: y, behavior: "smooth" }); },
      reportHeight() { const d = rep.querySelector("iframe").contentDocument; return d ? d.documentElement.scrollHeight : 0; },
      hideReport() { rep.classList.remove("on"); },
    };
  }
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);
})();
