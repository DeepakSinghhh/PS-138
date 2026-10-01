"""QMOEA-H: Hybrid Quantum-inspired Multi-Objective Evolutionary Algorithm.

Encoding (PS Delivery Table item 3, "encoding scheme for fleet decisions")
    For every route r the population holds a quantum individual made of
      * four qudit registers  |class>, |fuel>, |shore power>, |extra ships>
        (real amplitude vectors over each variable's options), and
      * one continuous QPSO coordinate u_r in [0, 1] for the cruising speed.
    A classical fleet plan is obtained by *measuring* every register (option j is drawn
    with probability |psi_j|^2) and reading u_r.

Quantum update mechanisms
    rotation gate   registers turn towards the options of a guide solution: a leader
                    from the external Pareto archive (binary tournament on crowding
                    distance) or the individual's own best, by an angle annealed from
                    dtheta_max to dtheta_min
    quantum NOT     random amplitude swaps (exploration)
    delta well      speeds move by QPSO: u = p +/- beta |mbest - u| ln(1/v), with the
                    attractor p between personal best and leader (quantum tunnelling)
    Zeno persistence each route's collapsed state persists between generations with
                    probability pi_Z (frequent observation freezes a quantum state), so good
                    partial plans survive while registers keep learning where to move
    Hadamard reset  when the archive stops improving, the worst part of the population
                    returns to uniform superposition (catastrophe / re-diversification)
    probability floor keeps every option measurable, avoiding premature collapse

Constraint handling: Deb's constrained dominance in the archive and the personal bests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from greenfleet.optimization.archive import Archive, Tracker, dominance_matrix
from greenfleet.optimization.problem import FleetProblem, Genes
from greenfleet.quantum.qregister import QuditRegister


@dataclass
class QMOEAConfig:
    pop_size: int = 40
    archive_size: int = 100
    dtheta_max: float = 0.10 * np.pi
    dtheta_min: float = 0.01 * np.pi
    not_rate: float = 0.02
    leader_prob: float = 0.8
    beta_max: float = 1.0
    beta_min: float = 0.5
    p_floor: float = 0.01
    stagnation: int = 12
    reset_fraction: float = 0.3
    differential: bool = True     # Han-Kim: rotate only registers whose measurement disagrees with the guide
    entangled: bool = True        # one joint register per route over (class x fuel x OPS x extra ships)
    zeno: float = 0.75            # probability a route's collapsed state persists (quantum Zeno effect)


@dataclass
class RunResult:
    algorithm: str
    genes: Genes
    F: np.ndarray
    CV: np.ndarray
    nfe: int
    history: list[dict] = field(default_factory=list)   # per-generation diagnostics


def _dominates(Fa, CVa, Fb, CVb) -> np.ndarray:
    """Element-wise constrained dominance a > b for paired rows."""
    fa, fb = CVa <= 1e-12, CVb <= 1e-12
    pareto = np.all(Fa <= Fb, axis=1) & np.any(Fa < Fb, axis=1)
    return (fa & fb & pareto) | (fa & ~fb) | (~fa & ~fb & (CVa < CVb))


class QMOEARegister:
    name = "QMOEA-R (register population, ablation)"

    def __init__(self, problem: FleetProblem, config: QMOEAConfig | None = None, seed: int = 0):
        self.problem = problem
        self.cfg = config or QMOEAConfig()
        self.rng = np.random.default_rng(seed)

    def run(self, tracker: Tracker, callback=None) -> RunResult:
        cfg, prob, rng = self.cfg, self.problem, self.rng
        P = cfg.pop_size
        R = prob.R
        sizes = prob.cat_sizes.reshape(R, 4)
        if cfg.entangled:
            # joint (entangled) register per route: option index = mixed-radix code of the 4 genes
            joint = sizes.prod(axis=1)
            reg = QuditRegister(P, joint, p_floor=cfg.p_floor)
            radix = np.column_stack([sizes[:, 1] * sizes[:, 2] * sizes[:, 3], sizes[:, 2] * sizes[:, 3],
                                     sizes[:, 3], np.ones(R, dtype=int)])

            def to_cat(m):
                return (m[:, :, None] // radix[None, :, :] % sizes[None, :, :]).reshape(len(m), 4 * R)

            def to_reg(cat):
                return (cat.reshape(len(cat), R, 4) * radix[None, :, :]).sum(axis=2)
        else:
            reg = QuditRegister(P, prob.cat_sizes, p_floor=cfg.p_floor)

            def to_cat(m):
                return m

            def to_reg(cat):
                return cat
        u = rng.random((P, prob.R))
        archive = Archive(max_size=cfg.archive_size)
        pbest: Genes | None = None
        pbest_F = pbest_CV = None
        gens_total = max(1, tracker.budget // P)
        gen, since_improve = 0, 0
        history = []
        measured = None
        while not tracker.exhausted:
            fresh = reg.measure(rng)
            if gen == 0 or cfg.zeno <= 0:
                measured = fresh
            else:
                # Zeno persistence: each route keeps its collapsed state with probability `zeno`
                # and is re-measured from its (rotated) register otherwise
                keep_route = rng.random((P, R)) < cfg.zeno
                keep = np.repeat(keep_route, measured.shape[1] // R, axis=1)
                measured = np.where(keep, measured, fresh)
            g = Genes(to_cat(measured), u.copy())
            F, CV = tracker.evaluate(g)
            improved = archive.update(g, F, CV)
            since_improve = 0 if improved else since_improve + 1
            if pbest is None:
                pbest, pbest_F, pbest_CV = g, F.copy(), CV.copy()
            else:
                better = _dominates(F, CV, pbest_F, pbest_CV)
                tie = ~better & ~_dominates(pbest_F, pbest_CV, F, CV) & (rng.random(P) < 0.5)
                upd = better | tie
                pbest.cat[upd], pbest.u[upd] = g.cat[upd], g.u[upd]
                pbest_F[upd], pbest_CV[upd] = F[upd], CV[upd]

            frac = min(1.0, gen / max(1, gens_total - 1))
            dtheta = cfg.dtheta_max - (cfg.dtheta_max - cfg.dtheta_min) * frac
            beta = cfg.beta_max - (cfg.beta_max - cfg.beta_min) * frac
            lead = archive.leaders(P, rng)
            use_leader = rng.random(P) < cfg.leader_prob
            guide_cat = np.where(use_leader[:, None], archive.genes.cat[lead], pbest.cat)
            guide = to_reg(guide_cat)
            if cfg.differential:
                # Han & Kim lookup: full angle where the measurement disagrees with a guide that
                # dominates the individual, a smaller angle where it disagrees otherwise, none where it agrees
                guide_F = np.where(use_leader[:, None], archive.F[lead], pbest_F)
                guide_CV = np.where(use_leader, archive.CV[lead], pbest_CV)
                worse = _dominates(guide_F, guide_CV, F, CV)
                differ = measured != guide
                angle = np.where(differ, np.where(worse[:, None], dtheta, 0.4 * dtheta), 0.0)
                reg.rotate(guide, angle)
            else:
                reg.rotate(guide, dtheta)
            reg.not_gate(rng, cfg.not_rate)

            # QPSO move for speeds (delta potential well around pbest/leader attractor)
            phi = rng.random((P, prob.R))
            attractor = phi * pbest.u + (1 - phi) * archive.genes.u[lead]
            mbest = pbest.u.mean(axis=0, keepdims=True)
            sign = np.where(rng.random((P, prob.R)) < 0.5, -1.0, 1.0)
            jump = beta * np.abs(mbest - u) * np.log(1.0 / np.maximum(rng.random((P, prob.R)), 1e-12))
            u = attractor + sign * jump
            u = np.where(u < 0, -u, u)
            u = np.where(u > 1, 2 - u, u)
            u = np.clip(u, 0.0, 1.0)

            if since_improve >= cfg.stagnation:
                D = dominance_matrix(pbest_F, pbest_CV)
                worst = np.argsort(-D.sum(axis=0))[: max(1, int(cfg.reset_fraction * P))]
                reg.hadamard(worst)
                u[worst] = rng.random((len(worst), prob.R))
                since_improve = 0

            rec = {"gen": gen, "nfe": tracker.nfe, "entropy": reg.entropy(), "archive": len(archive.F),
                   "feasible": archive.feasible, "dtheta": float(dtheta)}
            history.append(rec)
            if callback:
                callback(rec, archive)
            gen += 1
        return RunResult(self.name, archive.genes, archive.F, archive.CV, tracker.nfe, history)


@dataclass
class QMOEAHConfig:
    pop_size: int = 40
    archive_size: int = 100
    theta_max: float = 0.25 * np.pi   # superposition angle towards the guide: sin^2 = 0.5 early (broad mixing)
    theta_min: float = 0.10 * np.pi   # late: offspring mostly stay close to their parent
    noise_per_plan: float = 0.0       # expected Hadamard-noise collapses per offspring (0 = 1 + R/25)
    leader_prob: float = 0.9          # guide = archive leader (else a second tournament parent)
    memory_per_plan: float = 0.0      # expected routes per offspring re-measured from memory (0 = 1.2 + R/25)
    memory_dtheta: float = 0.05 * np.pi
    beta_max: float = 1.0
    beta_min: float = 0.3
    sigma0: float = 0.02              # base width of the delta well (keeps speeds exploring)
    stagnation: int = 15
    reset_fraction: float = 0.2
    local_fraction: float = 0.0       # offspring made by local tunnelling (0 = 0.3 for <= 25 routes, else 0.5)
    local_routes: int = 0             # routes perturbed per local offspring (0 = max(1, R // 12))
    coherent: float = 0.5             # share of offspring whose routes collapse coherently (all 4 registers)
    repair_prob: float = 0.9          # collapse-to-guide probability on routes the parent violates and the guide satisfies
    route_merge: float = 1.0          # share of offspring followed by a route-wise merge with their parent (0 = off)


class QMOEAH:
    """QMOEA-H: elitist non-dominated survival + quantum-inspired variation.

    Every generation each offspring is built route by route:
      * superposition crossover - for each categorical register the state
        cos(theta)|parent> + sin(theta)|guide> (plus a uniform Hadamard-noise floor) is measured;
        the guide is an archive leader (crowding tournament) or a second parent;
      * quantum memory - with probability `memory_rate` a route's decision is measured instead
        from a global per-route register that is continually rotated towards archive members
        (a learned distribution of good options, i.e. a quantum-inspired EDA);
      * delta-well mutation for speeds - u = p +/- L ln(1/r), p = phi*u_parent + (1-phi)*u_guide,
        L = beta |u_guide - u_parent| + sigma0 (heavy-tailed tunnelling jumps).
    Survival is (mu + lambda) with constrained non-dominated sorting and crowding distance;
    on stagnation a Hadamard reset replaces the most crowded/worst individuals with fresh
    measurements of the uniform superposition.
    """

    name = "QMOEA-H (quantum-inspired, ours)"

    def __init__(self, problem: FleetProblem, config: QMOEAHConfig | None = None, seed: int = 0):
        self.problem = problem
        self.cfg = config or QMOEAHConfig()
        self.rng = np.random.default_rng(seed)

    def _tournament(self, rank: np.ndarray, crowd: np.ndarray, n: int) -> np.ndarray:
        a, b = self.rng.integers(0, len(rank), n), self.rng.integers(0, len(rank), n)
        better_a = (rank[a] < rank[b]) | ((rank[a] == rank[b]) & (crowd[a] >= crowd[b]))
        return np.where(better_a, a, b)

    def _survive(self, g: Genes, F: np.ndarray, CV: np.ndarray, n: int, *extras: np.ndarray):
        from greenfleet.optimization.archive import crowding_distance, nondominated_sort

        fronts = nondominated_sort(F, CV)
        keep, rank, crowd = [], np.empty(len(F), dtype=int), np.zeros(len(F))
        for r, fr in enumerate(fronts):
            rank[fr] = r
            crowd[fr] = crowding_distance(F[fr]) if CV[fr].max() <= 1e-12 else -CV[fr]
        for fr in fronts:
            if len(keep) + len(fr) <= n:
                keep.extend(fr.tolist())
            else:
                order = fr[np.argsort(-crowd[fr])]
                keep.extend(order[: n - len(keep)].tolist())
                break
        idx = np.array(keep)
        return (g.take(idx), F[idx], CV[idx], rank[idx], crowd[idx], *(e[idx] for e in extras))

    def run(self, tracker: Tracker, callback=None, seeds: Genes | None = None) -> RunResult:
        """``seeds``: optional plans placed in the initial population (e.g. MILP warm start, see warmstart.py)."""
        cfg, prob, rng = self.cfg, self.problem, self.rng
        N, R = cfg.pop_size, prob.R
        # exploration and local tunnelling grow (sub-linearly) with network size: large fleets need more
        # route changes per offspring to explore, while 12-route networks keep ~1 change per offspring
        noise = min(0.05, (cfg.noise_per_plan or 1.0 + R / 25) / (4 * R))
        memory_rate = min(0.5, (cfg.memory_per_plan or 1.2 + R / 25) / R)
        local_routes = cfg.local_routes or max(1, R // 12)
        memory = QuditRegister(1, prob.cat_sizes, p_floor=noise)
        archive = Archive(max_size=cfg.archive_size)

        pop = prob.random_genes(N, rng)            # measurement of the uniform superposition
        if seeds is not None and len(seeds.u):     # warm start: at most a quarter seeded, the rest stays random
            k = min(len(seeds.u), max(1, N // 4))
            pop.cat[:k], pop.u[:k] = seeds.cat[:k], seeds.u[:k]
        F, CV, RV, RF = tracker.evaluate(pop, route_cv=True, route_f=True)
        archive.update(pop, F, CV, RV)
        pop, F, CV, rank, crowd, RV, RF = self._survive(pop, F, CV, N, RV, RF)
        gen, since_improve, history = 0, 0, []
        while not tracker.exhausted:
            frac = min(1.0, tracker.nfe / max(1, tracker.budget - N))
            theta = cfg.theta_max - (cfg.theta_max - cfg.theta_min) * frac
            beta = cfg.beta_max - (cfg.beta_max - cfg.beta_min) * frac
            par = self._tournament(rank, crowd, N)
            use_leader = rng.random(N) < cfg.leader_prob
            lead = archive.leaders(N, rng)
            mate = self._tournament(rank, crowd, N)
            guide_cat = np.where(use_leader[:, None], archive.genes.cat[lead], pop.cat[mate])
            guide_u = np.where(use_leader[:, None], archive.genes.u[lead], pop.u[mate])
            pc, pu = pop.cat[par], pop.u[par]

            # superposition crossover, done jointly per route so a route's decision stays coherent:
            # P(route collapses to guide) = sin^2(theta), else to parent
            p_guide = np.sin(theta) ** 2
            # violation-guided collapse: where the parent's route violates CII/schedule and the guide's does
            # not, the route collapses to the guide with high probability
            guide_rv = np.where(use_leader[:, None], archive.extra[lead], RV[mate])
            fix = (RV[par] > 1e-12) & (guide_rv <= 1e-12)
            p_route = np.where(fix, cfg.repair_prob, p_guide)
            coherent = rng.random(N) < cfg.coherent
            route_mask = np.repeat(rng.random((N, R)) < p_route, 4, axis=1)       # route-coherent collapse
            reg_mask = rng.random((N, 4 * R)) < p_guide                          # register-wise collapse
            to_guide = np.where(coherent[:, None], route_mask, reg_mask)
            child = np.where(to_guide, guide_cat, pc)
            # Hadamard-noise floor: each register may collapse to a uniformly random option
            noisy = (rng.random(child.shape) < noise) & (prob.cat_sizes[None, :] > 1)
            child = np.where(noisy, np.floor(rng.random(child.shape) * prob.cat_sizes[None, :]).astype(int), child)
            # quantum memory: re-measure some routes from the learned global register
            from_mem = rng.random((N, R)) < memory_rate
            if from_mem.any():
                mem = memory.sample(rng, N)
                child = np.where(np.repeat(from_mem, 4, axis=1), mem, child)
            child = np.minimum(child, prob.cat_sizes[None, :] - 1)

            # delta-well (QPSO) move for speeds
            phi = rng.random((N, R))
            att = phi * pu + (1 - phi) * guide_u
            L = beta * np.abs(guide_u - pu) + cfg.sigma0
            sign = np.where(rng.random((N, R)) < 0.5, -1.0, 1.0)
            u = att + sign * L * np.log(1.0 / np.maximum(rng.random((N, R)), 1e-12))
            # absorbing walls: many optima sit exactly on a speed bound (slowest feasible / top speed)
            u = np.clip(u, 0.0, 1.0)

            # local tunnelling: copies of archive members with a few routes re-measured / speed-tunnelled
            n_loc = int(round((cfg.local_fraction or (0.3 if R <= 25 else 0.5)) * N))
            if n_loc:
                src = archive.leaders(n_loc, rng)
                lc, lu = archive.genes.cat[src].copy(), archive.genes.u[src].copy()
                src_rv = archive.extra[src]
                for _ in range(local_routes):
                    # violation-guided tunnelling: perturb a violating route with probability ~ its violation
                    w = src_rv + 1e-3 * (src_rv.sum(axis=1, keepdims=True) <= 1e-12)
                    w = w / w.sum(axis=1, keepdims=True)
                    r_sel = (rng.random((n_loc, 1)) > np.cumsum(w, axis=1)).sum(axis=1).clip(0, R - 1)
                    mode = rng.random(n_loc)
                    rows = np.arange(n_loc)
                    # (a) speed tunnelling on the route
                    sigma_loc = 0.05 + 0.25 * (1 - frac)
                    step = np.where(rng.random(n_loc) < 0.5, -1.0, 1.0) * sigma_loc * np.log(1.0 / np.maximum(rng.random(n_loc), 1e-12))
                    lu[rows, r_sel] = np.clip(lu[rows, r_sel] + np.where(mode < 0.5, step, 0.0), 0.0, 1.0)
                    # (b) re-measure one register of the route from the quantum memory
                    reg_sel = 4 * r_sel + rng.integers(0, 4, n_loc)
                    mem = memory.sample(rng, n_loc)
                    swap = mode >= 0.5
                    lc[rows[swap], reg_sel[swap]] = mem[rows[swap], reg_sel[swap]]
                child = np.vstack([child[: N - n_loc], lc])
                u = np.vstack([u[: N - n_loc], lu])
            kids = Genes(child, u)
            Fk, CVk, RVk, RFk = tracker.evaluate(kids, route_cv=True, route_f=True)
            improved = archive.update(kids, Fk, CVk, RVk)
            pool = [(kids, Fk, CVk, RVk, RFk)]

            # route-wise merge: the objectives are sums over routes, so a child that improves some routes and worsens
            # others is usually dominated and lost. Compare child and parent route by route under a random trade-off
            # direction and keep, per route, whichever decision is better (fewer violations first)
            n_x = N - n_loc
            if cfg.route_merge > 0 and n_x > 0 and not tracker.exhausted:
                sel = np.flatnonzero(rng.random(n_x) < cfg.route_merge)
                pa = par[sel]
                diff = (child[sel] != pc[sel]).reshape(len(sel), R, 4).any(axis=2) | (np.abs(u[sel] - pu[sel]) > 1e-9)
                w = rng.dirichlet(np.ones(prob.n_obj), size=len(sel))
                scale = np.abs(F).mean(axis=0) + 1e-12
                gain = (((RFk[sel] - RF[pa]) / scale) * w[:, None, :]).sum(axis=2)
                dv = RVk[sel] - RV[pa]
                take = (dv < -1e-12) | ((np.abs(dv) <= 1e-12) & (gain < 0))
                mixed = (take & diff).any(axis=1) & (~take & diff).any(axis=1)
                if mixed.any():
                    sel, pa, take = sel[mixed], pa[mixed], take[mixed]
                    mcat = np.where(np.repeat(take, 4, axis=1), child[sel], pc[sel])
                    merged = Genes(mcat, np.where(take, u[sel], pu[sel]))
                    Fm, CVm, RVm, RFm = tracker.evaluate(merged, route_cv=True, route_f=True)
                    improved = archive.update(merged, Fm, CVm, RVm) or improved
                    pool.append((merged, Fm, CVm, RVm, RFm))
            since_improve = 0 if improved else since_improve + 1
            allg = Genes.concat([pop] + [x[0] for x in pool])
            pop, F, CV, rank, crowd, RV, RF = self._survive(
                allg, np.vstack([F] + [x[1] for x in pool]), np.concatenate([CV] + [x[2] for x in pool]), N,
                np.vstack([RV] + [x[3] for x in pool]), np.vstack([RF] + [x[4] for x in pool]))

            # learn the global memory from the archive (rotation towards a random archive member)
            for m in archive.leaders(3, rng):
                memory.rotate(archive.genes.cat[[m]], cfg.memory_dtheta / 3)

            if since_improve >= cfg.stagnation:
                n_reset = max(1, int(cfg.reset_fraction * N))
                worst = np.argsort(rank * 1e6 - np.nan_to_num(crowd, posinf=1e5))[-n_reset:]
                fresh = prob.random_genes(n_reset, rng)
                Ff, CVf, RVf, RFf = tracker.evaluate(fresh, route_cv=True, route_f=True)
                archive.update(fresh, Ff, CVf, RVf)
                pop.cat[worst], pop.u[worst] = fresh.cat, fresh.u
                F[worst], CV[worst], RV[worst], RF[worst] = Ff, CVf, RVf, RFf
                pop, F, CV, rank, crowd, RV, RF = self._survive(pop, F, CV, N, RV, RF)
                since_improve = 0
            rec = {"gen": gen, "nfe": tracker.nfe, "entropy": memory.entropy(), "archive": len(archive.F),
                   "feasible": archive.feasible, "theta": float(theta)}
            history.append(rec)
            if callback:
                callback(rec, archive)
            gen += 1
        return RunResult(self.name, archive.genes, archive.F, archive.CV, tracker.nfe, history)
