"""Gate-model QAOA for a small fleet sub-problem: state-vector simulation and OpenQASM 2.0 export.

The rest of Q-GreenFleet is quantum-*inspired* and runs on classical hardware. This module writes a piece of the
fleet problem as a quantum circuit that a gate-based quantum computer could run, and simulates it exactly.

Sub-problem
    m services ("routes") each pick one of k candidate options (vessel class x fuel x shore power x ships x speed);
    all other services keep the reference plan. Qubit q = r*k + j is 1 when service r uses option j (one-hot).
    Cost Hamiltonian (diagonal):  H_C = sum_q h_q x_q + sum_{q<q'} P_qq' x_q x_q'
      h   each option's weighted, normalised objective (fuel / WtW GHG / cost incl. linearised FuelEU)
      P   fleet availability: two options on different services that together need more ships of a class than
          remain after the fixed services get a penalty, so the services compete for scarce ships

Ansatz: Quantum Alternating Operator Ansatz (Hadfield et al., Algorithms 12:34, 2019)
    |psi_0> = W_k (x) ... (x) W_k                 each service in an equal superposition of its one-hot states
    U_C(g)  = exp(-i g H_C)
    U_M(b)  = prod_r prod_(a,b in ring r) exp(-i b (X_a X_b + Y_a Y_b) / 2)
    The XY mixer only swaps excitations inside a service, so every measurement is a valid plan. The textbook
    alternative (|+>^n, X mixer, one-hot penalty) is simulated for comparison.

Training: angles minimise <H_C> (grid + Nelder-Mead at p = 1, then layer by layer from interpolated angles,
Zhou et al., PRX 10:021067, 2020). The ground truth is brute force over all k^m plans with the full fleet model.

Export: OpenQASM 2.0 using only x, h, rx, ry, rz, cx (qelib1.inc), so it loads in Qiskit, IBM Quantum,
Amazon Braket or any QASM 2 toolchain. `simulate_qasm` re-simulates the exported text to check it.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from greenfleet.config import fuel_library
from greenfleet.optimization.options import RouteOptions, enumerate_options, options_to_genes
from greenfleet.optimization.problem import FleetProblem, Genes

MAX_QUBITS = 16


# ------------------------------------------------------------------ fleet sub-problem
@dataclass
class FleetSubproblem:
    routes: list[int]                     # services optimised on the quantum circuit
    k: int                                # options per service
    options: list[RouteOptions]           # k options per selected service
    base: list[int]                       # reference choice (index into all_options[r]) for every service
    all_options: list[RouteOptions]
    h: np.ndarray                         # (n,) linear coefficients (normalised)
    P: np.ndarray                         # (n, n) upper-triangular pair penalties
    labels: list[str]                     # readable option labels, one per qubit
    weights: dict[str, float]
    remaining: dict[int, int] = field(default_factory=dict)   # class -> ships left for the selected services

    @property
    def n(self) -> int:
        return len(self.h)

    def choice_from_bits(self, bits: np.ndarray) -> list[int] | None:
        """Local option per selected service, or None if a service is not exactly one-hot."""
        out = []
        for r in range(len(self.routes)):
            on = np.flatnonzero(bits[r * self.k:(r + 1) * self.k])
            if len(on) != 1:
                return None
            out.append(int(on[0]))
        return out

    def full_choice(self, local: list[int]) -> list[int]:
        choice = list(self.base)
        for r, j in zip(self.routes, local):
            choice[r] = int(self.opt_index[r][j])
        return choice

    opt_index: dict[int, np.ndarray] = field(default_factory=dict)


def _weighted(o: RouteOptions, w: dict[str, float], scale: dict[str, float], fe_rate: float) -> np.ndarray:
    return (w.get("fuel", 0) * o.fuel_t / scale["fuel"] + w.get("emissions", 0) * o.wtw / scale["emissions"]
            + w.get("cost", 0) * (o.cost + fe_rate * o.fe_excess) / scale["cost"])


def build_subproblem(problem: FleetProblem, weights: dict[str, float], n_routes: int = 4, k: int = 3,
                     penalty: float = 1.5) -> FleetSubproblem:
    """Pick the services that compete hardest for scarce ships and give each its k best options."""
    from greenfleet.optimization.milp import FleetMILP
    from greenfleet.optimization.options import objective_scales
    from greenfleet.optimization.qubo import fueleu_rate

    if n_routes * k > MAX_QUBITS:
        raise ValueError(f"at most {MAX_QUBITS} qubits (n_routes x options)")
    opts = enumerate_options(problem, 5)
    scale = objective_scales(opts)
    rate = fueleu_rate(problem)
    scores = [_weighted(o, weights, scale, rate) for o in opts]
    ref = FleetMILP(problem, opts).weighted(weights)          # exact reference plan for the other services
    base = [int(j) for j in ref.choice] if getattr(ref, "choice", None) is not None else [int(np.argmin(s)) for s in scores]

    # candidate options per service: best score per vessel class first (so services can trade classes), then best overall
    cand = {}
    for r, (o, s) in enumerate(zip(opts, scores)):
        picked: list[int] = []
        for c in np.unique(o.cls)[np.argsort([s[o.cls == c].min() for c in np.unique(o.cls)])]:
            picked.append(int(np.flatnonzero(o.cls == c)[np.argmin(s[o.cls == c])]))
        for j in np.argsort(s):
            if len(picked) >= k:
                break
            if int(j) not in picked:
                picked.append(int(j))
        if base[r] not in picked[:k]:
            picked = [base[r]] + [j for j in picked if j != base[r]]
        cand[r] = np.array(picked[:k])

    def used_by(routes_fixed):
        used = np.zeros(len(problem.class_ids), dtype=int)
        for r in routes_fixed:
            used[opts[r].cls[base[r]]] += opts[r].ships[base[r]]
        return used

    def conflicts(sel):
        left = problem.available.astype(int) - used_by([r for r in range(problem.R) if r not in sel])
        count = 0
        for a, b in itertools.combinations(sel, 2):
            for i in cand[a]:
                for j in cand[b]:
                    c = opts[a].cls[i]
                    if c == opts[b].cls[j] and opts[a].ships[i] + opts[b].ships[j] > left[c]:
                        count += 1
        return count, left

    # greedy: start from the pair with most conflicts, add the service that adds most conflicts
    R = [r for r in range(problem.R) if len(opts[r]) >= k]
    if len(R) < n_routes:
        raise ValueError("not enough services with enough options")
    best = max(itertools.combinations(R, 2), key=lambda p: (conflicts(list(p))[0], -p[0]))
    sel = list(best)
    while len(sel) < n_routes:
        nxt = max((r for r in R if r not in sel), key=lambda r: (conflicts(sel + [r])[0], -r))
        sel.append(nxt)
    sel.sort()
    _, left = conflicts(sel)

    loc = [opts[r].take(cand[r]) for r in sel]
    h = np.concatenate([scores[r][cand[r]] for r in sel])
    # normalise: each service's best option at 0, the largest spread at 1
    for i in range(len(sel)):
        h[i * k:(i + 1) * k] -= h[i * k:(i + 1) * k].min()
    h = h / max(h.max(), 1e-12)
    n = len(h)
    P = np.zeros((n, n))
    for a, b in itertools.combinations(range(len(sel)), 2):
        for i in range(k):
            for j in range(k):
                c = loc[a].cls[i]
                if c == loc[b].cls[j] and loc[a].ships[i] + loc[b].ships[j] > left[c]:
                    P[a * k + i, b * k + j] = penalty
    lib = fuel_library()
    lib_labels = []
    for r, o in zip(sel, loc):
        for j in range(k):
            cat = np.zeros((1, problem.n_cat), dtype=int)
            cat[0, 4 * r:4 * r + 4] = o.cat[j]
            u = np.zeros((1, problem.R))
            u[0, r] = o.u[j]
            speed = float(problem._route_block(Genes(cat, u))["v"][0, r])
            vc = problem.rs.classes[problem.class_ids[o.cls[j]]]
            fuel = lib.fuels[problem.fuel_ids[problem.fuel_lut[r, o.cat[j][1]]]].label
            ops = " · shore power" if problem.ops_lut[r, o.cat[j][2]] else ""
            lib_labels.append(f"{problem.rs.routes[r].id} · {o.ships[j]} × {vc.label.split(' (')[0]} · {fuel} · "
                              f"{speed:.1f} kn{ops}")
    return FleetSubproblem(routes=sel, k=k, options=loc, base=base, all_options=opts, h=h, P=P, labels=lib_labels,
                           weights=weights, remaining={int(c): int(left[c]) for c in np.unique([o.cls for o in loc])},
                           opt_index={r: cand[r] for r in sel})


# ------------------------------------------------------------------ state-vector simulator
def _basis_bits(n: int) -> np.ndarray:
    return ((np.arange(2 ** n)[:, None] >> np.arange(n)) & 1).astype(np.int8)     # qubit q = bit q (little endian)


def cost_vector(h: np.ndarray, P: np.ndarray, bits: np.ndarray) -> np.ndarray:
    x = bits.astype(float)
    return x @ h + np.einsum("si,ij,sj->s", x, P, x)


def onehot_penalty(bits: np.ndarray, k: int) -> np.ndarray:
    m = bits.shape[1] // k
    return ((bits.reshape(len(bits), m, k).sum(axis=2) - 1) ** 2).sum(axis=1).astype(float)


class QAOASimulator:
    """Exact QAOA state vectors for a diagonal cost and an X or ring-XY mixer."""

    def __init__(self, n: int, cost: np.ndarray, mixer: str, k: int):
        self.n, self.cost, self.mixer, self.k = n, cost, mixer, k
        self.m = n // k
        self.pairs = [(r * k + a, r * k + (a + 1) % k) for r in range(self.m) for a in range(k if k > 2 else 1)]
        idx = np.arange(2 ** n)
        self.swap_idx = []
        for a, b in self.pairs:
            i = idx[((idx >> a) & 1 == 1) & ((idx >> b) & 1 == 0)]
            self.swap_idx.append((i, i ^ (1 << a) ^ (1 << b)))

    def initial(self) -> np.ndarray:
        if self.mixer == "x":
            return np.full(2 ** self.n, 2 ** (-self.n / 2), dtype=complex)
        psi = np.zeros(2 ** self.n, dtype=complex)
        for combo in itertools.product(range(self.k), repeat=self.m):
            psi[sum(1 << (r * self.k + j) for r, j in enumerate(combo))] = 1.0
        return psi / np.sqrt(self.k ** self.m)

    def _mix(self, psi: np.ndarray, beta: float) -> np.ndarray:
        c, s = np.cos(beta), np.sin(beta)
        if self.mixer == "x":
            for q in range(self.n):
                v = psi.reshape(2 ** (self.n - q - 1), 2, 2 ** q)
                a0, a1 = v[:, 0, :].copy(), v[:, 1, :].copy()
                v[:, 0, :], v[:, 1, :] = c * a0 - 1j * s * a1, -1j * s * a0 + c * a1
            return psi
        for i, j in self.swap_idx:
            a, b = psi[i].copy(), psi[j].copy()
            psi[i], psi[j] = c * a - 1j * s * b, -1j * s * a + c * b
        return psi

    def state(self, gammas, betas) -> np.ndarray:
        psi = self.initial()
        for g, b in zip(gammas, betas):
            psi = psi * np.exp(-1j * g * self.cost)
            psi = self._mix(psi, b)
        return psi

    def expectation(self, params: np.ndarray) -> float:
        p = len(params) // 2
        psi = self.state(params[:p], params[p:])
        return float(np.real(np.vdot(psi, self.cost * psi)))

    def train(self, p_max: int, seed: int = 0) -> list[dict]:
        """Angles for p = 1..p_max (grid + Nelder-Mead, then INTERP initialisation layer by layer)."""
        rng = np.random.default_rng(seed)
        gmax = 2 * np.pi / max(float(np.ptp(self.cost)), 1e-9) * 2
        grid = [(g, b) for g in np.linspace(0.02, gmax, 14) for b in np.linspace(0.02, np.pi - 0.02, 14)]
        g0, b0 = min(grid, key=lambda gb: self.expectation(np.array(gb)))
        out, x = [], np.array([g0, b0])
        for p in range(1, p_max + 1):
            if p > 1:
                prev_g, prev_b = out[-1]["gammas"], out[-1]["betas"]

                def interp(v, p):
                    v = np.asarray(v)
                    return np.interp(np.linspace(0, 1, p), np.linspace(0, 1, len(v)), v)
                x = np.concatenate([interp(prev_g, p), interp(prev_b, p)])
            starts = [x, x + rng.normal(0, 0.15, len(x))]
            best = min((minimize(self.expectation, s0, method="Nelder-Mead",
                                 options={"maxiter": 400 * p, "xatol": 1e-4, "fatol": 1e-8}) for s0 in starts),
                       key=lambda r: r.fun)
            out.append({"p": p, "gammas": best.x[:p].tolist(), "betas": best.x[p:].tolist(), "energy": float(best.fun)})
        return out


# ------------------------------------------------------------------ experiment
def run_qaoa(problem: FleetProblem, weights: dict[str, float], n_routes: int = 4, k: int = 3, p_max: int = 3,
             onehot_weight: float = 1.5, seed: int = 0) -> dict:
    sub = build_subproblem(problem, weights, n_routes, k)
    n = sub.n
    bits = _basis_bits(n)
    c_qubo = cost_vector(sub.h, sub.P, bits)

    # ground truth: every valid plan through the full fleet model
    from greenfleet.optimization.options import objective_scales
    from greenfleet.optimization.qubo import weighted_value

    scales = objective_scales(sub.all_options)
    plans = []
    for combo in itertools.product(range(k), repeat=len(sub.routes)):
        g = options_to_genes(problem, sub.all_options, sub.full_choice(list(combo)))
        F, CV = problem.evaluate(g)
        idx = sum(1 << (r * k + j) for r, j in enumerate(combo))
        plans.append({"index": idx, "choice": list(combo), "qubo_energy": float(c_qubo[idx]),
                      "value": float(weighted_value(problem, g, weights, scales)), "feasible": bool(CV[0] <= 1e-9)})
    feas = [pl for pl in plans if pl["feasible"]] or plans
    true_opt = min(feas, key=lambda pl: pl["value"])
    top3 = [pl["index"] for pl in sorted(feas, key=lambda pl: pl["value"])[:3]]
    qubo_opt = min(plans, key=lambda pl: pl["qubo_energy"])
    valid = np.zeros(2 ** n, dtype=bool)
    valid[[pl["index"] for pl in plans]] = True
    e_best = min(pl["qubo_energy"] for pl in plans)
    e_worst = max(pl["qubo_energy"] for pl in plans)

    results = {}
    for mixer in ("xy", "x"):
        cost = c_qubo if mixer == "xy" else c_qubo + onehot_weight * onehot_penalty(bits, k)
        sim = QAOASimulator(n, cost, mixer, k)
        layers = sim.train(p_max, seed=seed)
        rows = []
        for L in layers:
            prob = np.abs(sim.state(L["gammas"], L["betas"])) ** 2
            e_valid = np.where(valid, c_qubo, e_worst)   # an invalid sample is worth the worst valid plan
            rows.append({**L, "p_optimal": float(prob[true_opt["index"]]), "p_top3": float(prob[top3].sum()),
                         "p_valid": float(prob[valid].sum()),
                         "approx_ratio": float((e_worst - prob @ e_valid) / max(e_worst - e_best, 1e-12)),
                         "most_likely": int(np.argmax(prob))})
        results[mixer] = {"layers": rows, "probabilities": prob}

    best_layer = results["xy"]["layers"][-1]
    prob = results["xy"]["probabilities"]
    top = np.argsort(-prob)[:8]

    def describe(idx):
        ch = sub.choice_from_bits(bits[idx])
        return {"bits": format(int(idx), f"0{n}b"), "probability": float(prob[idx]),
                "plan": [sub.labels[r * k + j] for r, j in enumerate(ch)] if ch is not None else None,
                "optimal": bool(idx == true_opt["index"])}

    return {
        "qubits": n, "services": [problem.rs.routes[r].id for r in sub.routes],
        "service_names": [problem.rs.routes[r].name for r in sub.routes], "options_per_service": k,
        "valid_plans": len(plans), "coupled_pairs": int((sub.P > 0).sum()), "labels": sub.labels,
        "weights": weights, "random_guess_p_optimal": 1 / len(plans), "random_guess_p_top3": len(top3) / len(plans),
        "optimum": describe(true_opt["index"]), "qubo_matches_full_model": bool(qubo_opt["index"] == true_opt["index"]),
        "layers": {m: [{kk: v for kk, v in r.items()} for r in results[m]["layers"]] for m in results},
        "top_plans": [describe(i) for i in top],
        "qasm": to_qasm(sub, best_layer["gammas"], best_layer["betas"]),
    }


# ------------------------------------------------------------------ OpenQASM 2.0 export
def _f(x: float) -> str:
    return f"{x:.10f}".rstrip("0").rstrip(".") if abs(x) > 1e-12 else "0"


def to_qasm(sub: FleetSubproblem, gammas, betas) -> str:
    """The trained XY-mixer circuit as OpenQASM 2.0 (qubit q = service q // k, option q % k)."""
    n, k = sub.n, sub.k
    m = n // k
    L = [
        "OPENQASM 2.0;", 'include "qelib1.inc";',
        f"// Q-GreenFleet QAOA (XY mixer), p = {len(gammas)}: {m} services x {k} options, one-hot per service",
        *[f"// q[{q}] = {lab}" for q, lab in enumerate(sub.labels)],
        f"qreg q[{n}];", f"creg c[{n}];",
    ]

    def ry(t, q):
        L.append(f"ry({_f(t)}) q[{q}];")

    def cx(a, b):
        L.append(f"cx q[{a}],q[{b}];")

    def rzz(t, a, b):
        cx(a, b)
        L.append(f"rz({_f(t)}) q[{b}];")
        cx(a, b)

    # W_k state per service: x q0, then cRY(theta_i) q_i -> q_{i+1} and cx q_{i+1} -> q_i
    for r in range(m):
        q = [r * k + j for j in range(k)]
        L.append(f"x q[{q[0]}];")
        for i in range(k - 1):
            t = 2 * np.arccos(np.sqrt(1 / (k - i)))
            ry(t / 2, q[i + 1])
            cx(q[i], q[i + 1])
            ry(-t / 2, q[i + 1])
            cx(q[i], q[i + 1])
            cx(q[i + 1], q[i])
    pairs = [(r * k + a, r * k + (a + 1) % k) for r in range(m) for a in range(k if k > 2 else 1)]
    for g, b in zip(gammas, betas):
        L.append("barrier q;")
        # exp(-i g H_C): x = (1 - Z)/2, so h x -> rz(-g h) and P x x' -> rz(-g P/2) on each + rzz(g P/2)
        lin = sub.h.copy()
        for i, j in zip(*np.nonzero(sub.P)):
            lin[i] += sub.P[i, j] / 2
            lin[j] += sub.P[i, j] / 2
        for q in range(n):
            if abs(lin[q]) > 1e-12:
                L.append(f"rz({_f(-g * lin[q])}) q[{q}];")
        for i, j in zip(*np.nonzero(sub.P)):
            rzz(g * sub.P[i, j] / 2, int(i), int(j))
        # exp(-i b (XX + YY)/2) = exp(-i b/2 XX) exp(-i b/2 YY)
        for a, c in pairs:
            L += [f"h q[{a}];", f"h q[{c}];"]
            rzz(b, a, c)
            L += [f"h q[{a}];", f"h q[{c}];"]
            L += [f"rx({_f(np.pi / 2)}) q[{a}];", f"rx({_f(np.pi / 2)}) q[{c}];"]
            rzz(b, a, c)
            L += [f"rx({_f(-np.pi / 2)}) q[{a}];", f"rx({_f(-np.pi / 2)}) q[{c}];"]
    L.append("barrier q;")
    L.append("measure q -> c;")
    return "\n".join(L) + "\n"


def simulate_qasm(text: str) -> np.ndarray:
    """State vector (before measurement) of a circuit using the gates `to_qasm` emits."""
    n = int(re.search(r"qreg q\[(\d+)\];", text).group(1))
    psi = np.zeros(2 ** n, dtype=complex)
    psi[0] = 1.0

    def one(U, q):
        v = psi.reshape(2 ** (n - q - 1), 2, 2 ** q)
        a0, a1 = v[:, 0, :].copy(), v[:, 1, :].copy()
        v[:, 0, :], v[:, 1, :] = U[0, 0] * a0 + U[0, 1] * a1, U[1, 0] * a0 + U[1, 1] * a1

    idx = np.arange(2 ** n)
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        mt = re.match(r"(\w+)(?:\(([^)]*)\))?\s+(.*);", line)
        if not mt or mt.group(1) in ("qreg", "creg", "include", "barrier", "measure", "OPENQASM"):
            continue
        gate, arg, qs = mt.group(1), mt.group(2), [int(x) for x in re.findall(r"q\[(\d+)\]", mt.group(3))]
        t = float(arg) if arg else 0.0
        c, s = np.cos(t / 2), np.sin(t / 2)
        if gate == "x":
            one(np.array([[0, 1], [1, 0]], complex), qs[0])
        elif gate == "h":
            one(np.array([[1, 1], [1, -1]], complex) / np.sqrt(2), qs[0])
        elif gate == "rx":
            one(np.array([[c, -1j * s], [-1j * s, c]]), qs[0])
        elif gate == "ry":
            one(np.array([[c, -s], [s, c]], complex), qs[0])
        elif gate == "rz":
            one(np.array([[np.exp(-1j * t / 2), 0], [0, np.exp(1j * t / 2)]]), qs[0])
        elif gate == "cx":
            a, b = qs
            i = idx[(idx >> a) & 1 == 1]
            j = i ^ (1 << b)
            keep = i < j
            i, j = i[keep], j[keep]
            psi[i], psi[j] = psi[j].copy(), psi[i].copy()
        else:
            raise ValueError(f"unsupported gate {gate}")
    return psi
