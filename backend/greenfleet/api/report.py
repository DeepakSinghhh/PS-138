"""Self-contained, printable HTML decision report (PS Delivery Table item 4: report generation)."""

from __future__ import annotations

import datetime as dt
import html

FUEL_COLORS = {
    "conventional": "#6b7280", "lng": "#2a78b8", "methanol": "#c2791b", "ammonia": "#2e9d6b", "hydrogen": "#7c5cc4",
}


def _e(x) -> str:
    return html.escape(str(x))


class Money:
    """Display currency for the report: the model works in USD; rupees are shown at ``rate`` per USD."""

    def __init__(self, currency: str = "USD", rate: float = 88.0):
        self.inr = currency == "INR"
        self.rate = rate
        self.big_unit = "crore ₹" if self.inr else "M USD"
        self.unit_label = "₹" if self.inr else "USD"

    def big_value(self, musd: float) -> float:          # million USD -> crore rupees or M USD
        return musd * self.rate / 10 if self.inr else musd

    def big(self, musd: float) -> str:
        if musd == 0:                                    # "₹0 crore" reads oddly for a zero penalty
            return "₹0" if self.inr else "USD 0"
        return f"₹{self.big_value(musd):,.0f} crore" if self.inr else f"USD {musd:,.1f} M"

    def per_t(self, usd: float | None) -> str:
        return "-" if usd is None else f"{usd * (self.rate if self.inr else 1):,.0f}"


def _localise(text: str, money: Money) -> str:
    """Rewrite "USD 21.73 M" in backend sentences into the report's currency."""
    import re

    return re.sub(r"USD\s*([\d,.]+)\s*M\b", lambda m: money.big(float(m.group(1).replace(",", ""))), text)


def _bar_svg(items: list[tuple[str, float, str]], unit: str, width: int = 640, bar_h: int = 18) -> str:
    """Horizontal bar chart as inline SVG. items = (label, value, color)."""
    if not items:
        return ""
    vmax = max(v for _, v, _ in items) or 1.0
    label_w, pad = 190, 6
    h = len(items) * (bar_h + pad) + pad
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg">']
    for i, (label, v, color) in enumerate(items):
        y = pad + i * (bar_h + pad)
        w = (width - label_w - 90) * v / vmax
        out.append(f'<text x="{label_w - 8}" y="{y + bar_h * 0.72}" text-anchor="end" font-size="11" fill="#374151">{_e(label)}</text>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{max(w, 1):.1f}" height="{bar_h}" rx="1" fill="{color}"/>')
        out.append(f'<text x="{label_w + w + 6:.1f}" y="{y + bar_h * 0.72}" font-size="11" fill="#111827">{v:,.0f} {unit}</text>')
    out.append("</svg>")
    return "".join(out)


def _stack_svg(shares: dict[str, float], families: dict[str, str], width: int = 640) -> str:
    x, out = 0.0, [f'<svg viewBox="0 0 {width} 46" width="100%" xmlns="http://www.w3.org/2000/svg">']
    for fid, s in shares.items():
        w = width * s
        color = FUEL_COLORS.get(families.get(fid, "conventional"), "#9ca3af")
        out.append(f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="22" fill="{color}" stroke="#fff"/>')
        if w > 45:
            out.append(f'<text x="{x + 4:.1f}" y="38" font-size="10" fill="#374151">{_e(fid)} {100 * s:.0f}%</text>')
        x += w
    out.append("</svg>")
    return "".join(out)


def render(plan: dict, scenario: dict, explanation: dict | None = None, macc: dict | None = None,
           robustness: dict | None = None, algorithm: str | None = None, network_name: str = "",
           currency: str = "USD", usd_to_inr: float = 88.0) -> str:
    money = Money(currency, usd_to_inr)
    o = plan["objectives"]
    ex = explanation or {}
    dp = ex.get("delta_pct", {})
    families = {r["fuel"]: r["fuel_family"] for r in plan["routes"]}
    route_items = sorted(((f"{r['route_id']} {r['name'][:26]}", r["wtw_co2e_t"], FUEL_COLORS.get(r["fuel_family"], "#9ca3af"))
                          for r in plan["routes"]), key=lambda t: -t[1])
    cost_items = sorted(((f"{r['route_id']} {r['name'][:26]}", money.big_value(sum(r["cost_usd"].values()) / 1e6), "#0a6aa6")
                         for r in plan["routes"]), key=lambda t: -t[1])
    fe = plan["fleet"]["fueleu"]
    rows = "".join(
        f"<tr><td>{_e(r['route_id'])}</td><td>{_e(r['name'])}</td><td>{_e(r['vessel_label'])}</td>"
        f"<td class=n>{r['ships']}</td><td class=n>{r['speed_kn']:.1f}</td><td>{_e(r['fuel_label'])}</td>"
        f"<td>{'yes' if r['shore_power'] else '-'}</td><td class=n>{r['fuel_hfo_eq_t']:,.0f}</td>"
        f"<td class=n>{r['wtw_co2e_t']:,.0f}</td><td class=n>{money.big_value(sum(r['cost_usd'].values()) / 1e6):,.{0 if money.inr else 1}f}</td>"
        f"<td class='c r{r['cii']['rating']}'>{r['cii']['rating']}</td><td class=n>{100 * r['on_time_probability']:.0f}%</td></tr>"
        for r in plan["routes"])

    def kpi(label, value, unit, delta_key):
        d = dp.get(delta_key)
        dtxt = f'<div class="delta {"good" if (d or 0) < 0 else "bad"}">{d:+.1f}% vs current practice</div>' if d is not None else ""
        return f'<div class="kpi"><div class="kl">{label}</div><div class="kv">{value}</div><div class="ku">{unit}</div>{dtxt}</div>'

    macc_html = ""
    if macc:
        mrows = "".join(
            f"<tr><td>{_e(m['measure'])}</td><td class=n>{m['abatement_t']:,.0f}</td>"
            f"<td class=n>{money.per_t(m['usd_per_t'])}</td>"
            f"<td>{'yes' if m['feasible'] else 'no (other constraints)'}</td></tr>" for m in macc["measures"])
        macc_html = (f"<h2>Marginal abatement cost of single measures</h2><p class=muted>Each measure applied fleet-wide "
                     f"to the current-practice plan.</p><table><tr><th>Measure</th><th>Abatement t CO2e/yr</th>"
                     f"<th>{money.unit_label} per t</th><th>Feasible alone</th></tr>{mrows}</table>")
    rob_html = ""
    if robustness:
        c, e = robustness["cost"], robustness["emissions"]
        rob_html = (f"<h2>Robustness (Monte Carlo)</h2><p>Under fuel-price (log-normal, σ = 25 %), carbon-price (±30 %) "
                    f"and weather (±0.5 Beaufort) uncertainty the plan's annual cost has mean {money.big(c['mean'])} "
                    f"(P5 {money.big(c['p5'])}, P95 {money.big(c['p95'])}, CVaR95 {money.big(c['cvar95'])}); WtW emissions mean "
                    f"{e['mean']:,.0f} t (P95 {e['p95']:,.0f} t).</p>")
    sc_items = "".join(f"<li><b>{_e(k)}</b>: {_e(v)}</li>" for k, v in scenario.items()
                       if k not in ("custom_routes",) and v not in (None, [], {}))
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Q-GreenFleet decision report</title>
<style>
body {{ font: 13px/1.55 'Archivo', 'Helvetica Neue', Arial, system-ui, sans-serif; color: #121518; background: #f3f1ec; margin: 0; }}
main {{ max-width: 980px; margin: 0 auto; padding: 28px 24px 60px; }}
h1 {{ font-size: 30px; font-weight: 700; line-height: 1.1; letter-spacing: -.03em; margin: 18px 0 6px; }} h2 {{ font-size: 18px; font-weight: 700; line-height: 1.3; margin: 34px 0 12px; border-top: 1px solid #121518; padding-top: 10px; }}
.brand {{ display: flex; align-items: center; gap: 10px; padding-bottom: 14px; border-bottom: 2px solid #121518; }}
.bn {{ font-size: 17px; font-weight: 700; line-height: 1.1; letter-spacing: -.02em; }} .bs {{ font: 10.5px 'IBM Plex Mono', ui-monospace, monospace; color: #6e7279; letter-spacing: .08em; text-transform: uppercase; }}
.muted {{ color: #6e7279; }} table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
th, td {{ border-bottom: 1px solid #dcd8cf; padding: 5px 8px 5px 0; text-align: left; vertical-align: top; }}
th {{ font: 10.5px 'IBM Plex Mono', ui-monospace, monospace; color: #6e7279; border-bottom-color: #121518; }} td.n {{ text-align: right; font-variant-numeric: tabular-nums; }} td.c {{ text-align: center; font-weight: 700; }}
.rA {{ color: #047857; }} .rB {{ color: #15803d; }} .rC {{ color: #a16207; }} .rD {{ color: #c2410c; }} .rE {{ color: #b91c1c; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 18px; margin: 16px 0; }}
.kpi {{ border-top: 1px solid #121518; padding-top: 8px; }} .kl {{ font: 10px 'IBM Plex Mono', ui-monospace, monospace; color: #6e7279; text-transform: uppercase; letter-spacing: .07em; }}
.kv {{ font-size: 26px; font-weight: 700; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }} .ku {{ color: #4a4f56; font-size: 11px; }}
.delta {{ font-size: 12px; margin-top: 2px; }} .good {{ color: #17692d; }} .bad {{ color: #b3261e; }}
.note {{ border-left: 2px solid #121518; padding: 2px 0 2px 14px; margin: 14px 0; }}
.legend span {{ display: inline-block; margin-right: 12px; font-size: 11px; }} .legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 1px; margin-right: 4px; vertical-align: -1px; }}
@media print {{ main {{ padding: 0; }} h2 {{ break-after: avoid; }} table {{ break-inside: auto; }} tr {{ break-inside: avoid; }} }}
</style></head><body><main>
<div class="brand"><svg viewBox="0 0 64 64" width="34" height="34" aria-hidden="true"><mask id="wl"><rect width="64" height="64" fill="#fff"/><path d="M0 34 C8 29 14 29 21 33.5 S33 38 40 33.5 S54 29 64 34" stroke="#000" stroke-width="10.5" fill="none"/></mask><circle cx="32" cy="32" r="18.5" fill="none" stroke="#121518" stroke-width="5.2" mask="url(#wl)"/><path d="M5 34 C11.5 30.1 16 30.1 22.2 33.8 S34.4 37.6 40.6 33.8 S52 30.1 59 33.3" stroke="#0a6aa6" stroke-width="4.6" stroke-linecap="round" fill="none"/></svg><div><div class="bn">Q-GreenFleet</div><div class="bs">Decision report</div></div></div>
<h1>Green fleet deployment plan</h1>
<div class="muted">{_e(network_name)} · year {scenario.get('year')} · generated {now} by Q-GreenFleet{(' · optimiser: ' + _e(algorithm)) if algorithm else ''}</div>
<div class="kpis">
{kpi('Fuel', f"{o['fuel']:,.0f}", 't HFO-eq / yr', 'fuel')}
{kpi('WtW GHG', f"{o['emissions']:,.0f}", 't CO2e / yr', 'emissions')}
{kpi('Annual cost', f"{money.big_value(o['cost']):,.{0 if money.inr else 1}f}", money.big_unit + ' / yr', 'cost')}
<div class="kpi"><div class="kl">Fleet</div><div class="kv">{plan['fleet']['ships']}</div><div class="ku">ships · {plan['fleet']['shore_power_routes']} services on shore power</div></div>
</div>
<div class="note">{_e(_localise(ex.get('summary', ''), money))}</div>
<h2>Fleet allocation</h2>
<table><tr><th>Route</th><th>Service</th><th>Vessel class</th><th>Ships</th><th>Speed kn</th><th>Fuel</th><th>Shore power</th>
<th>Fuel t HFO-eq</th><th>WtW t CO2e</th><th>Cost {money.big_unit}</th><th>CII</th><th>On time</th></tr>{rows}</table>
<h2>Emission profile</h2>
<div class="legend">{''.join(f'<span><i style="background:{c}"></i>{f}</span>' for f, c in FUEL_COLORS.items())}</div>
<p class=muted>Well-to-wake GHG per service (fuel lifecycle + shore-power grid electricity).</p>
{_bar_svg(route_items, 't')}
<p class=muted>Energy mix of the fleet (incl. pilot fuel).</p>
{_stack_svg(plan['fleet']['fuel_mix_energy_share'], {**families, 'MGO': 'conventional'})}
<h2>Cost profile</h2>
{_bar_svg(cost_items, money.big_unit)}
<h2>Regulatory compliance</h2>
<ul>
<li>IMO CII ({_e(scenario.get('cii_min_rating', 'C'))} or better required): ratings {', '.join(f"{k} × {sum(r['cii']['rating'] == k for r in plan['routes'])}" for k in 'ABCDE' if any(r['cii']['rating'] == k for r in plan['routes']))}.</li>
<li>FuelEU Maritime pool: {fe['intensity_g_per_mj']:.2f} gCO2e/MJ vs target {fe['target_g_per_mj']:.2f}; balance {fe['balance_t_co2e']:,.0f} t CO2e; penalty {money.big(fe['penalty_usd'] / 1e6)} (in-scope energy {fe['in_scope_energy_gj']:,.0f} GJ).</li>
<li>EU ETS cost: {money.big(sum(r['cost_usd']['eu_ets'] for r in plan['routes']) / 1e6)} / yr.</li>
<li>Plan feasibility: {'all constraints satisfied' if plan['feasible'] else 'violations: ' + ', '.join(k for k, v in plan['violations'].items() if v > 0)}.</li>
</ul>
{macc_html}
{rob_html}
<h2>Scenario</h2><ul class=muted>{sc_items}</ul>
<h2>Method</h2>
<p class=muted>Fuel consumption is predicted by Q-PHYS: a physics prior (IMO Fourth GHG Study power model, Kwon weather
correction, SFOC load curve) combined with a QPSO-tuned monotone gradient-boosting model and a Matrix-Product-State
tensor network, with split-conformal intervals. Fleet plans are optimised by QMOEA-H, a quantum-inspired multi-objective
evolutionary algorithm (qudit superposition crossover, quantum memory register, delta-well speed moves, Hadamard reset)
minimising fuel, well-to-wake GHG and cost under demand, schedule, fleet, CII and FuelEU constraints. Emission factors follow
FuelEU Maritime Annex II; CII follows IMO MEPC.353/354/400. All algorithms run on classical hardware; alternative-fuel
figures are model-based scenario estimates.</p>
</main></body></html>"""
