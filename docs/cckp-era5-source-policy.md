# World Bank CCKP / ERA5 source policy

## Scope

This provider publishes annual country statistics from the World Bank Climate Change Knowledge Portal (CCKP) country aggregation of ERA5.

Production collection: `era5-x0.25` / `historical_era5`, annual time series, country mean aggregation.

Included variables:

- `tas` – average mean surface air temperature
- `pr` – precipitation
- `txx` – maximum of daily maximum temperature
- `tnn` – minimum of daily minimum temperature
- `fd` – frost days, Tmin < 0 °C
- `tr` – tropical nights, Tmin > 20 °C
- `rx1day` – largest 1-day precipitation
- `rx5day` – largest 5-day cumulative precipitation

`tasmax` and `tasmin` are deliberately excluded. During the September 2026 source audit, both single-variable and combined CCKP API requests returned their country time series exactly equal to `tas`. Until that source/API behavior is clarified, those two series must not be published as distinct statistics.

## Source and history

CCKP describes ERA5 as the fifth-generation ECMWF atmospheric reanalysis and provides derived products at 0.25-degree resolution. The public documentation still describes the ERA5 collection as 1950–2022, but the live CCKP v1 API was audited directly and currently exposes complete annual country time series through 2025.

The production downloader starts at 1950 and asks for the previous calendar year. If that full annual period is not yet available, it falls back year-by-year, but never below the configured minimum latest year. A candidate year is accepted only if every audited variable and country has the complete annual series ending in that year.

No local interpolation, extrapolation or cross-source fallback is created.

## Country mapping

The live CCKP API currently returns 246 country/territory codes for every production variable.

CCKP uses `KSV` for Kosovo; the Kartensammlung country registry uses ISO3-style `XKX`. Production therefore applies exactly one explicit alias:

- `KSV` → `XKX` / `country:XKX`

After this alias, CCKP maps directly to 246 of the 250 registry areas. The four deliberately missing registry areas are:

- `country:ATA` – Antarctica
- `country:ESH` – Western Sahara
- `country:FLK` – Falkland Islands
- `country:SGS` – South Georgia and the South Sandwich Islands

No fuzzy name matching is used.

## Interpretation

Country values are spatial aggregations of the gridded ERA5 products. In particular:

- `fd` and `tr` may be fractional because the number of days is averaged spatially across a country.
- `txx` and `tnn` are country-aggregated annual climate indices, not national station records.
- `rx1day` and `rx5day` are likewise spatially aggregated precipitation indices and should not be presented as a single observed point extreme.

## License and attribution

The World Bank CCKP metadata states that CCKP data adhere to the Creative Commons Attribution 4.0 International license (CC BY 4.0).

Production attribution:

`World Bank Climate Change Knowledge Portal (CCKP); ERA5 / ECMWF Copernicus Climate Change Service`

CCKP data reference for ERA5 0.25-degree observed climate data:

`https://doi.org/10.57966/128g-6s70`

Relevant source pages:

- `https://climateknowledgeportal.worldbank.org/`
- `https://climateknowledgeportal.worldbank.org/index.php/metadata`
- `https://worldbank.github.io/climateknowledgeportal/docs/collections/era5-x0.25.html`

## September 2026 audit

The direct live audit established:

- 8 accepted production variables
- 246 CCKP areas for every variable
- 246 mapped registry areas after `KSV` → `XKX`
- 76 annual observations per area from 1950 through 2025
- complete 2025 coverage for all 246 mapped areas
- successful API metadata with no warning messages

For Austria in 2025, the audited source values are:

- `tas`: 7.86 °C
- `pr`: 1080.68 mm
- `txx`: 29.94 °C
- `tnn`: -12.36 °C
- `fd`: 120.30 days
- `tr`: 0.25 days
- `rx1day`: 29.69 mm
- `rx5day`: 71.18 mm

These values are retained as regression assertions when 2025 is the newest source year.
