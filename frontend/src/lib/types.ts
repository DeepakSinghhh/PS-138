export type Obj = "fuel" | "emissions" | "cost" | "schedule_risk";

export interface Scenario {
  network: string;
  year: number;
  fuel_prices: Record<string, number>;
  fuel_price_multiplier: number;
  ets_price_eur: number | null;
  global_levy_usd: number | null;
  grid_factor_multiplier: number;
  allowed_fuels: string[] | null;
  fleet_availability: Record<string, number>;
  red_sea_diversion: boolean;
  monsoon: boolean;
  demand_multiplier: number;
  extra_ops_ports: string[];
  on_time_min: number;
  cii_min_rating: string;
  fueleu_mode: "penalty" | "hard";
  fleet_emission_cap_t: number | null;
  objectives: Obj[];
  max_extra_ships: number;
  speed_levels: number | null;
  use_surrogate: boolean;
  custom_routes: Record<string, unknown>[] | null;
}

export interface Genes { cat: number[][]; u: number[][] }

export interface RoutePlan {
  route_id: string; name: string; ports: string[]; service: string; distance_nm: number; geometry: number[][];
  vessel_class: string; vessel_label: string; vessel_type: string; capacity: number; capacity_unit: string;
  ships: number; min_ships: number; speed_kn: number; speed_range_kn: [number, number]; design_speed_kn: number;
  fuel: string; fuel_label: string; fuel_family: string; shore_power: boolean; round_trips_per_year: number;
  energy_gj: number; fuel_t: Record<string, number>; fuel_hfo_eq_t: number; shore_power_mwh: number;
  co2_ttw_t: number; wtw_co2e_t: number; cost_usd: Record<string, number>;
  cii: { attained: number; required: number; ratio: number; rating: string };
  on_time_probability: number; buffer_hours_per_round_trip: number;
}

export interface Plan {
  objectives: Record<Obj, number>;
  objective_labels: Record<string, string>;
  feasible: boolean;
  violations: Record<string, number>;
  routes: RoutePlan[];
  fleet: {
    ships: number;
    class_usage: Record<string, { used: number; available: number }>;
    fuel_mix_energy_share: Record<string, number>;
    fueleu: { intensity_g_per_mj: number; target_g_per_mj: number; balance_t_co2e: number; penalty_usd: number; in_scope_energy_gj: number };
    shore_power_routes: number;
  };
  explanation?: Explanation;
}

export interface Explanation {
  summary: string; sentences: string[];
  delta_pct: Record<string, number>; delta_pct_vs_slow_steaming: Record<string, number>;
  baseline: Record<string, number>; slow_steaming_baseline: Record<string, number>; plan: Record<string, number>;
}

export interface Solution { i: number; objectives: Record<string, number>; genes: Genes }

export interface OptResult {
  objectives: Obj[]; labels: Record<string, string>; feasible: boolean;
  solutions: Solution[]; picks: Record<string, number>;
  recommended: Plan; explanation: Explanation;
  algorithm: string; budget: number; evaluations: number;
  convergence: { nfe: number; seconds: number; front_size: number; feasible: boolean }[];
  scenario: Scenario;
}

export interface Meta {
  fuels: { id: string; label: string; family: string; family_label: string; pathway: string; wtw_g_per_mj: number;
           lcv_mj_per_kg: number; rfnbo: boolean; range_nm: number; charter_premium: number; capacity_loss: number; source: string }[];
  vessel_classes: { id: string; label: string; cargo: string; capacity: number; capacity_unit: string; dwt: number;
                    design_speed_kn: number; min_speed_kn: number; max_speed_kn: number; mcr_kw: number; available: number }[];
  ports: { id: string; name: string; lon: number; lat: number; country: string; ops_from: number; bunkers: Record<string, number> }[];
  networks: Record<string, { name: string; description: string; routes: number }>;
  objectives: Record<string, string>;
  algorithms: Record<string, string>;
  default_scenario: Scenario;
  regulations: { cii_reduction_pct: Record<string, number>; fueleu_targets: Record<string, number>; fueleu_reference: number; ets_phase_in: Record<string, number> };
}

export interface NetworkInfo {
  name: string; year: number; notes: string[];
  routes: { id: string; name: string; ports: string[]; service: string; cargo: string; demand: number; demand_unit: string;
            distance_nm: number; geometry: number[][]; classes: string[]; fuels: { id: string; label: string; family: string }[];
            shore_power_share: number; eu_scope: number; beaufort: number }[];
  prices: { fuel_usd_per_t: Record<string, number>; ets_usd_per_t: number; levy_usd_per_t: number };
  fueleu_target: number; cii_reduction_pct: number;
  baselines: { current_practice: Plan; slow_steaming: Plan };
  baseline_genes: { current_practice: Genes; slow_steaming: Genes };
}
