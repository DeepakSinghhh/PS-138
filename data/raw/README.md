# Raw data drop-in folder

Real datasets are not committed (size and licence). Drop them here and run
`make data`; the loaders auto-detect files and fall back to the physics-informed
synthetic generator when a source is absent.

| Folder | Dataset | Where to get it |
|---|---|---|
| `fuelcast/` | FuelCast (3 ships, operational + weather, fuel t/day) | https://huggingface.co/datasets/krohnedigital/FuelCast (download the parquet/CSV files) |
| `mrv/` | EU MRV annual emission reports (THETIS-MRV export, `.xlsx` or `.csv`) | https://mrv.emsa.europa.eu/#public/emission-report |
| `kaggle_ship_fuel/` | Ship Fuel Consumption & CO2 Emissions (Nigerian waterways) | https://www.kaggle.com/datasets/jeleeladekunlefijabi/ship-fuel-consumption-and-co2-emissions-analysis |
| `user_fleet/` | Your own noon reports or sensor logs (one CSV/parquet per ship) | operator data |

Column names are matched by alias (see `backend/greenfleet/data/loaders.py`), so
minor naming differences between dataset versions are handled automatically. To pin
the mapping, add a `columns.yaml` to the dataset folder, e.g.

```yaml
speed_kn: "Speed Through Water [kn]"
load: "Cargo on board [t]"
wind_speed_ms: "True Wind Speed [m/s]"
fuel: "ME+AE Fuel [t/day]"
```

The PS Delivery Table (item 1) requires the inputs **speed, load, weather and vessel
type**:

- **Load** means cargo load. Fractions, percentages, tonnes or Laden/Ballast labels are
  all accepted. If there is no load column, load is estimated from draft.
- **Vessel type** is read from a column, or inferred from the file name (e.g. `cps_*`
  is a cruise ship, `oss_*` an offshore supply ship).
- **Engine load, power, rpm and torque** columns are *excluded* as target leakage and
  listed in `data/processed/data_card.json`.
