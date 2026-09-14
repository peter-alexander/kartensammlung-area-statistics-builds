# CRU-CY source policy

## Scope

This provider publishes annual country climate statistics from the Climatic Research Unit (CRU), University of East Anglia, using CRU-CY country-averaged time series derived from CRU-TS.

Production release: CRU-CY v4.10, source run `2606161920`, covering 1901–2025.

Included variables:

- `tmp` – annual mean air temperature
- `tmx` – annual mean of daily maximum temperature
- `tmn` – annual mean of daily minimum temperature
- `pre` – annual precipitation total
- `dtr` – annual mean diurnal temperature range
- `frs` – annual ground/frost-day frequency
- `wet` – annual wet-day frequency
- `pet` – annual mean daily potential evapotranspiration
- `cld` – annual mean cloud cover
- `vap` – annual mean vapour pressure

No local interpolation, extrapolation or cross-source fallback is added.

## Source and release guard

CRU describes CRU-CY as country-averaged time series calculated from CRU-TS. The current CRU family page identifies CRU-CY v4.10 as the current release and lists the period 1901–2025 and the ten production variables above. CRU announced v4.10 on 25 June 2026.

At the September 2026 audit, the current CEDA copy had not yet been updated to v4.10, so production uses the canonical CRU website release directly.

The downloader first reads the CRU family page and detects the current CRU-CY version. If CRU advertises any version other than the audited v4.10, the production build fails deliberately. A newer release must be audited before source paths, country definitions or production mappings are changed.

For v4.10, every production download also verifies that all ten variable directories expose the exact audited 292-name source-area universe before mapped data are accepted.

## Country mapping

CRU-CY v4.10 exposes 292 country, territory, island and subregional source files per variable, including the aggregate `all` file.

Production uses exactly 218 direct country or territory equivalents. Each accepted CRU source name is mapped explicitly to one registry ISO3-style code in `config/cru-cy-country-map.json`.

Examples include:

- `Austria` → `AUT`
- `USA` → `USA`
- `Kosovo` → `XKX`
- `Falkland_Isl` → `FLK`
- `Western_Sahara` → `ESH`

Seventy-three CRU source areas are deliberately excluded because they are subregions, island groups or fragments rather than a direct equivalent of one Kartensammlung registry area. They are not combined locally into synthetic national values.

The resulting direct mapping covers 218 of the 250 registry areas. The remaining 32 registry areas are an explicit, asserted set. No fuzzy matching is used at build time.

## Completeness and missing values

The September 2026 full audit downloaded and parsed all 2,180 mapped source files: 218 mapped areas × 10 variables.

Nine variables (`tmp`, `tmx`, `tmn`, `pre`, `dtr`, `frs`, `wet`, `cld`, `vap`) contain a valid annual `ANN` value for all 218 mapped areas in every year from 1901 through 2025.

`pet` is different. CRU-CY v4.10 contains `-999.0` for every year for exactly these 13 mapped small-island areas:

- `BMU`
- `CCK`
- `COK`
- `CXR`
- `IOT`
- `KIR`
- `LCA`
- `MDV`
- `MHL`
- `NFK`
- `NRU`
- `TKL`
- `TUV`

Production therefore publishes PET for 205 areas and keeps those 13 areas missing. `-999.0` is never emitted as a statistical value.

## Annual semantics and interpretation

CRU-CY files contain monthly values, seasonal aggregates and an annual `ANN` field. Production publishes only `ANN`.

The interpretation differs by variable:

- `tmp`, `tmx`, `tmn`, `dtr`, `pet`, `cld` and `vap` use the annual mean supplied by CRU-CY.
- `pre` uses the annual accumulated precipitation total supplied in `ANN`.
- `frs` and `wet` use the annual day-frequency total supplied in `ANN`.

`tmx` and `tmn` are means of daily maximum and minimum temperature, not annual temperature records. They therefore complement the CCKP/ERA5 `TXx` and `TNn` extreme indices instead of duplicating them.

CRU defines `wet` as wet-day frequency. The underlying CRU methodology uses a 0.1 mm precipitation threshold. `frs` is statistically derived from minimum-temperature information, so country averages may contain fractional day counts.

CRU-TS is constructed to provide complete time series and may use climatological substitutions where observations are unavailable. This source characteristic must be considered when interpreting sparse-data regions and long-term changes.

## License and attribution

The CRU conditions-of-use page states that the datasets are made available under the Open Database License (ODbL). Rights in individual database contents are made available under the Database Contents License under attribution and share-alike conditions.

Production identifies the CRU-derived provider separately in the statistics collection and keeps the derived data machine-readable.

Required attribution:

`Climatic Research Unit, University of East Anglia`

Primary reference:

Harris, I., Osborn, T. J., Jones, P. & Lister, D. (2020), Version 4 of the CRU TS monthly high-resolution gridded multivariate climate dataset, Scientific Data 7, 109.

`https://doi.org/10.1038/s41597-020-0453-3`

Relevant source pages:

- `https://crudata.uea.ac.uk/cru/data/hrg/`
- `https://crudata.uea.ac.uk/cru/data/hrg/cru_ts_4.10/`
- `https://crudata.uea.ac.uk/cru/data/hrg/cru_ts_4.10/crucy.2606161920.v4.10/Read_Me_CRU_CY.txt`
- `https://crudata.uea.ac.uk/cru/data/hrg/cru_ts_4.10/crucy.2606161920.v4.10/Read_Me_CRU_CY_Updated_Country_Definitions.txt`
- `https://crudata.uea.ac.uk/cru/data/hrg/cru_ts_4.10/crucy.2606161920.v4.10/Release_Notes_CRU_CY_4.10.txt`

## September 2026 regression values

Austria 2025 is retained as a source regression assertion:

- `tmp`: 8.4 °C
- `tmx`: 13.2 °C
- `tmn`: 3.7 °C
- `pre`: 870.1 mm
- `dtr`: 9.5 °C
- `frs`: 133.5 days
- `wet`: 148.1 days
- `pet`: 2.1 mm/day
- `cld`: 59.4 %
- `vap`: 8.5 hPa

These assertions are source checks for CRU-CY v4.10. Any future release must be audited rather than forced to reproduce v4.10 values.