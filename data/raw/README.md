# Raw data drop-in folder

Real datasets are not committed (size and licence). Drop them here and run
`make data`; the loaders auto-detect files and fall back to the physics-informed
synthetic generator when a source is absent.

| Folder | Dataset | Where to get it |
|---|---|---|
| `fuelcast/` | FuelCast (3 ships, operational + weather, fuel t/day) | https://huggingface.co/datasets/krohnedigital/FuelCast (download the parquet/CSV files) |
| `mrv/` | EU MRV annual emission reports (THETIS-MRV export, `.xlsx` or `.csv`) | https://mrv.emsa.europa.eu/#public/emission-report |
| `kaggle_ship_fuel/` | Ship Fuel Consumption & CO2 Emissions (Nigerian waterways) | https://www.kaggle.com/datasets/jeleeladekunlefijabi/ship-fuel-consumption-and-co2-emissions-analysis |

Column names are matched by alias (see `backend/greenfleet/data/loaders.py`), so
minor naming differences between dataset versions are handled automatically.
