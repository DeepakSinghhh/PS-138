# Data card

## Sources

| Source | Status in this build | Used for |
|---|---|---|
| **Physics-informed synthetic fleet telemetry** (`greenfleet/data/synthetic.py`) | generated (~47k rows, 20 ships, 10 vessel classes, 1 year, 3-hourly) | prediction training and benchmark scenarios A–C; optimizer fuel surrogate |
| **FuelCast** (Hugging Face `krohnedigital/FuelCast`, CC BY-NC-ND 4.0): 2 cruise ships + 1 offshore supply vessel, 5-minute sensor logs with hindcast wind, waves and currents | **used**: 86,757 samples under way (> 3 kn) | prediction benchmark scenario D (real data), **evaluation only**: the files are not redistributed (`data/raw` is git-ignored) and the production model is trained on synthetic data |
| **EU MRV / THETIS-MRV** (EMSA public emission reports, 2023 and 2024): annual per-ship fuel, CO₂, distance, time at sea, transport work | **used**: 26,999 ship-years (23,009 after plausibility filters) | vessel-library validation (`reports/mrv_validation.md`) |
| Kaggle "Ship Fuel Consumption & CO₂ Emissions" (Nigerian waterways) | loader ready; not downloaded (needs a Kaggle account token) | secondary tabular set (ship type, fuel type, weather, distance, engine efficiency) |
| `searoute` maritime network (bundled with the Python package) | used | sea distances and route geometry |
| Regulatory parameters (IMO MEPC.353/354/338/400; FuelEU Regulation 2023/1805 Annex II; EU ETS Directive 2023/959) | encoded in `config/regulations.yaml`, `config/fuels.yaml` | emissions and compliance |

## Canonical schema (PS Delivery Table item 1 inputs)

| Column | Meaning |
|---|---|
| `speed_kn` | speed through water (**speed**) |
| `load_ratio` | cargo load as a fraction of full load (**load**); `draft_ratio` is its physical consequence |
| `wind_speed_ms`, `wind_rel_deg`, `wave_height_m`, `wave_rel_deg`, `current_kn` | **weather** (angles: 0° = from ahead) |
| `vessel_type` (+ one-hot `vt_*`) and particulars (design speed, MCR, displacement, length, block coefficient, aux load) | **vessel type** |
| `trim_m`, `days_since_cleaning` | operational extras |
| `fuel_tpd` | target: fuel consumption, t/day (HFO-equivalent for synthetic data) |

Engine power, rpm, torque and engine load are **excluded** as target leakage. The loaders list them in
`data/processed/data_card.json`.

## Real data: how it is read

- **FuelCast** (`load_fuelcast`): the documented schema is mapped explicitly. Speed over ground and ocean current
  (m/s) become knots; total fuel flow (kg/s) becomes t/day (× 86.4). Wind (`Weather_WindSpeed10M`,
  `Weather_WindDirection10M`; the dataset card writes `…10m`) and waves are made relative to the ship's heading
  (bearing where heading is not logged), and the current is projected on the heading. Load and trim come from the
  fore/aft drafts where recorded (not on CPS Poseidon). Absolute dates are not published, so the 5-minute step index
  gives the time order; the few missing indices are interpolated.
- **EU MRV** (`load_mrv`): the THETIS-MRV export (two title rows above the header). From the reported fields:
  distance = total fuel / fuel per n mile; average speed = distance / time at sea; average cargo carried = fuel per
  n mile / fuel per tonne-n mile of transport work (mass-based for bulk carriers, tankers and container ships,
  deadweight-based for some types); at-berth share = CO₂ at berth in EU ports / total CO₂.

Download commands (full network access):

```bash
# FuelCast
for f in CPS_Poseidon CPS_Triton OSS_Ceto; do
  curl -L -o data/raw/fuelcast/$f.parquet https://huggingface.co/datasets/krohnedigital/FuelCast/resolve/main/$f.parquet
done
# EU MRV: current file versions are listed at https://mrv.emsa.europa.eu/api/public-emission-report/downloadable-files
curl -o data/raw/mrv/mrv_2024.xlsx https://mrv.emsa.europa.eu/api/public-emission-report/reporting-period-document/binary/2024/<version>
make data && python -m greenfleet.benchmark.mrv_validation   # (from backend/)
```

## How the synthetic data is generated

The data-generating process is deliberately **richer than the models' physics prior**, so the ML layer has real
structure to learn:
- Calm-water power with a speed exponent that grows above the design Froude number.
- Ship-specific hull factor (σ 6 %) and engine condition (σ 4 %).
- Hull fouling growth of 4–12 % per year since cleaning.
- A trim penalty around a ship-specific optimum.
- Wind added resistance (relative wind, frontal area, drag vs angle) and wave added resistance (ITTC STAWAVE-1 form).
- The SFOC load curve and auxiliary load.
- Seasonal SW-monsoon weather: autocorrelated wind, wind sea plus swell, currents.
- Cargo load per voyage driving draft (laden/ballast for bulk and tankers, partial loads for containers and passenger ships).
- 2.5 % meter noise and 0.2 % outliers.

The models' prior uses a *different* weather model (Kwon's speed-loss method) and knows nothing about hidden per-ship factors.

## Limitations
- Synthetic data cannot validate absolute accuracy on real ships. It shows that the modelling pipeline recovers known
  structure and ranks methods fairly. Scenario D reports real-data accuracy once FuelCast is supplied.
- No operational data exists yet for ammonia or hydrogen ships. Alternative-fuel consumption is energy-equivalent, with
  family-specific engine efficiency, pilot fuel and cargo-space loss (scenario assumptions in `fuels.yaml`).
- Demand figures in the case-study networks are illustrative magnitudes for realistic services, not operator data.
