# Algorithms

This document covers Delivery Table item 3 ("Quantum-Inspired Optimization Algorithm: quantum optimization or equivalent,
encoding scheme for fleet decisions, quantum update mechanisms") and the quantum-inspired parts of item 1.
Every algorithm runs on classical hardware. "Quantum-inspired" describes the mechanics the algorithms borrow from
quantum computing, not a speed-up claim.

## 1. Quantum core (`backend/greenfleet/quantum`)

### Qudit registers (`qregister.py`)
A decision variable with $K$ options is a real amplitude vector $|\psi\rangle = \sum_j \alpha_j |j\rangle$, with
$\sum_j \alpha_j^2 = 1$. Four gates act on it:

| Gate | Effect |
|---|---|
| **Measurement** | collapses to option $j$ with probability $\alpha_j^2$ |
| **Rotation** $R(\Delta\theta)$ | Givens rotation towards a guide option $g$ in the plane of $|g\rangle$ and the orthogonal remainder of the state. For $K=2$ it is exactly the Han & Kim Q-bit rotation gate (unit-tested) |
| **Quantum NOT** | swaps two amplitudes (for $K=2$: $\alpha \leftrightarrow \beta$) |
| **Hadamard reset** | returns a register to the uniform superposition |

A probability floor keeps every option measurable, which avoids the premature collapse of naive QEAs.

### QPSO (`qpso.py`)
Quantum-behaved PSO (Sun et al. 2004): each particle sits in a δ potential well around the attractor
$p = \varphi\,p_{best} + (1-\varphi)\,g_{best}$ and is sampled as
$x = p \pm \beta\,|m_{best} - x|\,\ln(1/u)$. The heavy-tailed $\ln(1/u)$ term acts like tunnelling: occasional
long jumps out of local optima. There is a single control parameter $\beta$, annealed from 1.0 to 0.5. It is used for
hyperparameter tuning (the Q-PHYS booster and MPS) and for continuous genes.

### QIEA (`qiea.py`)
Binary quantum-inspired EA (Han & Kim 2002) with the rotation lookup table, quantum-NOT mutation and a Hadamard reset
on stagnation. It is used for feature selection. The four PS-mandated inputs (speed, load, weather, vessel type) are
always kept.

### Simulated quantum annealing (`sqa.py`)
A from-scratch **path-integral Monte Carlo** simulation of a transverse-field annealer:
- $M$ Trotter replicas of the Ising system are coupled by $J_\perp = -\tfrac{T}{2}\ln\tanh\!\big(\Gamma/(MT)\big)$.
- The transverse field $\Gamma$ is lowered geometrically, so quantum fluctuations dominate at first and the classical ground state at the end.
- Even and odd replicas are updated alternately, vectorised over replicas and reads.

It is validated against brute force on random 12-variable QUBOs. OpenJij SQA/SA are wrapped for comparison, and `to_bqm` exports a `dimod`
model that runs unchanged on D-Wave hardware.

## 2. Q-PHYS: quantum-inspired fuel prediction (`backend/greenfleet/prediction`)

1. **Physics prior**:
   - Ships with history use their own grey-box NNLS fit on physical basis functions: calm water $T^{0.66}v^3$, fouling growth, head-wind and following-wind terms, and a STAWAVE-type wave term. Every basis function is non-decreasing in speed.
   - Unseen ships use the IMO GHG4 + Kwon nominal model, scaled by a class calibration factor.
2. **Matrix Product State regressor** (`mps.py`):
   - Each feature is encoded as a spin-coherent qudit state $\phi_k(x) = \sqrt{\binom{p}{k}}\cos^{p-k}(\pi x/2)\sin^k(\pi x/2)$. For $p=1$ this is the Stoudenmire–Schwab qubit map. With even $p$ the basis spans constants, so irrelevant features can be ignored.
   - The model contracts this product state with an MPS: $f(x) = A_1[\phi(x_1)]\cdots A_n[\phi(x_n)]$.
   - Training uses **DMRG-style alternating least squares**. Each core is solved exactly (ridge) with the others fixed, and QR gauge moves keep the environments orthonormal.
   - The bond dimension bounds the "entanglement" between feature groups. The trained model reports the entanglement entropy across each bond.
3. **Monotone physics-informed booster**: LightGBM on log fuel, with log(prior) as an input and monotone constraints (speed, load, draft, hull age, waves, head wind, prior). Every constrained input is non-decreasing in speed, so the booster's prediction is **certified non-decreasing in speed** (the Q-PHYS-M variant). This matters because the optimizer searches over speed: a non-monotone model would let it exploit spurious dips. Hyperparameters are tuned by **QPSO**.
4. **Blend** of booster and prior × MPS correction, with the weight chosen on validation data.
5. **Split-conformal** 90 % intervals on relative error.
6. **Two heads**:
   - The **ship head** is a digital twin for ships with history.
   - The **fleet head** handles new vessels. It is trained without some ships and calibrated on them, then refitted on all ships (cross-conformal style), so interval coverage holds for vessels never seen before.

The certified-monotone model is distilled into a correction table per (class × loading state × Beaufort × speed),
which the optimizer multiplies into its physics energy model (`surrogate.py`).

## 3. QMOEA-H: hybrid quantum-inspired multi-objective EA (`optimization/qmoea.py`)

**Encoding (per service $r$):**
- Four categorical registers: class (type and capacity), fuel/pathway, shore power, and extra ships.
- One continuous speed coordinate $u_r \in [0,1]$.

A plan is obtained by measuring the registers and reading $u$.

**Each generation:**
1. **Parent selection**: binary tournament on (constrained non-domination rank, crowding distance).
2. **Superposition crossover**:
   - For each route, the offspring state is $\cos\theta\,|\text{parent}\rangle + \sin\theta\,|\text{guide}\rangle$ and is measured. The route collapses to the guide with probability $\sin^2\theta$.
   - Half the offspring collapse whole routes coherently (class, fuel, OPS and fleet size stay consistent); the other half collapse register by register.
   - The guide is an archive leader (tournament on crowding distance, so sparse regions of the front are preferred) with probability 0.9, else a second parent.
   - $\theta$ anneals from $\pi/4$ (broad mixing) to $0.1\pi$ (offspring close to their parent).
3. **Hadamard noise**: each register collapses to a uniformly random option with probability 2 %.
4. **Quantum memory**: a global register per route is continually rotated towards archive members, so it learns a distribution of good options. 10 % of route decisions are re-measured from it (a quantum-inspired EDA).
5. **δ-well speed move**:
   - $u = p \pm L\ln(1/r)$, with $p = \varphi u_{parent} + (1-\varphi)u_{guide}$ and $L = \beta|u_{guide} - u_{parent}| + \sigma_0$.
   - The walls are **absorbing** (clip), not reflecting, because many optima sit exactly on a speed bound: slowest feasible or top speed.
6. **Violation-guided local tunnelling**:
   - 30 % of offspring are archive members with one route re-measured (from memory) or speed-tunnelled.
   - The route is drawn with probability proportional to its own constraint violation (CII, schedule), and uniformly once the member is feasible.
   - In superposition crossover, a route the parent violates but the guide satisfies collapses to the guide with probability 0.9.
7. **Elitist $(\mu+\lambda)$ survival** by constrained non-dominated sorting and crowding distance. An external archive keeps up to 100 non-dominated plans.
8. **Hadamard reset**: after 15 generations without archive improvement, the worst 20 % of the population is replaced by fresh measurements of the uniform superposition.

### Design journey and ablations (honest record)
The algorithm was developed empirically on the India 2030 instance (hypervolume at 4,000 and 10,000 evaluations, 3–4 seeds).
The EU and synthetic networks were **not** used for tuning.

| Version | What changed | HV @ 10k (India) | Lesson |
|---|---|---|---|
| QMOEA-R (register population) | per-individual registers rotated towards archive leaders, QPSO speeds | ≈ 0.2 | re-measuring all 48 registers every generation destroys feasible plans; retained as the ablation **QMOEA-R** |
| + Han–Kim differential rotation, entangled joint registers, Zeno persistence | variants of the register population | 0.0–0.2 | joint (entangled) route registers learn too slowly; persistence helps feasibility but not front quality |
| QMOEA-H v2 | elitist survival + superposition crossover | ≈ 0.59 | survival of the fittest plans is essential; quantum mechanics belongs in *variation* |
| + mutation fix | Hadamard noise per register was scaled by $K-1$ (22 % per fuel register) | ≈ 0.62 | over-mutation |
| + absorbing δ-well walls | clip instead of reflect at speed bounds | ≈ 0.77 (vs MOPSO 0.72, NSGA-III 0.49) | fuel-optimal plans sit exactly on the minimum speed |
| **+ violation-guided tunnelling** | routes to re-measure/tunnel are drawn ∝ their own CII/schedule violation; superposition collapses to the guide where the parent violates and the guide does not | **≈ 0.83** (vs MOPSO 0.72); on the MILP-certified 100-route network it reaches feasibility in every seed where NSGA-III never does | on large networks the few violating routes must be found; *how* a route changes stays quantum (measurement, δ-well), only *where* is guided by the route-separable violation |

The MOQPSO ablation (QPSO on every gene with random-key decoding) shows the qudit registers matter: on the same budget
it reaches HV ≈ 0.52.

## 4. Exact MILP and QUBO (`optimization/options.py`, `milp.py`, `qubo.py`)

- **Options.** For each route: classes × fuels × OPS × extra ships × 5 speed levels. Options infeasible on their own (CII, schedule) are removed, and options dominated within the same class on (cost, GHG, fuel, ships, FuelEU excess, risk) are pruned.
- **MILP (PuLP + CBC).** One-hot per route, ships per class ≤ availability, FuelEU pool (a linear compliance constraint in hard mode; the penalty is linearised in penalty mode). It gives exact extremes in milliseconds and an exact ε-constraint cost–emissions front.
- **QUBO.**
  - Energy: $E(x) = \sum s_{rj}x_{rj} + A\sum_r(\sum_j x_{rj}-1)^2 + B\sum_k(\sum n_{rj}x_{rj} + \sum_b 2^b s_{kb} - N_k)^2$.
  - Per-route scores are shifted so each route's best option scores 0. Then dropping a route or picking two options can never undercut the one-hot penalty, which is set just above the largest per-route score range.
  - **Lazy constraints**: slack-encoded availability terms have couplings about 10⁴ times the objective differences and trap single-flip annealers. They are added only for classes the current annealed plan over-uses, cutting-plane style, with weight escalation if a violation persists.
  - **Lagrangian FuelEU price**: the pooled penalty max(0, deficit) × rate is convex and piecewise linear, so a QUBO can only carry it as a linear price. That price is bisected on [0, rate] until the pool balance is about zero, and the best plan under the *exact* fleet model is kept.
  - **Solvers**: from-scratch path-integral SQA, OpenJij SQA, and classical SA (OpenJij).

## 5. Classical baselines

| Family | Methods |
|---|---|
| Multi-objective (pymoo, random-key encoding) | NSGA-II, NSGA-III, SPEA2, MOEA/D (penalty-based; it has no native constraint handling) |
| Swarm and sanity floor | MOPSO (Coello et al.), random search |
| Single-objective tuners | PSO, real-coded GA (SBX + polynomial mutation), random search, grid, Optuna TPE; binary GA for feature selection |

Every multi-objective algorithm evaluates through the same `Tracker`: identical budgets, identical feasibility rules,
identical front-quality measurement.
