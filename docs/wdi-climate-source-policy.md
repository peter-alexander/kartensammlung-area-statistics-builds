# WDI climate source policy

## Scope

Six climate indicators intentionally remain in the World Bank WDI provider instead of being migrated to a direct EDGAR/JRC or alternative climate-data provider:

- `co2-emissions-excluding-lulucf.per-capita` → WDI `EN.GHG.CO2.PC.CE.AR5`
- `climate.ghg-total-excluding-lulucf-mtco2e` → WDI `EN.GHG.ALL.MT.CE.AR5`
- `climate.ghg-total-excluding-lulucf-per-capita` → WDI `EN.GHG.ALL.PC.CE.AR5`
- `climate.co2-total-excluding-lulucf-mtco2e` → WDI `EN.GHG.CO2.MT.CE.AR5`
- `climate.co2-intensity-gdp-ppp` → WDI `EN.GHG.CO2.RT.GDP.PP.KD`
- `climate.ghg-total-including-lulucf-mtco2e` → WDI `EN.GHG.ALL.LU.MT.CE.AR5`

This is a deliberate source-policy decision, not an unfinished migration.

The source audit was repeated in September 2026 against the current WDI API, EDGAR 2026 and Global Carbon Budget 2025.

## Current WDI coverage

The September 2026 production-registry audit used only the 250 country codes in the Kartensammlung country registry. World Bank regional and global aggregate codes were deliberately excluded.

| WDI series | Observations | Countries | Years |
| --- | ---: | ---: | --- |
| `EN.GHG.CO2.MT.CE.AR5` | 11,165 | 203 | 1970–2024 |
| `EN.GHG.CO2.PC.CE.AR5` | 11,165 | 203 | 1970–2024 |
| `EN.GHG.ALL.MT.CE.AR5` | 11,165 | 203 | 1970–2024 |
| `EN.GHG.ALL.PC.CE.AR5` | 11,165 | 203 | 1970–2024 |
| `EN.GHG.CO2.RT.GDP.PP.KD` | 6,583 | 191 | 1990–2024 |
| `EN.GHG.ALL.LU.MT.CE.AR5` | 4,224 | 176 | 2000–2023 |
| supporting `EN.GHG.CO2.LU.MT.CE.AR5` | 4,392 | 183 | 2000–2023 |

The shorter LULUCF horizon is expected because the current WDI combined series depends on the separate JRC/EFO LULUCF time series.

## World Bank upstream lineage

The public `WDI_GHG_emissions` preparation repository maintained by Thijs Benschop documents how the WDI greenhouse-gas series are assembled:

- repository: `https://github.com/thijsbenschop/WDI_GHG_emissions`
- latest preparation script found during the audit: `20251117_prepare_EDGAR_data_for_WDI_v2.R`
- script update date: 17 November 2025
- EDGAR input documented by that script: `EDGAR_2025_GHG`, published in October 2025
- LULUCF input documented by that script: European Forest Observatory / JRC NGHGI 2025 time series, version 3.0

The preparation script loads and combines the EDGAR total-GHG, CH₄, N₂O, F-gas and `IEA_EDGAR_CO2` fossil-CO₂ datasets. The fossil CO₂ dataset is explicitly included in the combined EDGAR input used for WDI.

The script maps the prepared EDGAR data to WDI indicator codes and explicitly contains the total-series mappings including:

- `EN.GHG.ALL.MT.CE.AR5` – total greenhouse-gas emissions excluding LULUCF;
- `EN.GHG.CO2.MT.CE.AR5` – total CO₂ emissions excluding LULUCF.

For LULUCF, the same upstream pipeline uses the European Forest Observatory / JRC NGHGI country time series. The WDI total including LULUCF is explicitly constructed as:

`EN.GHG.ALL.LU.MT.CE.AR5 = EN.GHG.ALL.MT.CE.AR5 + EN.GHG.CO2.LU.MT.CE.AR5`

The three standalone LULUCF CO₂ indicators are handled separately by the Kartensammlung `jrc-lulucf` provider because the direct JRC release is independently auditable and licensed compatibly with the public snapshot model. The combined WDI total including LULUCF remains in WDI so that its non-LULUCF component stays on the same WDI/EDGAR/IEA lineage as the other WDI climate totals.

## Verified derived WDI indicators

The September 2026 audit recalculated the derived series from current WDI component series for production countries.

| Relationship | Country-year overlap | Match within `1e-12` | Match within `1e-9` |
| --- | ---: | ---: | ---: |
| CO₂ per capita = CO₂ total × 1,000,000 / population | 11,165 | 11,165 (100%) | 11,165 (100%) |
| GHG per capita = GHG total × 1,000,000 / population | 11,165 | 11,165 (100%) | 11,165 (100%) |
| CO₂ intensity = CO₂ total × 1,000,000,000 / constant-2021-PPP GDP | 6,583 | 6,583 (100%) | 6,583 (100%) |
| GHG including LULUCF = GHG excluding LULUCF + CO₂ LULUCF net flux | 4,224 | 4,218 (99.858%) | 4,224 (100%) |

The six observations in the final relationship outside `1e-12` differ only by floating-point rounding. The largest absolute difference is approximately `1.82e-12 Mt CO₂e`.

This confirms that the ratio/intensity indicators are exact WDI derivations of their component series for production countries and that the country-level total including LULUCF follows the construction documented by the World Bank preparation code.

## Why direct EDGAR is not used for these six series

EDGAR does not have one uniform licence for every component needed to reconstruct these indicators.

The official EDGAR 2026 report states that European Union-owned EDGAR material is generally licensed under CC BY 4.0, but separately identifies the fossil-fuel CO₂ component `IEA-EDGAR CO₂ (v5)`. It is based on IEA (2025) `Greenhouse Gas Emissions from Energy`, as modified by JRC, and is licensed under **CC BY-NC-ND 4.0**.

That restriction propagates through the six candidate indicators:

- `EN.GHG.CO2.MT.CE.AR5` directly contains the IEA-derived fossil-CO₂ component;
- CO₂ per capita derives from that CO₂ series;
- CO₂ intensity derives from that CO₂ series;
- total GHG contains fossil CO₂ as one of its components;
- total GHG per capita derives from that total;
- total GHG including LULUCF derives from the same total plus the LULUCF component.

A direct Kartensammlung reconstruction would therefore not be a simple redistribution of CC BY 4.0 JRC data. It would redistribute and transform a component carrying `NC` and `ND` restrictions. This is materially less compatible with the project's public reusable snapshot model than keeping the published WDI indicators under the existing World Bank provider policy.

This licensing distinction is also why the direct Kartensammlung `edgar` provider intentionally contains the audited CH₄ and N₂O series, but not fossil CO₂ or a reconstructed total-GHG series.

## Global Carbon Budget 2025 comparison

Global Carbon Budget / Global Carbon Project 2025 was audited as the strongest obvious alternative for fossil CO₂.

The tested files were the official 2025 release:

- `GCB2025v15_MtCO2_flat.csv`
- `GCB2025v15_percapita_flat.csv`
- Zenodo record `17417124`

GCB has a much longer fossil-CO₂ history than the WDI series and reaches 2024 in the audited release. However, its country estimates are produced with a different source and estimation methodology. It is therefore not sufficient that the concepts and units look similar; the actual country-year values must agree closely before it can replace the WDI series without changing the meaning of the existing indicator.

The audit compared 10,582 overlapping production-country years.

| Comparison | Within 0.1% | Within 1% | Within 5% | Within 10% | Median relative difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| WDI CO₂ total vs GCB total | 0.91% | 7.76% | 37.89% | 57.02% | 7.659% |
| WDI CO₂ per capita vs GCB per capita | 0.98% | 7.74% | 37.60% | 56.78% | 7.777% |

Representative 2024 total-CO₂ differences:

| Country | WDI Mt CO₂ | GCB Mt CO₂ | Relative difference |
| --- | ---: | ---: | ---: |
| Austria | 58.0304 | 56.367657 | 2.865% |
| Germany | 579.9356 | 572.319175 | 1.313% |
| United States | 4,632.1649 | 4,904.119652 | 5.545% |
| India | 3,153.8291 | 3,193.478015 | 1.242% |
| China | 13,124.728 | 12,289.03675 | 6.367% |
| Brazil | 491.4688 | 483.011562 | 1.721% |
| South Africa | 440.1678 | 439.830514 | 0.077% |
| Australia | 383.4031 | 386.732383 | 0.861% |

The differences are systematic and far too large for GCB to be treated as a drop-in republication of the WDI/EDGAR series. Replacing WDI with GCB would create a new statistical series with a methodological break, not merely improve the source path.

GCB remains a useful independent fossil-CO₂ dataset and may be suitable for a separate future indicator/provider if there is a reason to expose its methodology explicitly. It is not a substitute for the existing WDI indicators.

## PRIMAP-hist is not a replacement

PRIMAP-hist v2.7 provides a broad global greenhouse-gas time series, but since v2.7 it is distributed under **CC BY-NC-SA 4.0**. That is not suitable as the general direct source for these public reusable statistics snapshots without obtaining additional rights.

PRIMAP also explicitly advises extra care with its LULUCF data because of data-availability and methodological issues. It therefore does not provide a cleaner direct replacement for the WDI total including LULUCF.

## Source-policy decision

The six indicators in scope remain intentionally in the World Bank WDI provider.

No production values, indicator IDs, titles, classifications, snapshots or provider assignments are changed by this audit.

The direct-source split is therefore:

- **EDGAR direct:** audited CH₄ and N₂O indicators whose direct source terms permit the project's reuse model;
- **JRC LULUCF direct:** standalone audited LULUCF CO₂ indicators;
- **World Bank WDI:** the six CO₂ / total-GHG / derived climate indicators listed in this document because their internally consistent lineage contains the restricted IEA-EDGAR fossil-CO₂ component;
- **Global Carbon Budget:** not substituted into the existing WDI series because the empirical country-year comparison demonstrates a different methodology and value series;
- **PRIMAP-hist:** not used as a replacement because of the current non-commercial share-alike licence and LULUCF caveats.

## When to reopen this audit

Reopen the source decision only if one of the following materially changes:

- EDGAR replaces the IEA-derived fossil-CO₂ component with a source compatible with the Kartensammlung redistribution model;
- the IEA-EDGAR licence changes materially;
- World Bank changes the construction or provenance of these WDI greenhouse-gas series;
- Global Carbon Budget or another authoritative source becomes the intended statistical series for the Kartensammlung rather than merely an alternative dataset;
- another global source offers genuinely equivalent country-level values, suitable coverage and compatible reuse terms.

A newer EDGAR release alone is not enough reason to migrate the six WDI series if the source definition and licensing constraints remain unchanged.
