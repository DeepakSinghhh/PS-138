"""Green fleet deployment problem: mathematical model and vectorised evaluator.

Decision variables per route r (PS Delivery Table item 2)
    k_r  vessel class (type and capacity)       categorical
    f_r  fuel / production pathway              categorical (only fuels bunkerable within range)
    s_r  shore power at berth                   binary      (only where a port has OPS)
    e_r  extra ships above the minimum fleet    integer 0..E-1
    u_r  speed position in [v_lo, v_max]        continuous  (v_lo = slowest speed that still meets demand)

Derived: round trips N_r = max(D_r / (cap_eff * LF), 52 for weekly liners); fleet size
n_r = n_min + e_r with n_min the smallest fleet that can serve demand at v_max; the time
budget per round trip RTT = n_r * H / N_r; the commanded speed v_r = v_lo + u_r (v_max - v_lo).
Extra ships and lower speeds trade charter cost for fuel (the classic slow-steaming trade-off).

Objectives (minimise)
    fuel       total fuel energy in tonnes of HFO-equivalent per year
    emissions  well-to-wake GHG, t CO2e / yr (fuel WtW + shore-power grid electricity)
    cost       M USD / yr: charter (+ alternative-fuel premium), fuel, electricity, EU ETS,
               optional global levy, and the pooled FuelEU penalty
    schedule_risk (optional) demand-weighted probability of arriving late, %

Constraints (aggregated into a violation CV, Deb's constrained dominance)
    demand and frequency     guaranteed by construction (n_min, v_lo)
    schedule reliability     P(on time) >= threshold  (weather delay vs. buffer + 50 % speed-up margin)
    fleet availability       ships used per class <= ships available
    CII                      every ship rated `min_rating` or better
    FuelEU Maritime          pooled compliance balance >= 0 when fueleu_mode == "hard"
    fleet emission cap       optional WtW cap
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from greenfleet.config import fuel_library, regulations
from greenfleet.physics.emissions import wtw_g_per_mj
from greenfleet.physics.propulsion import max_service_speed, propulsion_power_kw, sfoc_multiplier, weather_power_factor
from greenfleet.prediction.surrogate import FuelCorrection, loading_states
from greenfleet.regulations import cii, ets, fueleu
from greenfleet.scenarios.scenario import OBJECTIVE_LABELS, ResolvedScenario

HOURS_AVAILABLE = 8760 * 0.95
AUX_BSEC = 8.3                   # MJ/kWh, 4-stroke auxiliary engines
HFO_MJ_PER_T = 40500.0
RECOVERY_SHARE = 0.5             # share of the speed margin a master may use to recover delays
N_GRID = 40


def state_draft_ratio(vc, load: float) -> float:
    if vc.cargo == "pax":
        return 0.93 + 0.07 * load
    dr_ballast = vc.ballast_draft_m / vc.design_draft_m
    return dr_ballast + (1 - dr_ballast) * load**0.9


@dataclass
class Genes:
    cat: np.ndarray    # (P, 4R) int: class, fuel, ops, extra-ships option index per route
    u: np.ndarray      # (P, R) float in [0, 1]

    def __len__(self):
        return len(self.u)

    def take(self, idx) -> Genes:
        return Genes(self.cat[idx].copy(), self.u[idx].copy())

    @staticmethod
    def concat(parts: list[Genes]) -> Genes:
        return Genes(np.vstack([p.cat for p in parts]), np.vstack([p.u for p in parts]))


class FleetProblem:
    def __init__(self, rs: ResolvedScenario, correction: FuelCorrection | None = None):
        self.rs = rs
        sc = rs.scenario
        self.objectives = [o for o in sc.objectives if o in OBJECTIVE_LABELS] or ["fuel", "emissions", "cost"]
        self.n_obj = len(self.objectives)
        self.correction = correction if correction is not None else (
            FuelCorrection.load() if sc.use_surrogate else FuelCorrection(None))
        lib = fuel_library()
        routes = rs.routes
        R = self.R = len(routes)
        self.E = sc.max_extra_ships + 1

        # ---------------- index spaces
        self.class_ids = sorted({c for r in routes for c in r.classes if c in rs.classes and rs.classes[c].available > 0})
        cidx = {c: i for i, c in enumerate(self.class_ids)}
        self.fuel_ids = sorted({f for fl in rs.route_fuels for f in fl})
        fidx = {f: i for i, f in enumerate(self.fuel_ids)}
        self.fam_ids = list(lib.families)
        famidx = {m: i for i, m in enumerate(self.fam_ids)}

        self.route_classes = [[cidx[c] for c in r.classes if c in cidx] for r in routes]
        if any(len(x) == 0 for x in self.route_classes):
            bad = [r.id for r, x in zip(routes, self.route_classes) if not x]
            raise ValueError(f"routes without an available vessel class: {bad}")
        self.route_fuels = [[fidx[f] for f in fl] for fl in rs.route_fuels]
        self.route_ops = [[0, 1] if s > 0 else [0] for s in rs.route_ops_share]
        sizes = []
        for r in range(R):
            sizes += [len(self.route_classes[r]), len(self.route_fuels[r]), len(self.route_ops[r]), self.E]
        self.cat_sizes = np.array(sizes, dtype=int)

        def lut(opts):
            width = max(len(o) for o in opts)
            out = np.zeros((R, width), dtype=int)
            for r, o in enumerate(opts):
                out[r, : len(o)] = o
                out[r, len(o):] = o[0]
            return out

        self.class_lut, self.fuel_lut, self.ops_lut = lut(self.route_classes), lut(self.route_fuels), lut(self.route_ops)

        # ---------------- route constants
        self.L = np.array([r.distance_nm for r in routes])
        self.port_h = np.array([r.port_hours for r in routes], float)
        self.liner = np.array([r.service == "liner" for r in routes])
        self.demand = np.array([r.annual_demand for r in routes], float)
        self.lf = np.array([r.load_factor for r in routes], float)
        self.bn = np.array([r.beaufort for r in routes], float)
        self.delay_mean = np.array([r.delay_mean for r in routes], float)
        self.delay_sd = np.array([r.delay_sd for r in routes], float)
        self.port_sd = np.array([r.port_delay_sd_h for r in routes], float)
        self.eu_scope = np.array([r.eu_scope for r in routes], float)
        self.ops_share = np.array(rs.route_ops_share, float)
        self.grid = np.array(rs.grid_t_per_kwh, float)
        self.elec_price = np.array(rs.elec_usd_per_kwh, float)

        # ---------------- class constants
        classes = [rs.classes[c] for c in self.class_ids]
        C = len(classes)
        cii_cfg = regulations()["cii"]
        self.cap = np.array([vc.capacity for vc in classes], float)
        self.charter = np.array([vc.charter_usd_per_day for vc in classes], float)
        self.v_min = np.array([vc.min_speed_kn for vc in classes], float)
        self.aux_berth = np.array([vc.aux_berth_kw for vc in classes], float)
        self.available = np.array([vc.available for vc in classes], float)
        self.cii_cap = np.array([cii.capacity_for(vc, cii_cfg) for vc in classes], float)
        self.cii_req = np.array([cii.required_cii(vc, rs.year, cii_cfg) for vc in classes], float)
        self.cii_limit = np.array([cii.rating_ratio_limit(vc.cii_type, sc.cii_min_rating, cii_cfg) for vc in classes])

        # ---------------- fuel & family constants (per MJ delivered, pilot fuel included)
        fams = [lib.families[m] for m in self.fam_ids]
        self.fam_bsec = np.array([m.bsec_mj_per_kwh for m in fams])
        self.fam_fc = np.array([m.load_curve == "fuel_cell" for m in fams])
        self.fam_premium = np.array([m.charter_premium for m in fams])
        self.fam_caploss = np.array([m.capacity_loss for m in fams])
        pilot = lib.fuels[lib.pilot_fuel]
        fe_cfg = regulations()["fueleu"]
        rwd_on = rs.year <= fe_cfg["rfnbo_reward_until"]

        def per_mj(fuel, share):
            mass = share / fuel.lcv_mj_per_g                   # g fuel per MJ delivered
            burnt = mass * (1 - fuel.slip)
            return (burnt * fuel.cf_co2, burnt * fuel.cf_ch4 + mass * fuel.slip, burnt * fuel.cf_n2o, mass)

        F = len(self.fuel_ids)
        self.fuel_fam = np.zeros(F, dtype=int)
        self.co2_mj, self.ch4_mj, self.n2o_mj = np.zeros(F), np.zeros(F), np.zeros(F)
        self.wtw_mj, self.cost_mj, self.fe_num, self.fe_den = np.zeros(F), np.zeros(F), np.zeros(F), np.zeros(F)
        self.mass_mj, self.pilot_mass_mj = np.zeros(F), np.zeros(F)
        for i, fid in enumerate(self.fuel_ids):
            fu = lib.fuels[fid]
            p = fu.pilot_share
            self.fuel_fam[i] = famidx[fu.family]
            a, b = per_mj(fu, 1 - p), per_mj(pilot, p)
            self.co2_mj[i], self.ch4_mj[i], self.n2o_mj[i] = (a[0] + b[0]) * 1e-6, (a[1] + b[1]) * 1e-6, (a[2] + b[2]) * 1e-6
            self.mass_mj[i], self.pilot_mass_mj[i] = a[3] * 1e-6, b[3] * 1e-6
            wf, wp = wtw_g_per_mj(fu, lib), wtw_g_per_mj(pilot, lib)
            self.wtw_mj[i] = ((1 - p) * wf + p * wp) * 1e-6
            self.cost_mj[i] = a[3] * 1e-6 * rs.fuel_price[fid] + b[3] * 1e-6 * rs.fuel_price[pilot.id]
            self.fe_num[i] = (1 - p) * wf + p * wp
            self.fe_den[i] = (1 - p) * (fe_cfg["rfnbo_reward_factor"] if (fu.rfnbo and rwd_on) else 1.0) + p
        self.gwp_ch4, self.gwp_n2o = lib.gwp_ch4, lib.gwp_n2o
        self.ets_share = ets.surrender_share(rs.year)
        self.ets_non_co2 = rs.year >= regulations()["eu_ets"]["non_co2_from"]
        self.fe_target = fueleu.target_intensity(rs.year)
        self.fe_rate = fe_cfg["penalty_eur_per_t_vlsfo_eq"] / fe_cfg["vlsfo_mj_per_t"]

        # ---------------- speed tables per (route, class): energy per round trip on a speed grid
        self.v_max = np.zeros((R, C))
        self.grid_v = np.zeros((R, C, N_GRID))
        self.main_ice = np.zeros((R, C, N_GRID))    # kWh x SFOC multiplier per round trip (ICE)
        self.main_fc = np.zeros((R, C, N_GRID))     # same for fuel-cell load curve
        self.aux_sea = np.zeros((R, C, N_GRID))     # auxiliary kWh at sea per round trip
        for r, route in enumerate(routes):
            for c in self.route_classes[r]:
                vc = classes[c]
                vmax = max(min(max_service_speed(vc, route.beaufort, True), vc.max_speed_kn), vc.min_speed_kn + 0.5)
                self.v_max[r, c] = vmax
                v = np.linspace(vc.min_speed_kn, vmax, N_GRID)
                self.grid_v[r, c] = v
                t_leg = route.distance_nm / v
                states = loading_states(vc.cargo)
                for state, laden in (("laden", True), ("return", False)):
                    dr = state_draft_ratio(vc, states[state])
                    wf = np.array([weather_power_factor(vc, s, route.beaufort, laden) for s in v])
                    p = np.minimum(propulsion_power_kw(vc, v, dr * vc.design_draft_m, wf), 1.05 * vc.mcr_kw)
                    corr = np.array([self.correction.ratio(vc.id, s, laden, route.beaufort) for s in v])
                    self.main_ice[r, c] += p * t_leg * sfoc_multiplier(p / vc.mcr_kw, "ice") * corr
                    self.main_fc[r, c] += p * t_leg * sfoc_multiplier(p / vc.mcr_kw, "fuel_cell") * corr
                    self.aux_sea[r, c] += vc.aux_sea_kw * t_leg * corr
        for c in range(C):  # unused (route, class) pairs: harmless finite values
            mask = self.v_max[:, c] == 0
            self.v_max[mask, c] = self.v_min[c] + 1.0
            self.grid_v[mask, c] = np.linspace(self.v_min[c], self.v_min[c] + 1.0, N_GRID)

        self.cv_labels = ["schedule", "fleet_availability", "cii", "fueleu", "emission_cap"]

    # ------------------------------------------------------------------ encodings
    @property
    def n_cat(self) -> int:
        return len(self.cat_sizes)

    @property
    def n_keys(self) -> int:
        """Length of the random-key vector used by continuous (classical / pymoo) algorithms."""
        return self.n_cat + self.R

    def decode_keys(self, X: np.ndarray) -> Genes:
        X = np.clip(np.atleast_2d(X), 0.0, 1.0 - 1e-12)
        cat = np.floor(X[:, : self.n_cat] * self.cat_sizes[None, :]).astype(int)
        return Genes(cat=cat, u=X[:, self.n_cat:].copy())

    def encode_keys(self, g: Genes) -> np.ndarray:
        return np.hstack([(g.cat + 0.5) / self.cat_sizes[None, :], g.u])

    def random_genes(self, n: int, rng: np.random.Generator) -> Genes:
        return self.decode_keys(rng.random((n, self.n_keys)))

    # ------------------------------------------------------------------ evaluation
    def _route_block(self, g: Genes) -> dict[str, np.ndarray]:
        P, R = g.u.shape
        ar = np.arange(R)[None, :]
        cls = self.class_lut[ar, g.cat[:, 0::4]]
        fu = self.fuel_lut[ar, g.cat[:, 1::4]]
        ops = self.ops_lut[ar, g.cat[:, 2::4]]
        extra = g.cat[:, 3::4]
        fam = self.fuel_fam[fu]
        L, port = self.L[None, :], self.port_h[None, :]

        cap_eff = self.cap[cls] * (1 - self.fam_caploss[fam])
        n_rt = np.maximum(self.demand[None, :] / (cap_eff * self.lf[None, :]), np.where(self.liner, 52.0, 0.0)[None, :])
        vmax = self.v_max[ar, cls]
        vmin = self.v_min[cls]
        s_max = 2 * L / vmax
        n_min = np.maximum(np.ceil(n_rt * (s_max + port) / HOURS_AVAILABLE - 1e-9), 1)
        n = n_min + extra
        rtt = n * HOURS_AVAILABLE / n_rt
        v_req = 2 * L / np.maximum(rtt - port, 1e-6)
        v_lo = np.minimum(np.maximum(vmin, v_req), vmax)
        u = g.u
        if self.rs.scenario.speed_levels:
            lv = self.rs.scenario.speed_levels - 1
            u = np.round(u * lv) / lv
        v = v_lo + u * (vmax - v_lo)

        pos = (v - vmin) / np.maximum(vmax - vmin, 1e-9) * (N_GRID - 1)
        i0 = np.clip(np.floor(pos).astype(int), 0, N_GRID - 2)
        w = np.clip(pos - i0, 0.0, 1.0)

        def lerp(tab):
            return (1 - w) * tab[ar, cls, i0] + w * tab[ar, cls, i0 + 1]

        is_fc = self.fam_fc[fam]
        main = np.where(is_fc, lerp(self.main_fc), lerp(self.main_ice))
        aux_bsec = np.where(is_fc, self.fam_bsec[fam], AUX_BSEC)
        e_sea = main * self.fam_bsec[fam] + lerp(self.aux_sea) * aux_bsec
        sea_h = 2 * L / v
        buffer = np.maximum(rtt - port - sea_h, 0.0)
        berth_kw = self.aux_berth[cls]
        ops_frac = ops * self.ops_share[None, :]
        e_port = berth_kw * port * (1 - ops_frac) * aux_bsec
        elec_rt = berth_kw * port * ops_frac
        e_idle = berth_kw * buffer * aux_bsec
        energy = n_rt * (e_sea + e_port + e_idle)             # MJ / yr
        elec = n_rt * elec_rt                                 # kWh / yr

        co2, ch4, n2o = energy * self.co2_mj[fu], energy * self.ch4_mj[fu], energy * self.n2o_mj[fu]
        wtw = energy * self.wtw_mj[fu] + elec * self.grid[None, :]
        ets_t = (co2 + (ch4 * self.gwp_ch4 + n2o * self.gwp_n2o if self.ets_non_co2 else 0.0)) * self.eu_scope[None, :] * self.ets_share
        charter = n * self.charter[cls] * 365.0 * (1 + self.fam_premium[fam])
        fuel_cost = energy * self.cost_mj[fu]
        elec_cost = elec * self.elec_price[None, :]
        ets_cost = ets_t * self.rs.ets_price_usd
        levy_cost = wtw * self.rs.global_levy_usd

        attained = co2 * 1e6 / (self.cii_cap[cls] * n_rt * 2 * L)
        cii_ratio = attained / self.cii_req[cls]
        absorb = buffer + RECOVERY_SHARE * (sea_h - s_max)
        sd = np.sqrt((self.delay_sd[None, :] * sea_h) ** 2 + self.port_sd[None, :] ** 2)
        p_on = norm.cdf((absorb - self.delay_mean[None, :] * sea_h) / sd)
        return {
            "cls": cls, "fuel": fu, "fam": fam, "ops": ops, "n": n, "n_min": n_min, "v": v, "v_lo": v_lo, "vmax": vmax,
            "n_rt": n_rt, "energy": energy, "elec": elec, "co2": co2, "ch4": ch4, "n2o": n2o, "wtw": wtw,
            "charter": charter, "fuel_cost": fuel_cost, "elec_cost": elec_cost, "ets_cost": ets_cost,
            "levy_cost": levy_cost, "cii_ratio": cii_ratio, "cii_attained": attained, "p_on": p_on,
            "buffer_h": buffer, "sea_h": sea_h, "rtt": rtt,
        }

    def _fleet(self, b: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        P = b["n"].shape[0]
        scope = self.eu_scope[None, :]
        e_in = b["energy"] * scope
        ops_in = b["elec"] * 3.6 * scope
        num = (e_in * self.fe_num[b["fuel"]]).sum(axis=1)
        den = (e_in * self.fe_den[b["fuel"]]).sum(axis=1) + ops_in.sum(axis=1)
        e_tot = e_in.sum(axis=1) + ops_in.sum(axis=1)
        intensity = np.where(den > 0, num / np.maximum(den, 1e-9), 0.0)
        cb = (self.fe_target - intensity) * e_tot
        penalty_eur = np.where(cb < 0, -cb / np.maximum(intensity, 1e-9) * self.fe_rate, 0.0)
        used = np.zeros((P, len(self.class_ids)))
        np.add.at(used, (np.repeat(np.arange(P), self.R), b["cls"].ravel()), b["n"].ravel())
        return {"fe_intensity": intensity, "fe_cb_g": cb, "fe_energy": e_tot, "fe_penalty_usd": penalty_eur * self.rs.eur_to_usd,
                "used": used}

    def evaluate(self, g: Genes, return_parts: bool = False):
        b = self._route_block(g)
        fl = self._fleet(b)
        sc = self.rs.scenario
        fuel_t = b["energy"].sum(axis=1) / HFO_MJ_PER_T
        emissions = b["wtw"].sum(axis=1)
        cost = (b["charter"] + b["fuel_cost"] + b["elec_cost"] + b["ets_cost"] + b["levy_cost"]).sum(axis=1)
        if sc.fueleu_mode == "penalty":
            cost = cost + fl["fe_penalty_usd"]
        weights = self.demand / self.demand.sum()
        risk = ((1 - b["p_on"]) * weights[None, :]).sum(axis=1) * 100
        objs = {"fuel": fuel_t, "emissions": emissions, "cost": cost / 1e6, "schedule_risk": risk}
        F = np.column_stack([objs[o] for o in self.objectives])

        v_sched = np.maximum(sc.on_time_min - b["p_on"], 0).sum(axis=1) * 5.0
        v_avail = (np.maximum(fl["used"] - self.available[None, :], 0) / self.available[None, :]).sum(axis=1)
        limit = self.cii_limit[b["cls"]]
        v_cii = np.maximum(b["cii_ratio"] / limit - 1, 0).sum(axis=1)
        v_fe = (np.maximum(-fl["fe_cb_g"], 0) / np.maximum(fl["fe_energy"] * self.fe_target, 1e-9)
                if sc.fueleu_mode == "hard" else np.zeros(len(g)))
        cap = sc.fleet_emission_cap_t
        v_cap = np.maximum(emissions - cap, 0) / cap if cap else np.zeros(len(g))
        parts = np.column_stack([v_sched, v_avail, v_cii, v_fe, v_cap])
        CV = parts.sum(axis=1)
        if return_parts:
            route_cv = np.maximum(sc.on_time_min - b["p_on"], 0) * 5.0 + np.maximum(b["cii_ratio"] / limit - 1, 0)
            return F, CV, {"route": b, "fleet": fl, "cv_parts": parts, "objectives_all": objs, "route_cv": route_cv}
        return F, CV

    # ------------------------------------------------------------------ reporting
    def describe(self, g: Genes, i: int = 0) -> dict:
        """Human-readable deployment plan and KPIs for one solution."""
        single = g.take([i])
        F, CV, parts = self.evaluate(single, return_parts=True)
        b = {k: v[0] for k, v in parts["route"].items()}
        fl = {k: v[0] for k, v in parts["fleet"].items()}
        lib = fuel_library()
        routes = []
        fuel_mix: dict[str, float] = {}
        for r, route in enumerate(self.rs.routes):
            cid = self.class_ids[b["cls"][r]]
            vc = self.rs.classes[cid]
            fid = self.fuel_ids[b["fuel"][r]]
            e = float(b["energy"][r])
            main_t = e * self.mass_mj[b["fuel"][r]]
            pilot_t = e * self.pilot_mass_mj[b["fuel"][r]]
            fuel_mix[fid] = fuel_mix.get(fid, 0.0) + e * (1 - lib.fuels[fid].pilot_share)
            fuel_mix[lib.pilot_fuel] = fuel_mix.get(lib.pilot_fuel, 0.0) + e * lib.fuels[fid].pilot_share
            ratio = float(b["cii_ratio"][r])
            routes.append({
                "route_id": route.id, "name": route.name, "ports": route.ports, "service": route.service,
                "distance_nm": route.distance_nm, "geometry": route.geometry,
                "vessel_class": cid, "vessel_label": vc.label, "vessel_type": vc.cargo,
                "capacity": vc.capacity, "capacity_unit": vc.capacity_unit,
                "ships": int(b["n"][r]), "min_ships": int(b["n_min"][r]),
                "speed_kn": float(b["v"][r]), "speed_range_kn": [float(b["v_lo"][r]), float(b["vmax"][r])],
                "design_speed_kn": vc.design_speed_kn,
                "fuel": fid, "fuel_label": lib.fuels[fid].label, "fuel_family": lib.fuels[fid].family,
                "shore_power": bool(b["ops"][r]),
                "round_trips_per_year": float(b["n_rt"][r]),
                "energy_gj": e / 1000.0, "fuel_t": {fid: main_t, **({lib.pilot_fuel: pilot_t} if pilot_t > 0 else {})},
                "fuel_hfo_eq_t": e / HFO_MJ_PER_T, "shore_power_mwh": float(b["elec"][r]) / 1000.0,
                "co2_ttw_t": float(b["co2"][r]), "wtw_co2e_t": float(b["wtw"][r]),
                "cost_usd": {"charter": float(b["charter"][r]), "fuel": float(b["fuel_cost"][r]),
                             "electricity": float(b["elec_cost"][r]), "eu_ets": float(b["ets_cost"][r]),
                             "levy": float(b["levy_cost"][r])},
                "cii": {"attained": float(b["cii_attained"][r]), "required": float(self.cii_req[b["cls"][r]]),
                        "ratio": ratio, "rating": cii.rating(ratio, 1.0, vc.cii_type)},
                "on_time_probability": float(b["p_on"][r]), "buffer_hours_per_round_trip": float(b["buffer_h"][r]),
            })
        total_e = sum(fuel_mix.values()) or 1.0
        used = {self.class_ids[c]: {"used": int(fl["used"][c]), "available": int(self.available[c])}
                for c in range(len(self.class_ids)) if fl["used"][c] > 0}
        objs = {k: float(v[0]) for k, v in parts["objectives_all"].items()}
        return {
            "objectives": objs,
            "objective_labels": {k: OBJECTIVE_LABELS[k] for k in objs},
            "feasible": bool(CV[0] <= 1e-9),
            "violations": {lab: float(x) for lab, x in zip(self.cv_labels, parts["cv_parts"][0])},
            "routes": routes,
            "fleet": {
                "ships": int(sum(r["ships"] for r in routes)),
                "class_usage": used,
                "fuel_mix_energy_share": {k: v / total_e for k, v in sorted(fuel_mix.items(), key=lambda kv: -kv[1])},
                "fueleu": {"intensity_g_per_mj": float(fl["fe_intensity"]), "target_g_per_mj": self.fe_target,
                           "balance_t_co2e": float(fl["fe_cb_g"]) / 1e6, "penalty_usd": float(fl["fe_penalty_usd"]),
                           "in_scope_energy_gj": float(fl["fe_energy"]) / 1000.0},
                "shore_power_routes": int(sum(r["shore_power"] for r in routes)),
            },
        }

    # ------------------------------------------------------------------ reference plans
    def baseline_genes(self, kind: str = "current_practice") -> Genes:
        """Reference plans that respect schedule and fleet availability but ignore emissions.

        'current_practice': VLSFO, no shore power, largest available class, fastest speed that
        still meets the on-time requirement (fewest ships first).
        'slow_steaming': the same, but the slowest feasible speed with one extra ship.
        """
        cat = np.zeros((1, self.n_cat), dtype=int)
        u = np.zeros((1, self.R))
        used = np.zeros(len(self.class_ids))
        order = np.argsort(-self.demand)      # big services pick their ships first
        for r in order:
            fuels = [self.fuel_ids[f] for f in self.route_fuels[r]]
            fuel_opt = fuels.index("VLSFO") if "VLSFO" in fuels else 0
            by_cap = sorted(range(len(self.route_classes[r])), key=lambda j: -self.cap[self.route_classes[r][j]])
            chosen = None
            for j in by_cap:
                cands = []
                for e in range(self.E):
                    for uu in np.linspace(1.0, 0.0, 11):
                        c2 = cat.copy()
                        c2[0, 4 * r: 4 * r + 4] = [j, fuel_opt, 0, e]
                        u2 = u.copy()
                        u2[0, r] = uu
                        blk = self._route_block(Genes(c2, u2))
                        cands.append((blk["p_on"][0, r] >= self.rs.scenario.on_time_min, e, uu, blk["n"][0, r]))
                ok = [c for c in cands if c[0]] or cands
                if kind == "slow_steaming":
                    pick = min(ok, key=lambda c: (c[1] != min(1, self.E - 1), c[2]))
                else:
                    pick = min(ok, key=lambda c: (c[3], -c[2]))
                cls = self.route_classes[r][j]
                if used[cls] + pick[3] <= self.available[cls] or j == by_cap[-1]:
                    chosen = (j, pick)
                    used[cls] += pick[3]
                    break
            j, pick = chosen
            cat[0, 4 * r: 4 * r + 4] = [j, fuel_opt, 0, pick[1]]
            u[0, r] = pick[2]
        return Genes(cat, u)
