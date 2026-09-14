# World Bank / ESMAP solar and PV potential source policy

## Canonical source

The provider `world-bank-esmap-solar-pv` uses the World Bank Data Catalog dataset **Global Photovoltaic Power Potential by Country** and the published country workbook:

- catalog: `https://datacatalog.worldbank.org/search/dataset/0038379/global-photovoltaic-power-potential-by-country`
- workbook: `https://datacatalogfiles.worldbank.org/ddh-published/0038379/1/DR0046831/solargis_pvpotential_countryranking_2020_data.xlsx`
- report page: `https://www.esmap.org/Global%20Photovoltaic%20Power%20Potential%20by%20Country`

The workbook states **March 2020**. This is therefore treated as a static study snapshot, not as an annual 2020 observation and not as a 2025 dataset merely because the current World Bank file endpoint reports a later HTTP Last-Modified timestamp.

The country indicators were prepared by Solargis under contract to the World Bank Group / ESMAP. The World Bank Data Catalog publishes the dataset under **Creative Commons Attribution 4.0 (CC BY 4.0)**.

## Country mapping and coverage

The audited `Country indicators` worksheet has exactly **209 unique country/territory rows**. All source rows map deterministically to the 250-area Kartensammlung country registry.

The only source-code alias is:

- `XKO` -> `XKX` (Kosovo)

No fuzzy matching, country-name matching or territorial synthesis is used.

The 41 registry areas absent from the workbook are pinned in the configuration. A change to this set is a build failure and requires a new source audit.

Seven source rows include a geographic limitation in the workbook note column: either `up to parallel 45°S` or `up to parallel 60°N`. The builder accepts only those two audited note texts, requires exactly seven such rows and publishes the exact ISO3-to-note mapping in `dataset.partialCoverageNotes`. The values are not geographically corrected or extrapolated to the omitted parts of those countries.

## Published indicators

Only the solar/PV variables prepared for the study are published:

1. **Mean global horizontal irradiance (GHI)** — long-term, kWh/m²/day.
2. **Practical PV potential (PVOUT Level 1)** — long-term specific yield, kWh/kWp/day. Level 1 excludes land with identifiable physical obstacles to utility-scale PV development.
3. **PV levelized cost of electricity (LCOE)** — study estimate for 2018, USD/kWh.
4. **PV seasonality index** — ratio between the highest and lowest long-term monthly PVOUT averages.
5. **PV equivalent area** — modeled share of national area required to generate electricity equivalent to the study-era annual electricity consumption under the study assumptions.

GHI, PVOUT, LCOE and seasonality have values for all 209 mapped source areas. PV equivalent area is present for only **135 registry areas**. The additional 74 missing source values are explicitly pinned in the configuration; together with the 41 areas absent from the workbook this yields 115 missing registry areas for that indicator.

The workbook's older auxiliary socioeconomic and power-sector fields (population, GDP, HDI, electricity access, electricity consumption, installed PV capacity, Doing Business reliability and SME tariffs) are deliberately not published by this provider. The Kartensammlung already has newer or more authoritative direct sources for several of those topics, and mixing those historical side fields into this provider would obscure provenance and reference years.

## Snapshot semantics

Indicator payloads use:

- `frequency: "snapshot"`
- `availableYears: [2020]`
- `defaultYear: 2020`

The year is a UI/reference key for the March 2020 study snapshot. It must not be interpreted as saying that long-term GHI, PVOUT or seasonality describe calendar year 2020.

LCOE remains explicitly labeled as a **2018** estimate. PV equivalent area remains tied to the electricity-demand and technology assumptions of the study and must not be presented as a current land requirement.

## Build invariants

The production builder fails closed if any of the following audited properties changes:

- provider license is no longer configured as CC BY 4.0;
- the workbook is not an XLSX/ZIP payload;
- the expected workbook sheets are missing;
- the workbook no longer declares `March 2020`;
- the five relevant source headers change;
- the source no longer has exactly 209 unique country rows;
- an unmapped source code appears;
- the base 209/250 country mapping changes;
- the seven latitude-limited rows change to an unknown note form or their count changes;
- an indicator's exact missing-country set or audited coverage changes;
- audited regression values for Austria, Germany, United States, India, China, South Africa, Namibia and Kosovo change unexpectedly where applicable;
- a value is non-numeric, non-finite or outside the configured sanity range.

The source workbook SHA-256, byte count, HTTP metadata and exact partial-coverage notes are retained in provider metadata for reproducibility.

## No derived fallback

This provider does **not**:

- interpolate missing countries;
- copy values from neighboring states;
- split or merge territories;
- aggregate the Global Solar Atlas raster independently;
- substitute a newer raster product for the published 2020 country-study workbook;
- use a cross-provider fallback.

Missing source values remain missing.
