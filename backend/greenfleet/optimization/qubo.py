"""QUBO formulation of fleet deployment, solved by (simulated) quantum annealing.

Binary variables
    x_{r,j} = 1  if route r uses option j   (one-hot per route)
    s_{c,b}      slack bits encoding unused ships of class c (binary expansion)

Energy (minimised)
    E(x) = sum_{r,j} score_{r,j} x_{r,j}                           weighted, normalised objectives
         + A * sum_r (sum_j x_{r,j} - 1)^2                          exactly one option per route
         + B * sum_c (sum_{r,j} n_{r,j} x_{r,j} + sum_b 2^b s_{c,b} - N_c)^2   fleet availability

The FuelEU pool enters the score linearly (penalty price x per-option excess). The same
matrix is solved with a from-scratch path-integral SQA, OpenJij SQA and classical SA, and
exported as a dimod BQM that runs unchanged on a D-Wave quantum annealer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from greenfleet.optimization.options import RouteOptions, objective_scales, options_to_genes
from greenfleet.optimization.problem import FleetProblem, Genes
from greenfleet.quantum.sqa import PathIntegralSQA, qubo_energy, solve_openjij_sa, solve_openjij_sqa, to_bqm


@dataclass
class FleetQUBO:
    Q: np.ndarray
    offset: float
    var_route: np.ndarray        # route of each option variable (-1 for slack bits)
    var_option: np.ndarray       # option index within its route (-1 for slack)
    options: list[RouteOptions]
    scores: list[np.ndarray]
    labels: list[str]

    @property
    def n_vars(self) -> int:
        return self.Q.shape[0]


def fueleu_rate(problem: FleetProblem) -> float:
    """FuelEU penalty per gCO2e of pooled deficit (USD), linearised at the target intensity."""
    if problem.rs.scenario.fueleu_mode != "penalty":
        return 0.0
    return problem.fe_rate * problem.rs.eur_to_usd / max(problem.fe_target, 1e-9)


def _scores(problem: FleetProblem, options: list[RouteOptions], weights: dict[str, float],
            fe_price: float | None = None) -> list[np.ndarray]:
    sc = objective_scales(options)
    rate = fueleu_rate(problem) if fe_price is None else fe_price
    out = []
    for o in options:
        s = (weights.get("fuel", 0) * o.fuel_t / sc["fuel"]
             + weights.get("emissions", 0) * o.wtw / sc["emissions"]
             + weights.get("cost", 0) * (o.cost + rate * o.fe_excess) / sc["cost"]
             + weights.get("schedule_risk", 0) * o.risk / sc["schedule_risk"])
        out.append(s)
    return out


def reduce_options(options: list[RouteOptions], scores: list[np.ndarray], max_per_route: int) -> list[RouteOptions]:
    """Keep the best-scoring options per route (always including each class's best, for availability)."""
    out = []
    for o, s in zip(options, scores):
        if len(o) <= max_per_route:
            out.append(o)
            continue
        keep = set()
        for c in np.unique(o.cls):
            idx = np.nonzero(o.cls == c)[0]
            keep.update(idx[np.argsort(s[idx])[:2]].tolist())
        for j in np.argsort(s):
            if len(keep) >= max_per_route:
                break
            keep.add(int(j))
        out.append(o.take(np.array(sorted(keep))))
    return out


def build_qubo(problem: FleetProblem, options: list[RouteOptions], weights: dict[str, float],
               max_per_route: int = 10, penalty_scale: float = 1.5,
               availability_classes: set[int] | None = None, fe_price: float | None = None) -> FleetQUBO:
    scores = _scores(problem, options, weights, fe_price)
    options = reduce_options(options, scores, max_per_route)
    scores = _scores(problem, options, weights, fe_price)
    var_route, var_option, labels = [], [], []
    for r, o in enumerate(options):
        for j in range(len(o)):
            var_route.append(r)
            var_option.append(j)
            labels.append(f"x[{problem.rs.routes[r].id},{j}]")
    n_opt_vars = len(var_route)
    # slack bits per class for the availability inequality
    slack = []
    for c in range(len(problem.class_ids)):
        used = any((o.cls == c).any() for o in options)
        if not used or (availability_classes is not None and c not in availability_classes):
            continue
        cap = int(problem.available[c])
        nbits = max(1, int(np.ceil(np.log2(cap + 1))))
        for b in range(nbits):
            slack.append((c, 2**b))
            var_route.append(-1)
            var_option.append(-1)
            labels.append(f"s[{problem.class_ids[c]},{b}]")
    n = len(var_route)
    Q = np.zeros((n, n))
    offset = 0.0
    # penalties just above the largest per-route score range: large enough to make every
    # constraint violation unprofitable, small enough to keep the landscape well conditioned
    spread = max(float(s.max() - s.min()) for s in scores if len(s))
    A = penalty_scale * max(spread, 1e-6)
    B = A
    # objective, shifted so each route's best option scores 0 (constant moved to the offset):
    # then dropping a route or picking two options can never undercut the one-hot penalty
    k = 0
    for s in scores:
        base = float(s.min())
        offset += base
        for val in s:
            Q[k, k] += float(val) - base
            k += 1
    # one-hot: A (sum x - 1)^2 = A (sum_i x_i + 2 sum_{i<j} x_i x_j - 2 sum x_i + 1)
    start = 0
    for o in options:
        idx = np.arange(start, start + len(o))
        for i in idx:
            Q[i, i] += -A
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                Q[idx[a], idx[b]] += A
                Q[idx[b], idx[a]] += A
        offset += A
        start += len(o)
    # availability: B (sum w_i z_i - N)^2 with w = ships or slack weights
    for c in {cs for cs, _ in slack}:
        idxs, w = [], []
        k = 0
        for o in options:
            for j in range(len(o)):
                if o.cls[j] == c:
                    idxs.append(k)
                    w.append(float(o.ships[j]))
                k += 1
        for si, (cs, weight) in enumerate(slack):
            if cs == c:
                idxs.append(n_opt_vars + si)
                w.append(float(weight))
        N = float(problem.available[c])
        w = np.array(w)
        for a, ia in enumerate(idxs):
            Q[ia, ia] += B * (w[a] ** 2 - 2 * N * w[a])
            for b in range(a + 1, len(idxs)):
                Q[ia, idxs[b]] += B * w[a] * w[b]
                Q[idxs[b], ia] += B * w[a] * w[b]
        offset += B * N**2
    return FleetQUBO(Q=Q, offset=offset, var_route=np.array(var_route), var_option=np.array(var_option),
                     options=options, scores=scores, labels=labels)


def decode(fq: FleetQUBO, x: np.ndarray) -> tuple[list[int], bool]:
    """Chosen option per route; repairs one-hot violations with the best-scoring candidate."""
    choice, valid = [], True
    for r, (o, s) in enumerate(zip(fq.options, fq.scores)):
        sel = np.nonzero((fq.var_route == r) & (x.astype(bool)))[0]
        opts = fq.var_option[sel]
        if len(opts) != 1:
            valid = False
            opts = opts if len(opts) else np.arange(len(o))
        choice.append(int(opts[np.argmin(s[opts])]))
    return choice, valid


@dataclass
class AnnealOutcome:
    solver: str
    energy: float
    one_hot_valid: bool
    genes: Genes
    seconds: float
    n_vars: int


def solve(problem: FleetProblem, fq: FleetQUBO, solver: str = "openjij_sqa", seed: int = 0,
          reads: int = 30, sweeps: int = 2500) -> AnnealOutcome:
    t0 = time.perf_counter()
    if solver == "openjij_sqa":
        res = solve_openjij_sqa(fq.Q, reads=reads, sweeps=sweeps, seed=seed)
    elif solver == "openjij_sa":
        res = solve_openjij_sa(fq.Q, reads=reads, sweeps=sweeps, seed=seed)
    elif solver == "pi_sqa":
        from greenfleet.quantum.sqa import qubo_to_ising

        h, J, _ = qubo_to_ising(fq.Q)
        scale = max(np.abs(J).sum(axis=1).max(), np.abs(h).max(), 1e-9)
        res = PathIntegralSQA(trotter=8, sweeps=max(100, sweeps // 8), reads=max(2, reads // 3),
                              temperature=0.01 * scale, gamma0=2.0 * scale, seed=seed).solve(fq.Q)
    else:
        raise ValueError(solver)
    choice, valid = decode(fq, res.x)
    genes = options_to_genes(problem, fq.options, choice)
    return AnnealOutcome(res.solver, float(res.energy + fq.offset), valid, genes, time.perf_counter() - t0, fq.n_vars)


def export_bqm(fq: FleetQUBO):
    """dimod BQM with readable labels - submit with dwave.system.DWaveSampler when hardware is available."""
    return to_bqm(fq.Q, offset=fq.offset, labels=fq.labels)


def assignment(fq: FleetQUBO, choice: list[int], problem: FleetProblem) -> np.ndarray:
    """Binary vector for a per-route choice, with slack bits = binary expansion of unused ships."""
    x = np.zeros(fq.n_vars)
    used = np.zeros(len(problem.class_ids))
    for r, j in enumerate(choice):
        x[np.nonzero((fq.var_route == r) & (fq.var_option == j))[0]] = 1
        used[fq.options[r].cls[j]] += fq.options[r].ships[j]
    slack_idx = np.nonzero(fq.var_route == -1)[0]
    by_class: dict[int, list[int]] = {}
    for i in slack_idx:
        cid = problem.class_ids.index(fq.labels[i][2:].split(",")[0])
        by_class.setdefault(cid, []).append(i)
    for cid, idxs in by_class.items():
        rest = int(max(problem.available[cid] - used[cid], 0))
        for b, i in enumerate(idxs):
            x[i] = (rest >> b) & 1
    return x


def energy_of_choice(fq: FleetQUBO, choice: list[int], problem: FleetProblem) -> float:
    """QUBO energy of a per-route choice with optimally set slack bits."""
    return float(qubo_energy(fq.Q, assignment(fq, choice, problem))[0] + fq.offset)


@dataclass
class LazyOutcome:
    solver: str
    genes: Genes
    choice: list[int]
    score: float                 # weighted normalised objective of the decoded plan
    feasible_availability: bool
    iterations: int
    n_vars: int
    seconds: float


def plan_score(fq: FleetQUBO, choice: list[int]) -> float:
    return float(sum(s[j] for s, j in zip(fq.scores, choice)))


def solve_qubo(problem: FleetProblem, options: list[RouteOptions], weights: dict[str, float],
               solver: str = "openjij_sqa", seed: int = 0, price_steps: int = 4, **kw) -> LazyOutcome:
    """Lazy-constraint annealing + Lagrangian calibration of the FuelEU shadow price.

    The pooled FuelEU penalty is max(0, deficit) x rate: convex and piecewise linear, so a QUBO can
    only carry it as a linear price. A price equal to the penalty rate is exact while the pool is in
    deficit but over-rewards surplus; bisecting the price on [0, rate] until the pool balance is ~0
    recovers the right trade-off. The plan with the best *exact* objective is returned.
    """
    from greenfleet.optimization.options import objective_scales

    rate = fueleu_rate(problem)
    scales = objective_scales(options)
    in_scope = rate > 0 and bool(np.any(problem.eu_scope > 0)) and weights.get("cost", 0) > 0
    lo, hi, price = 0.0, rate, rate
    best, best_val, t0 = None, np.inf, time.perf_counter()
    for _ in range(price_steps if in_scope else 1):
        out = solve_lazy(problem, options, weights, solver, seed, fe_price=price if in_scope else None, **kw)
        val = weighted_value(problem, out.genes, weights, scales)
        if val < best_val:
            best, best_val = out, val
        if not in_scope:
            break
        _, _, parts = problem.evaluate(out.genes, return_parts=True)
        surplus = parts["fleet"]["fe_cb_g"][0] > 0
        if surplus:
            hi = price
        else:
            lo = price
        price = 0.5 * (lo + hi)
    best.seconds = time.perf_counter() - t0
    return best


def solve_lazy(problem: FleetProblem, options: list[RouteOptions], weights: dict[str, float],
               solver: str = "openjij_sqa", seed: int = 0, max_iter: int = 6, **kw) -> LazyOutcome:
    """Anneal with availability penalties only for classes that the current plan over-uses.

    Coupling strengths from slack-encoded inequalities dwarf objective differences and trap
    single-flip annealers; adding them lazily (cutting-plane style) keeps the QUBO well
    conditioned. Stops when the decoded plan respects every class's availability.
    """
    t0 = time.perf_counter()
    classes: set[int] = set()
    out = fq = None
    scale = kw.pop("penalty_scale", 1.5)
    for it in range(1, max_iter + 1):  # noqa: B007  (it is reported after the loop)
        fq = build_qubo(problem, options, weights, availability_classes=classes, penalty_scale=scale, **kw)
        out = solve(problem, fq, solver, seed=seed)
        choice, _ = decode(fq, _last_x(problem, fq, out))
        used = np.zeros(len(problem.class_ids))
        for r, j in enumerate(choice):
            used[fq.options[r].cls[j]] += fq.options[r].ships[j]
        violated = {int(c) for c in np.nonzero(used > problem.available)[0]}
        if not violated:
            break
        if violated <= classes:
            scale *= 2.0            # constraint already present but still violated: escalate its weight
        classes |= violated
    return LazyOutcome(out.solver, out.genes, choice, plan_score(fq, choice), not violated, it, fq.n_vars,
                       time.perf_counter() - t0)


def _last_x(problem: FleetProblem, fq: FleetQUBO, out: AnnealOutcome) -> np.ndarray:
    """Reconstruct the option part of the binary vector from the decoded genes."""
    x = np.zeros(fq.n_vars)
    for r, o in enumerate(fq.options):
        cat = out.genes.cat[0, 4 * r: 4 * r + 4]
        match = np.nonzero(np.all(o.cat == cat, axis=1) & np.isclose(o.u, out.genes.u[0, r]))[0]
        if len(match):
            x[np.nonzero((fq.var_route == r) & (fq.var_option == match[0]))[0]] = 1
    return x


def weighted_value(problem: FleetProblem, genes: Genes, weights: dict[str, float], scales: dict[str, float]) -> float:
    """Weighted normalised objective of a plan under the *exact* fleet model (pooled FuelEU)."""
    _, CV, parts = problem.evaluate(genes, return_parts=True)
    objs = parts["objectives_all"]
    unit = {"cost": 1e6}
    val = sum(w * objs[k][0] * unit.get(k, 1.0) / scales[k] for k, w in weights.items() if w)
    return float(val + 1e3 * CV[0])
