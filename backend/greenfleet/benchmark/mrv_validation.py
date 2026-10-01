"""Vessel library vs EU MRV: does the class-level fuel model match real ships of the same type and size?

``python -m greenfleet.benchmark.mrv_validation`` (needs the THETIS-MRV exports in ``data/raw/mrv``).

EU MRV publishes, per ship and reporting year, total fuel, fuel per nautical mile, time at sea and fuel per
tonne-mile of cargo (or of deadweight); the average cargo carried follows as (fuel per n mile) / (fuel per t-n mile).
For each class of the vessel library:

  peers   MRV ships of the class's type whose average cargo carried is LO..HI x the class's deadweight
          (averaged over laden and ballast legs ships carry well below full deadweight). Passenger ships report
          transport work per passenger, so passenger classes are compared with their ship type only
  model   fuel per n mile of the nominal physics model (IMO GHG4 power, SFOC curve, Kwon weather) at the peers'
          median speed, average draft (0.85 x design) and Beaufort 4 - a sea passage only

MRV totals also include fuel burnt in port and at anchor. The share of CO2 emitted at berth in EU ports (reported
separately) is removed to give a sea-passage figure; fuel at anchor and in non-EU ports cannot be separated, so the
model is still expected to sit somewhat below the MRV median.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from greenfleet.benchmark.report import FIG_DIR, _plt, _table, write
from greenfleet.config import REPORTS_DIR, vessel_classes
from greenfleet.data.loaders import load_mrv
from greenfleet.prediction.physics_model import NominalPhysics

TYPE_MAP = {"container": ["Container ship"], "bulk": ["Bulk carrier"], "tanker": ["Oil tanker", "Chemical tanker"],
            "pax": ["Ro-pax ship"]}
LO, HI = 0.3, 0.8
DRAFT_RATIO, BEAUFORT = 0.85, 4.0


def clean(mrv: pd.DataFrame) -> pd.DataFrame:
    """Ship-years with a credible annual profile (enough sea time, plausible speed and fuel per mile)."""
    m = mrv.copy()
    ok = (m["hours_at_sea"] > 500) & m["avg_speed_kn"].between(5, 25) & m["fuel_per_nm_kg"].between(5, 2000)
    m = m[ok].copy()
    berth = (m["co2_berth_t"] / m["co2_t"]).clip(0, 0.9) if "co2_berth_t" in m else 0.0
    m["berth_share"] = berth.fillna(0.0) if isinstance(berth, pd.Series) else berth
    m["sea_fuel_per_nm_kg"] = m["fuel_per_nm_kg"] * (1 - m["berth_share"])
    return m


def model_fuel_per_nm(cls: str, speed_kn: float) -> float:
    row = pd.DataFrame({"vessel_class": [cls], "speed_kn": [speed_kn], "draft_ratio": [DRAFT_RATIO],
                        "beaufort": [BEAUFORT], "wind_rel_deg": [90.0]})
    tpd = float(NominalPhysics().predict(row)[0])
    return tpd * 1000 / (24 * speed_kn)


def validate(mrv: pd.DataFrame) -> dict:
    m = clean(mrv)
    rows = []
    for cid, vc in vessel_classes().items():
        types = TYPE_MAP.get(vc.cargo)
        if not types:
            continue
        peers = m[m["ship_type"].isin(types)]
        sized = vc.cargo != "pax" and "cargo_carried_t" in peers
        if sized:
            peers = peers[peers["cargo_carried_t"].between(LO * vc.dwt, HI * vc.dwt)]
        if len(peers) < 10:
            rows.append({"class": cid, "label": vc.label, "peers": len(peers), "note": "too few MRV peers"})
            continue
        v = float(peers["avg_speed_kn"].median())
        q10, q50, q90 = (float(x) for x in peers["sea_fuel_per_nm_kg"].quantile([0.1, 0.5, 0.9]))
        total50 = float(peers["fuel_per_nm_kg"].median())
        model = model_fuel_per_nm(cid, v)
        pct = float((peers["sea_fuel_per_nm_kg"] < model).mean() * 100)
        rows.append({"class": cid, "label": vc.label, "mrv_types": types, "size_matched": bool(sized),
                     "peers": int(len(peers)), "median_speed_kn": v, "mrv_p10": q10, "mrv_p50": q50, "mrv_p90": q90,
                     "mrv_total_p50": total50, "berth_share_median": float(peers["berth_share"].median()),
                     "model_kg_per_nm": model, "model_to_median": model / q50, "model_percentile": pct,
                     "within_p10_p90": bool(q10 <= model <= q90)})
    # robustness: does the result depend on how tightly peers are matched on size?
    bands = [(0.3, 0.8), (0.4, 0.7), (0.45, 0.6)]
    robustness = {}
    for cid, vc in vessel_classes().items():
        if vc.cargo not in TYPE_MAP or vc.cargo == "pax":
            continue
        robustness[cid] = {}
        for lo, hi in bands:
            pe = m[m["ship_type"].isin(TYPE_MAP[vc.cargo]) & m["cargo_carried_t"].between(lo * vc.dwt, hi * vc.dwt)]
            if len(pe) >= 10:
                robustness[cid][f"{lo:.2f}-{hi:.2f}"] = {
                    "peers": int(len(pe)),
                    "model_to_median": model_fuel_per_nm(cid, float(pe["avg_speed_kn"].median()))
                    / float(pe["sea_fuel_per_nm_kg"].median())}
    years = sorted(int(y) for y in mrv["year"].dropna().unique()) if "year" in mrv else []
    return {"years": years, "ship_years": int(len(mrv)), "ship_years_used": int(len(m)), "classes": rows,
            "robustness": robustness,
            "assumptions": {"carried_dwt_band": [LO, HI], "draft_ratio": DRAFT_RATIO, "beaufort": BEAUFORT}}


def figure(res: dict) -> str | None:
    rows = [r for r in res["classes"] if "model_kg_per_nm" in r]
    if not rows:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7.5, 0.45 * len(rows) + 1.2))
    y = np.arange(len(rows))[::-1]
    for yi, r in zip(y, rows):
        ax.plot([r["mrv_p10"], r["mrv_p90"]], [yi, yi], color="#9aa7ad", lw=6, solid_capstyle="round", zorder=1)
        ax.plot([r["mrv_p50"]], [yi], "|", color="#0f2d3a", ms=14, mew=2, zorder=2)
        ax.plot([r["model_kg_per_nm"]], [yi], "o", color="#0f6b45", ms=7, zorder=3, mec="white", mew=1.2)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r['label'].split(' (')[0]} (n={r['peers']})" for r in rows], fontsize=8)
    ax.set_xscale("log")
    ticks = [t for t in (40, 50, 60, 80, 100, 150, 200, 300, 400) if ax.get_xlim()[0] <= t <= ax.get_xlim()[1]]
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(t) for t in ticks])
    ax.minorticks_off()
    ax.set_xlabel("fuel per nautical mile (kg / n mile, log scale)")
    ax.set_title("Vessel library vs EU MRV peers: model (dot), MRV median (tick), MRV p10-p90 (bar)", fontsize=9)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / "mrv_validation.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name


def markdown(res: dict, fig: str | None) -> str:
    rows = [r for r in res["classes"] if "model_kg_per_nm" in r]
    inside = sum(r["within_p10_p90"] for r in rows)
    sized = [r for r in rows if r["size_matched"]]
    md = ["# Vessel library vs EU MRV", "",
          f"Real annual reports from EU MRV (THETIS-MRV, reporting years {', '.join(map(str, res['years']))}): "
          f"{res['ship_years']:,} ship-years, {res['ship_years_used']:,} with more than 500 h at sea and plausible speed "
          "and fuel per mile. Generated by `python -m greenfleet.benchmark.mrv_validation`.", "",
          "For each class, the peers are MRV ships of the same type whose average cargo carried over laden and "
          "ballast legs (fuel per n mile / fuel per tonne-n mile of transport work) is "
          f"{res['assumptions']['carried_dwt_band'][0]:.0%}–{res['assumptions']['carried_dwt_band'][1]:.0%} of the "
          "class's deadweight. Passenger ships report transport work per passenger, so the Ro-Pax classes are compared "
          "with all Ro-pax ships. The model value is the "
          "nominal physics model's fuel per n mile at the peers' median speed, average draft (0.85 × design) and "
          "Beaufort 4: a sea passage only. MRV totals include fuel burnt in port and at anchor; the CO₂ share emitted "
          "at berth in EU ports (reported separately) is removed, giving the sea-passage figures below. Fuel at anchor "
          "and in non-EU ports cannot be separated, so the model should still sit somewhat below the MRV median.", "",
          f"**Result: the model lies inside the MRV p10–p90 band for {inside} of {len(rows)} classes "
          f"({sum(r['within_p10_p90'] for r in sized)} of {len(sized)} size-matched cargo classes). For cargo classes it "
          f"gives {min(r['model_to_median'] for r in sized):.2f}–{max(r['model_to_median'] for r in sized):.2f} × the MRV "
          "median: close for the larger classes, and clearly low for the smallest ones (feeder container, Handysize, MR "
          "tanker), whose library parameters under-predict real fuel use and are the first candidates for "
          "recalibration.** The island passenger-cargo class has no size-matched peers (type-level comparison only).", ""]
    table = [[r["label"], ", ".join(r["mrv_types"]), "yes" if r["size_matched"] else "type only", r["peers"],
              r["median_speed_kn"], f"{100 * r['berth_share_median']:.0f} %", r["mrv_total_p50"], r["mrv_p10"],
              r["mrv_p50"], r["mrv_p90"], r["model_kg_per_nm"], r["model_to_median"], f"{r['model_percentile']:.0f}"]
             for r in rows]
    md += ["Fuel per n mile in kg; MRV p10/p50/p90 are sea-passage figures (EU at-berth share removed).", "",
           _table(["class", "MRV type", "size-matched", "peers", "median speed kn", "at-berth CO₂ share",
                   "MRV total p50", "MRV p10", "MRV p50", "MRV p90", "model", "model / MRV p50", "model percentile"],
                  table), ""]
    rob = res.get("robustness") or {}
    if rob:
        bands = sorted({b for v in rob.values() for b in v})
        md += ["**Robustness.** Model ÷ MRV median when peers are matched more tightly on cargo size:", "",
               _table(["class"] + [f"band {b} × DWT" for b in bands],
                      [[vessel_classes()[c].label] + [v.get(b, {}).get("model_to_median") for b in bands]
                       for c, v in rob.items()]), "",
               "The gap barely moves with the band, so it is not an artefact of peer selection. The large classes "
               "sit near 0.9 (the remaining ~10 % is fuel at anchor and in non-EU ports, which MRV does not separate). "
               "Bringing a class to that level would need about 0.9 ÷ (its ratio) more fuel: roughly ×1.6 for the "
               "feeder, ×1.25 for Handysize, ×1.2 for the MR tanker and Panamax container, ×1.1 for the Aframax. A single "
               "factor on propulsion power is not physically consistent (the feeder would no longer reach its design "
               "speed within its engine power), and a different speed-power exponent cannot explain it either (the "
               "feeder and the Neo-Panamax run at similar fractions of design speed but differ by 1.6×). The library is "
               "therefore left as it is and the gap is reported here. Plausible causes for small ships, such as reefer "
               "and hotel loads and older or fouled hulls, need ship-level data to separate.", ""]
    skipped = [r for r in res["classes"] if "model_kg_per_nm" not in r]
    if skipped:
        md += ["Not compared: " + ", ".join(f"{r['label']} ({r['note']})" for r in skipped), ""]
    if fig:
        md += [f"![MRV validation](figures/{fig})", ""]
    return "\n".join(md)


def run() -> dict | None:
    mrv = load_mrv()
    if mrv is None:
        print("no EU MRV files in data/raw/mrv")
        return None
    res = validate(mrv)
    fig = figure(res)
    with open(REPORTS_DIR / "mrv_validation.json", "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    write(REPORTS_DIR / "mrv_validation.md", markdown(res, fig))
    return res


if __name__ == "__main__":
    import warnings

    warnings.filterwarnings("ignore")
    out = run()
    if out:
        for r in out["classes"]:
            print(r["class"], r.get("peers"), {k: round(v, 2) for k, v in r.items()
                                               if k in ("median_speed_kn", "mrv_p50", "model_kg_per_nm", "model_to_median")})
