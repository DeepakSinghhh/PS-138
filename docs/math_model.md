# Mathematical model: green fleet deployment

This document formalises Delivery Table item 2 ("Mathematical Optimization Formulation"). The implementation is
`backend/greenfleet/optimization/problem.py`. It evaluates the whole model, fully vectorised, for a population of plans at
once, at about 55,000 plans per second on 4 CPU cores.

## Sets and data

| Symbol | Meaning | Source |
|---|---|---|
| $r \in \mathcal{R}$ | services (two-port shuttles; round trip $2L_r$ nm) | `config/routes_*.yaml`, distances via `searoute` |
| $k \in \mathcal{K}_r$ | vessel classes allowed on $r$ (type **and** capacity) | `config/vessels.yaml` |
| $f \in \mathcal{F}_r(y)$ | fuels/pathways bunkerable for $r$ in year $y$ within the fuel system's range | `config/ports.yaml`, `config/fuels.yaml` |
| $D_r$ | demand (TEU / pax per week for liners, t per year for tramp services) | routes |
| $\mathrm{LF}_r$, $t^{port}_r$ | load factor, port + manoeuvring hours per round trip | routes |
| $\mathrm{Cap}_k$, $N_k$ | cargo capacity, ships available | vessels |
| $H$ | operating hours per ship-year, $8760 \times 0.95$ | model constant |

## Decision variables (per service $r$)

| Variable | Domain | Meaning |
|---|---|---|
| $k_r$ | $\mathcal{K}_r$ | vessel class, i.e. **vessel type and capacity** |
| $f_r$ | $\mathcal{F}_r(y)$ | **fuel type / production pathway** (HFO, VLSFO, MGO, LNG low/high-pressure, bio-LNG, grey/bio/e-methanol, grey/blue/e-ammonia, grey/e-hydrogen) |
| $s_r$ | $\{0,1\}$ (only if a port has shore power in $y$) | **shore power** at berth |
| $e_r$ | $\{0,1,\dots,E-1\}$ | extra ships above the minimum fleet (**vessel mix size**) |
| $u_r$ | $[0,1]$ | position of the **cruising speed** between the slowest feasible and the maximum service speed |

## Derived quantities

Effective capacity (larger tanks for alternative fuels reduce cargo space):
$\mathrm{Cap}^{eff}_{r} = \mathrm{Cap}_{k_r}\,(1-\lambda_{fam(f_r)})$.

Round trips needed (weekly liners need at least one sailing per week):
$$N_r = \max\!\Big(\frac{D^{yr}_r}{\mathrm{Cap}^{eff}_r\,\mathrm{LF}_r},\ 52\cdot\mathbb{1}[\text{liner}]\Big)$$

Minimum fleet at maximum service speed $v^{max}_{r,k}$ (capped by 95 % MCR in the route's average weather):
$$n^{min}_r = \Big\lceil N_r\,\big(2L_r/v^{max}_{r,k} + t^{port}_r\big)/H \Big\rceil, \qquad n_r = n^{min}_r + e_r$$

Time budget per round trip and commanded speed:
$$\mathrm{RTT}_r = \frac{n_r H}{N_r},\quad v^{lo}_r = \max\!\Big(v^{min}_k,\ \frac{2L_r}{\mathrm{RTT}_r - t^{port}_r}\Big),\quad v_r = v^{lo}_r + u_r\,(v^{max}_{r,k}-v^{lo}_r)$$

Demand and weekly frequency therefore hold **by construction**. More ships allow slower speeds, which is the
slow-steaming trade-off between charter cost and fuel.

## Energy and fuel

Propulsion power (IMO Fourth GHG Study bottom-up model), for the laden leg ($\ell$) and return leg ($b$):
$$P_{r,\cdot}(v) = P^{ref}_k\Big(\frac{T_\cdot}{T^{des}_k}\Big)^{0.66}\Big(\frac{v}{v^{des}_k}\Big)^{3}\frac{w_k(v, \mathrm{Bf}_r)}{\eta_f}\,c_k(v, \mathrm{Bf}_r)$$

where:
- $w_k$ is the expected Kwon (2008) weather power factor, averaged over a Beaufort distribution and four heading sectors (capped at 1.5×);
- $\eta_f = 0.917$ is the hull-fouling efficiency;
- $c_k$ is the **learned correction** distilled from the certified-monotone Q-PHYS model (`prediction/surrogate.py`).

Energy per round trip, with the SFOC load curve $\sigma(L) = 0.455L^2 - 0.710L + 1.280$ (fuel cells use their own part-load curve) and family-specific brake-specific energy consumption $\beta_f$ (MJ/kWh):
$$E^{sea}_r = \sum_{\text{legs}} P\,\frac{L_r}{v_r}\,\sigma(P/\mathrm{MCR})\,\beta_{f_r} + P^{aux,sea}_k\,\frac{2L_r}{v_r}\,\beta^{aux}$$
$$E^{port}_r = P^{aux,berth}_k\,t^{port}_r\,(1-s_r\,\omega_r)\,\beta^{aux},\qquad
E^{idle}_r = P^{aux,berth}_k\,\big(\mathrm{RTT}_r - t^{port}_r - 2L_r/v_r\big)\,\beta^{aux}$$
$$E_r = N_r\big(E^{sea}_r + E^{port}_r + E^{idle}_r\big)\ \ [\mathrm{MJ/yr}],\qquad
W_r = N_r\,P^{aux,berth}_k\,t^{port}_r\,s_r\,\omega_r\ \ [\mathrm{kWh/yr}]$$

Here $\omega_r$ is the share of port time at berths with shore power (OPS).

## Emissions (well-to-wake)

Per fuel (FuelEU Maritime Annex II method, with methane slip $C_{slip}$ and pilot-fuel share $p_f$):
$$I^{WtW}_f = \mathrm{WtT}_f + \frac{(1-C_{slip})(C_{f,CO_2} + C_{f,CH_4}\mathrm{GWP}_{CH_4} + C_{f,N_2O}\mathrm{GWP}_{N_2O}) + C_{slip}\,\mathrm{GWP}_{CH_4}}{\mathrm{LCV}_f}$$
$$G_r = E_r\,\big[(1-p_f)\,I^{WtW}_f + p_f\,I^{WtW}_{MGO}\big] + W_r\,\gamma^{grid}_r$$

Shore-power electricity is counted at the local grid factor $\gamma^{grid}$ (India CEA trajectory, EU country values),
which is honest lifecycle accounting. FuelEU itself counts OPS electricity as zero, and the compliance calculation does so.

## Objectives (minimise), matching Delivery Table item 2

$$\min\ F_1 = \sum_r E_r / 40\,500 \quad \text{(fuel, t HFO-equivalent / yr)}$$
$$\min\ F_2 = \sum_r G_r \quad \text{(well-to-wake GHG, t CO}_2\text{e / yr)}$$
$$\min\ F_3 = \sum_r \big[ n_r\,c^{day}_k\,365\,(1+\pi_{fam}) + \textstyle\sum_f m_{r,f}\,p_f + W_r\,p^{el}_r + \mathrm{ETS}_r + \mathrm{Levy}_r \big] + \mathrm{FuelEU}^{pen}$$

$F_3$ is the annual cost in M USD. The optional fourth objective is schedule risk,
$F_4 = \sum_r \frac{D_r}{\sum D}\,(1-P^{on}_r)$.

- **EU ETS**: $\mathrm{ETS}_r = (CO_2 + [CH_4\,\mathrm{GWP} + N_2O\,\mathrm{GWP}]_{y\ge2026})\,\epsilon_r\,\phi(y)\,p^{EUA}$, with the EU scope $\epsilon_r$ (1 intra-EU, 0.5 extra-EU) and phase-in $\phi$ (70 % in 2025, 100 % from 2026).
- **FuelEU (pooled)**: pool intensity $\bar I = \frac{\sum_r \epsilon_r E_r I_{f_r}}{\sum_r \epsilon_r (E_r\,\mathrm{RWD}_{f_r}) + \epsilon_r W_r\,3.6}$, where RWD = 2 for RFNBOs until 2033.
  - Compliance balance: $\mathrm{CB} = (I^{target}_y - \bar I)\,E^{scope}$.
  - Penalty: $\mathrm{FuelEU}^{pen} = \frac{\max(0,-\mathrm{CB})}{\bar I \cdot 41\,000}\cdot 2400$ EUR. Pooling across the company's ships is modelled explicitly.

## Constraints

| Constraint | Formulation | Handling |
|---|---|---|
| Cargo demand & weekly frequency | via $N_r$, $n^{min}_r$, $v^{lo}_r$ | by construction |
| **Schedule reliability** | $P^{on}_r = \Phi\!\Big(\frac{\mathrm{buffer}_r + 0.5(S_r - S^{max}_r) - \mu_r S_r}{\sqrt{(\sigma_r S_r)^2 + \sigma^{2}_{port,r}}}\Big) \ge \underline{P}$ (default 0.8), with sea time $S_r$ | penalty in CV |
| Fleet availability | $\sum_{r: k_r = k} n_r \le N_k$ | penalty in CV |
| **Emission limits: IMO CII** | $\frac{CO_2^{TtW}/(\mathrm{Cap}^{CII}_k \cdot \mathrm{dist})}{(1-Z_y)\,a_k\,\mathrm{Cap}_k^{-c_k}} \le d^{(C)}_k$ (rating C or better) | penalty in CV |
| **Emission limits: FuelEU** | $\mathrm{CB} \ge 0$ (mode "hard") or penalty in $F_3$ (mode "penalty") | CV or cost |
| Fleet emission cap (optional) | $F_2 \le \bar G$ | penalty in CV |
| Fuel availability & range | $f_r \in \mathcal{F}_r(y)$: bunkerable at a port on the route in year $y$, and round trip (or one way if both ports bunker it) within the fuel system's range | encoded in the domain |

The constraint violation CV is the sum of normalised violations. All optimizers use Deb's constrained dominance:
feasible beats infeasible, lower CV beats higher CV, and Pareto dominance applies among feasible plans.

## Exact reformulation (for optimality gaps)

Every route-level quantity depends only on that route's decision. Routes interact solely through linear fleet-level
terms: ships per class, the FuelEU pool numerator and denominator, the emission cap, and the objective sums. With speeds
discretised to $q$ levels, enumerating each route's options $j$ (class × fuel × OPS × extra ships × speed level) gives
a **multiple-choice MILP**:
$$\min \sum_{r,j} c_{rj}\,x_{rj} \quad\text{s.t.}\quad \sum_j x_{rj} = 1\ \forall r,\quad \sum_{r,j:\,k_{rj}=k} n_{rj}\,x_{rj} \le N_k\ \forall k,\quad \sum_{r,j} (\mathrm{num}_{rj} - I^{target}\,\mathrm{den}_{rj})\,x_{rj} \le 0$$
Options infeasible on their own (CII, schedule) are dropped, and options dominated within the same class are pruned. The pruning is
verified against brute force in `tests/test_optimization.py`. An ε-constraint sweep gives the exact cost–emissions front. The same structure gives the
**QUBO** (one-hot per route, slack-encoded availability), described in [algorithms.md](algorithms.md).
