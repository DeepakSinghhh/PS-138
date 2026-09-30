// Records a scripted walkthrough of the Q-GreenFleet dashboard as timestamped JPEG frames (CDP screencast)
// plus an event log (captions, cards, fast-forward spans) used by assemble.py to build the MP4 and SRT.
const fs = require("fs");
const path = require("path");
const { chromium } = require(path.join(__dirname, "..", "..", "frontend", "node_modules", "@playwright/test"));

const BASE = process.env.QGF_URL || "http://localhost:8000";
const OUT = path.join(__dirname, "frames");
const OVERLAY = fs.readFileSync(path.join(__dirname, "overlay.js"), "utf8");

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const events = [];
const frames = [];
const now = () => Date.now() / 1000;
const hold = (ms) => new Promise((r) => setTimeout(r, ms));
const readMs = (text) => Math.max(2800, text.length * 50);

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || "/opt/pw-browsers/chromium",
    args: ["--hide-scrollbars", "--force-color-profile=srgb", "--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"],
  });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, colorScheme: "light", acceptDownloads: true,
  });
  await context.addInitScript({ content: OVERLAY });
  const page = await context.newPage();
  const client = await context.newCDPSession(page);
  client.on("Page.screencastFrame", async (f) => {
    const file = path.join(OUT, `f${String(frames.length).padStart(6, "0")}.jpg`);
    fs.writeFileSync(file, Buffer.from(f.data, "base64"));
    frames.push({ file: path.basename(file), t: f.metadata.timestamp || now() });
    try { await client.send("Page.screencastFrameAck", { sessionId: f.sessionId }); } catch (e) { /* page closing */ }
  });

  // ---------------------------------------------------------------- helpers
  const caption = async (kicker, text, vo) => {
    events.push({ t: now(), type: "caption", kicker, text, vo: vo || text });
    await page.evaluate(([k, t]) => window.__qgf.caption(k, t), [kicker, text]);
  };
  const say = async (kicker, text, vo, extra = 0) => { await caption(kicker, text, vo); await hold(readMs(text) + extra); };
  const hideCaption = async () => {
    events.push({ t: now(), type: "hide" });
    await page.evaluate(() => window.__qgf.hideCaption());
    await hold(450);
  };
  const card = async (html, ms, during) => {
    events.push({ t: now(), type: "card", html });
    await page.evaluate((h) => window.__qgf.card(h.replace("{MARK}",
      document.querySelector(".brand-mark") ? document.querySelector(".brand-mark").innerHTML : "")), html);
    await hold(500);
    if (during) await during();
    await hold(ms);
    await page.evaluate(() => window.__qgf.hideCard());
    events.push({ t: now(), type: "card_end" });
    await hold(550);
  };
  const ff = async (on) => {
    events.push({ t: now(), type: on ? "ff_start" : "ff_end" });
    await page.evaluate((o) => window.__qgf.ff(o), on);
  };
  const moveTo = async (loc, o = {}) => {
    const b = await loc.boundingBox();
    if (!b) return null;
    const x = b.x + b.width * (o.fx ?? 0.5);
    const y = b.y + b.height * (o.fy ?? 0.5);
    await page.mouse.move(x, y, { steps: o.steps ?? 30 });
    await hold(o.pause ?? 250);
    return { x, y };
  };
  const click = async (loc, o = {}) => {
    await moveTo(loc, o);
    await page.mouse.down();
    await hold(90);
    await page.mouse.up();
    await hold(o.after ?? 450);
  };
  const scrollTo = async (loc, block = "start", ms = 1300) => {
    await loc.evaluate((el, b) => el.scrollIntoView({ behavior: "smooth", block: b }), block);
    await hold(ms);
  };
  const scrollTop = async () => { await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" })); await hold(1200); };
  const nav = async (label) => click(page.getByRole("link", { name: label, exact: true }), { after: 600 });
  const dragRange = async (loc, target) => {
    const [val, min, max] = await loc.evaluate((el) => [Number(el.value), Number(el.min), Number(el.max)]);
    const b = await loc.boundingBox();
    const px = (v) => b.x + 8 + (b.width - 16) * ((v - min) / (max - min));
    const y = b.y + b.height / 2;
    await page.mouse.move(px(val), y, { steps: 25 });
    await hold(200);
    await page.mouse.down();
    await page.mouse.move(px(target), y, { steps: 45 });
    await page.mouse.up();
    await hold(600);
  };
  const textOf = async (loc) => ((await loc.first().textContent()) || "").trim();

  const MARK_CARD = (num, title, sub) => `<div class="num">${num}</div><h1>${title}</h1><p>${sub}</p>`;

  // ---------------------------------------------------------------- start
  await page.goto(BASE + "/");
  await page.getByRole("heading", { level: 1 }).filter({ hasText: "India" }).waitFor({ timeout: 60000 });
  await page.locator(".leaflet-container").waitFor();
  await hold(2500);
  await page.mouse.move(960, 560);
  await client.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  events.push({ t: now(), type: "start" });

  // ---------------------------------------------------------------- intro
  await card(`<div class="mark">{MARK}</div><div class="kick">SIH 2026 &middot; Problem statement 26138 &middot; Egreen Quanta</div>
    <h1>Q-GreenFleet</h1><p>Quantum-inspired fuel prediction and green fleet optimization</p>
    <div class="foot">Prototype walkthrough &middot; Clean &amp; Green Technology</div>`, 3600);

  // ---------------------------------------------------------------- overview
  const K1 = "The problem";
  await caption(K1, "India coastal & near-sea network: 12 real services, from JNPT–Mundra and Chennai–Singapore to Mundra–Rotterdam.",
    "This is our India case study: twelve real coastal and near-sea services, from JNPT to Mundra and Chennai to Singapore, all the way to Mundra and Rotterdam.");
  await moveTo(page.locator(".leaflet-container").first(), { fx: 0.62, fy: 0.55, steps: 40 });
  await hold(1500);
  await moveTo(page.locator(".leaflet-container").first(), { fx: 0.42, fy: 0.35, steps: 40 });
  await hold(1500);
  await moveTo(page.locator(".hero").first(), { steps: 40 });
  await say(K1, "Run the way fleets run today (VLSFO at full schedule speed), it emits about 2.1 Mt CO₂e a year, and 11 of 12 services fail the 2030 CII limit.",
    "Run the way fleets run today, on VLSFO at full schedule speed, this network emits about two point one million tonnes of CO2-equivalent a year, and eleven of the twelve services fail the 2030 carbon-intensity limit.");
  await hideCaption();

  // ---------------------------------------------------------------- optimizer
  await card(MARK_CARD("01", "Optimise the whole fleet", "Vessel mix &middot; capacity &middot; speed &middot; fuel &middot; shore power"), 800,
    async () => { await nav("Fleet optimizer"); });
  const K2 = "Fleet optimizer";
  await moveTo(page.locator("select").nth(1), { steps: 40 });
  await say(K2, "Scenario: India 2030. IMO CII, FuelEU Maritime and EU ETS are built in, and every assumption is editable.",
    "The scenario is India in 2030. IMO's carbon-intensity rules, FuelEU Maritime and the EU emissions trading system are built in, and every assumption can be edited.", -800);
  const algo = page.getByRole("button", { name: "Run optimization" }).locator("xpath=..").locator("select").first();
  await moveTo(algo, { steps: 35 });
  await say(K2, "QMOEA-H, our quantum-inspired optimiser, decides vessel mix, capacity, speed, fuel and shore power for all 12 routes at once.",
    "Our quantum-inspired optimiser, QMOEA-H, decides the vessel mix, capacity, speed, fuel and shore power for all twelve routes at once.", -900);
  await click(page.getByRole("button", { name: "Run optimization" }), { after: 200 });
  await scrollTo(page.getByRole("heading", { name: "Trade-off: emissions vs cost" }), "center", 900);
  await caption(K2, "Each dot is a complete fleet plan. The front of best trade-offs streams in live, far below today's plans (grey markers).",
    "Every dot is a complete fleet plan. The front of best trade-offs streams in live, far below today's reference plans in grey.");
  await moveTo(page.locator(".js-plotly-plot").first(), { fx: 0.3, fy: 0.6, steps: 60 });
  await page.getByText("Pareto-optimal plans ·").waitFor({ timeout: 240000 });
  await hold(1800);
  const status = await textOf(page.getByText("Pareto-optimal plans ·"));
  const nPlans = (status.match(/^(\d+)/) || [])[1] || "100+";
  await say(K2, `Done: ${nPlans} Pareto-optimal plans out of 6,000 evaluated. The recommended plan sits at the knee of the curve.`,
    `In a few seconds it evaluates six thousand plans and keeps ${nPlans} Pareto-optimal ones. The recommended plan sits at the knee of the curve.`, -400);
  const expl = await textOf(page.getByText(/This plan changes well-to-wake GHG/));
  const m = expl.match(/GHG by (-?[\d.]+) %, fuel by (-?[\d.]+) % and annual cost by (-?[\d.]+) %/);
  const [dG, dF, dC] = m ? m.slice(1).map((v) => Math.round(Math.abs(Number(v)))) : [59, 52, 25];
  await scrollTo(page.getByRole("heading", { name: "Recommended (balanced)" }), "start");
  await moveTo(page.locator(".stat").first(), { steps: 40 });
  await say(K2, `Recommended plan: ${dG} % less well-to-wake GHG, ${dF} % less fuel and ${dC} % lower cost than today, with every constraint met.`,
    `The recommended plan cuts well-to-wake greenhouse gas by ${dG} percent, fuel by ${dF} percent and cost by ${dC} percent compared with today, and it meets every constraint.`);
  await moveTo(page.getByText(/This plan changes well-to-wake GHG/).first(), { fx: 0.2, steps: 35 });
  await say(K2, "It explains itself in plain words: which routes switch to LNG or ammonia, where to slow-steam, and where to plug into shore power.",
    "And it explains itself in plain words: which routes switch to LNG or ammonia, where to slow down, and where to plug into shore power.");
  await scrollTo(page.getByRole("heading", { name: "Fleet allocation map" }), "start");
  await caption(K2, "Fleet allocation on the map, and the emission profile of every service.",
    "Here is the fleet allocation on the map, next to the emission profile of every service.");
  await moveTo(page.locator(".leaflet-container").last(), { fx: 0.5, fy: 0.45, steps: 45 });
  await hold(1800);
  await moveTo(page.getByRole("heading", { name: "Emission profile by service" }).locator("xpath=../.."), { fx: 0.55, fy: 0.3, steps: 45 });
  await hold(1800);
  await scrollTo(page.getByRole("heading", { name: "Fleet allocation", exact: true }), "start");
  await say(K2, "Per service: vessel class and capacity, number of ships, speed, fuel, shore power and the resulting CII rating.",
    "For each service you get the vessel class and capacity, the number of ships, the speed, the fuel, shore power, and the resulting CII rating.", -700);
  await scrollTo(page.getByRole("heading", { name: "Recommended (balanced)" }), "start", 1000);
  await page.evaluate(() => { window.__qgfReport = null; });
  await click(page.getByRole("button", { name: "Download decision report" }), { after: 200 });
  await caption(K2, "One click builds a decision report for managers: the plan, compliance, robustness and abatement costs.",
    "One more click builds a decision report for managers, with the plan, its compliance, its robustness and its abatement costs.");
  await hold(1200);
  await ff(true);
  await page.waitForFunction(() => window.__qgfReport, null, { timeout: 180000 });
  await ff(false);
  const html = await page.evaluate(() => window.__qgfReport);
  await page.evaluate((h) => window.__qgf.report(h), html);
  await hold(1800);
  const rh = await page.evaluate(() => window.__qgf.reportHeight());
  for (const f of [0.35, 0.7]) {
    await page.evaluate((y) => window.__qgf.reportScroll(y), Math.round(rh * f));
    await hold(1700);
  }
  await page.evaluate(() => window.__qgf.hideReport());
  await hideCaption();

  // ---------------------------------------------------------------- compliance
  await card(MARK_CARD("02", "Stay compliant", "IMO CII &middot; FuelEU Maritime &middot; EU ETS, year by year"), 800,
    async () => { await nav("Compliance"); await scrollTop(); });
  const K3 = "Compliance";
  await caption(K3, "For the chosen plan: the CII rating of every service, the FuelEU pool against its tightening limit, and EU ETS exposure.",
    "For the chosen plan you see the CII rating of every service, the FuelEU pool against a limit that tightens every year, and the EU ETS exposure.");
  await hold(3000);
  await scrollTo(page.getByRole("heading", { name: "FuelEU Maritime GHG-intensity limit" }), "center", 3200);
  await hideCaption();

  // ---------------------------------------------------------------- prediction
  await card(MARK_CARD("03", "Predict fuel for any ship", "Speed &middot; load &middot; weather &middot; vessel type"), 800,
    async () => { await nav("Fuel prediction"); await scrollTop(); });
  const K4 = "Fuel prediction · Q-PHYS";
  await page.getByText("Speed-fuel curve at these conditions").waitFor();
  await say(K4, "Q-PHYS predicts fuel from speed, load, weather and vessel type: a physics model plus a quantum-inspired tensor network.",
    "Q-PHYS predicts fuel from speed, load, weather and vessel type. It combines a physics model with a quantum-inspired tensor network.", -900);
  const ranges = page.locator("input[type=range]");
  await caption(K4, "Speed up and fuel rises steeply. The model is certified never to predict less fuel at a higher speed.",
    "Speed up and fuel rises steeply. The model is certified never to predict less fuel at a higher speed, so the optimiser can trust it.");
  const [sv, , smax] = await ranges.nth(0).evaluate((el) => [Number(el.value), Number(el.min), Number(el.max)]);
  await dragRange(ranges.nth(0), Math.min(smax, sv + (smax - sv) * 0.8));
  await hold(2600);
  await caption(K4, "Rougher seas add fuel, and the 90 % confidence band scales with the prediction.",
    "Rougher seas add fuel, and the ninety percent confidence band scales with the prediction.");
  await dragRange(ranges.nth(4), 4.5);
  await hold(2400);
  const fuelSel = page.locator("select").nth(1);
  await moveTo(fuelSel, { steps: 35 });
  await fuelSel.selectOption("AMMONIA_E");
  await say(K4, "Switch the fuel system to e-ammonia: fuel mass and well-to-wake emissions update instantly.",
    "Switch the fuel system to e-ammonia, and the fuel mass and well-to-wake emissions update instantly.", -900);
  await scrollTo(page.getByRole("heading", { name: "Inside the tensor network" }), "center");
  await moveTo(page.getByRole("heading", { name: "Inside the tensor network" }).locator("xpath=../.."), { fx: 0.5, fy: 0.6, steps: 40 });
  await say(K4, "Inside the tensor network: entanglement entropy shows which inputs the model couples, a view borrowed from quantum physics.",
    "Inside the tensor network, entanglement entropy shows which inputs the model couples, a view borrowed straight from quantum physics.", -400);
  await hideCaption();

  // ---------------------------------------------------------------- lab
  await card(MARK_CARD("04", "Plan the transition", "2025 &rarr; 2050 pathway &middot; abatement costs &middot; exact optimum &middot; quantum annealing"), 800,
    async () => { await nav("Fuel & policy lab"); await scrollTop(); });
  const K5 = "Fuel & policy lab";
  await caption(K5, "2025 → 2050: every milestone year is optimised under that year's rules, prices and fuel availability.",
    "Now the transition to 2050. Every milestone year is optimised under that year's rules, prices and fuel availability.");
  await click(page.getByRole("button", { name: "Run pathway" }), { after: 800 });
  await ff(true);
  await page.getByRole("button", { name: "Run pathway" }).waitFor({ timeout: 300000 });
  await ff(false);
  await hold(800);
  await scrollTo(page.getByRole("heading", { name: /Transition pathway/ }), "start", 1000);
  await moveTo(page.locator(".js-plotly-plot").first(), { fx: 0.5, fy: 0.5, steps: 40 });
  await say(K5, "The fuel mix shifts decade by decade as the targets tighten, while emissions keep falling.",
    "The fuel mix shifts decade by decade as the targets tighten, while emissions keep falling.", 200);
  await scrollTo(page.getByRole("heading", { name: "Marginal abatement cost curve" }), "start");
  await click(page.getByRole("heading", { name: "Marginal abatement cost curve" }).locator("xpath=../..").getByRole("button", { name: "Compute" }), { after: 300 });
  await caption(K5, "Marginal abatement cost curve: which measures save money, and which cost dollars per tonne of CO₂e avoided.",
    "The marginal abatement cost curve shows which measures save money, and which ones cost dollars per tonne of CO2 avoided.");
  await page.getByText("saves money").first().waitFor({ timeout: 120000 }).catch(() => {});
  await hold(3600);
  await scrollTo(page.getByRole("heading", { name: "Exact reference (MILP)" }), "start");
  await click(page.getByRole("button", { name: "Minimum cost" }), { after: 300 });
  await say(K5, "An exact MILP solves the discretised problem to true optimality in about a second: the yardstick for every heuristic.",
    "An exact MILP solves the discretised problem to true optimality in about a second. That is the yardstick we hold every heuristic to.", -800);
  await click(page.getByRole("button", { name: "Anneal" }), { after: 300 });
  await caption(K5, "The same fleet problem as a QUBO, solved by our own simulated quantum annealer and exportable unchanged to D-Wave hardware.",
    "The same fleet problem is also written as a QUBO, solved by our own simulated quantum annealer, and it can be sent unchanged to D-Wave quantum hardware.");
  const t0 = now();
  await hold(3500);
  let ffOn = false;
  if (!(await page.getByText("Gap to exact optimum").isVisible())) { await ff(true); ffOn = true; }
  await page.getByText("Gap to exact optimum").waitFor({ timeout: 300000 });
  if (ffOn) await ff(false);
  await hold(Math.max(0, 5200 - (now() - t0) * 1000));
  const gapTxt = await textOf(page.getByText("Gap to exact optimum").locator("xpath=..").locator(".value"));
  await moveTo(page.getByText("Gap to exact optimum").locator("xpath=.."), { steps: 35 });
  await say(K5, `Annealed plan: ${gapTxt} from the exact optimum on the same objective, and fully feasible.`,
    `The annealed plan lands ${gapTxt.replace("%", " percent")} from the exact optimum on the same objective, and it is fully feasible.`, -300);
  await hideCaption();

  // ---------------------------------------------------------------- benchmarks
  await card(MARK_CARD("05", "Benchmarked honestly", "Accuracy &middot; convergence &middot; solution quality &middot; scalability"), 800,
    async () => { await nav("Benchmarks"); await scrollTop(); });
  const K6 = "Benchmarks";
  await moveTo(page.getByText("Q-PHYS (quantum-inspired hybrid)").first(), { steps: 40 });
  await say(K6, "Prediction: Q-PHYS reaches 3.3 % error on known ships, ahead of LightGBM, random forest and neural networks on the same data.",
    "On prediction, Q-PHYS reaches three point three percent error on known ships, ahead of LightGBM, random forests and neural networks trained on the same data.", -400);
  await scrollTo(page.getByRole("heading", { name: "Front quality" }), "start");
  await moveTo(page.getByText("QMOEA-H (ours)").first(), { steps: 40 });
  await say(K6, "Optimisation: QMOEA-H ranks first against NSGA-II, NSGA-III and MOPSO, and lands within 1–3 % of the exact optimum.",
    "On optimisation, QMOEA-H ranks first against NSGA-II, NSGA-III and MOPSO, and lands within one to three percent of the exact optimum.", -300);
  await scrollTo(page.getByRole("heading", { name: "Scalability" }), "start");
  await say(K6, "We also show where classical methods still do better, such as MOPSO on very large, loosely constrained networks.",
    "And we show where classical methods still do better, such as MOPSO on very large, loosely constrained networks.", -700);
  await hideCaption();

  // ---------------------------------------------------------------- what-if
  const K7 = "What-if scenarios";
  await nav("Fleet optimizer");
  await scrollTop();
  const redSea = page.getByText("Red Sea closed (divert via Cape)");
  await click(redSea, { fx: 0.1, after: 600 });
  await say(K7, "What-if: close the Red Sea. The Europe service reroutes around the Cape of Good Hope (6,348 → 11,027 nm), ready to re-optimise.",
    "And what if the Red Sea closes? Tick one box, and the Europe service reroutes around the Cape of Good Hope, from about six thousand three hundred to eleven thousand nautical miles, ready to re-optimise.", -1400);
  await nav("Overview");
  await page.locator(".leaflet-container").first().waitFor();
  await hold(1200);
  await moveTo(page.locator(".leaflet-container").first(), { fx: 0.3, fy: 0.62, steps: 35 });
  await hold(1600);
  await hideCaption();

  // ---------------------------------------------------------------- outro
  await card(`<div class="mark">{MARK}</div><div class="kick">Q-GreenFleet &middot; SIH 2026 &middot; PS 26138</div>
    <h1>Predict every tonne.<br/>Optimise every voyage.</h1>
    <p>Working prototype &middot; FastAPI + React &middot; 71 automated tests &middot; one-command Docker</p>
    <div class="foot">github.com/DeepakSinghhh/PS-138</div>`, 4600);
  events.push({ t: now(), type: "end" });
  await hold(300);
  await client.send("Page.stopScreencast");
  await hold(300);
  fs.writeFileSync(path.join(__dirname, "timeline.json"), JSON.stringify({ frames, events }, null, 1));
  console.log(`frames=${frames.length} events=${events.length} duration=${(events.at(-1).t - events[0].t).toFixed(1)}s`);
  await browser.close();
})().catch(async (e) => {
  console.error("FAILED:", e);
  fs.writeFileSync(path.join(__dirname, "timeline.json"), JSON.stringify({ frames, events, error: String(e) }, null, 1));
  process.exit(1);
});
