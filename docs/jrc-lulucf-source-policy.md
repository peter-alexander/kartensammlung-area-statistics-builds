# JRC LULUCF source policy

## Scope

The country-statistics build uses the European Commission Joint Research Centre (JRC) LULUCF Data Hub as the canonical source for these three CO₂ land-use indicators:

- `climate.co2-lulucf-net-flux-mtco2e` → JRC category `LULUCF`
- `climate.co2-lulucf-deforestation-mtco2e` → JRC category `DEFORESTATION`
- `climate.co2-lulucf-forest-land-mtco2e` → JRC category `FOREST`

The current source is the LULUCF Data Hub Version 3.1.1, 2025 NGHGI release:

- Zenodo record: `18352395`
- DOI: `10.5281/zenodo.18352395`
- file: `timeseries_NGHGI_v3.1.csv`
- checksum: `md5:702b46bfe67cca47264fdf272d312005`
- licence: CC BY 4.0
- annual NGHGI time series: 2000–2023

Version 3.1.1 is a patch release of Version 3.1. The JRC states that the patch changes only GCB-derived files; the NGHGI CSV used here is unchanged.

## Why direct JRC instead of WDI

The World Bank WDI rows previously used for these indicators are:

- `EN.GHG.CO2.LU.MT.CE.AR5`
- `EN.GHG.CO2.LU.DF.MT.CE.AR5`
- `EN.GHG.CO2.LU.FL.MT.CE.AR5`

The public WDI source metadata points to the 2022 Grassi et al. ESSD work and cites Zenodo record `7190605`. That Zenodo identifier is unrelated to the LULUCF dataset; the corresponding 2022 NGHGI dataset is record `7190601`. More importantly, that older open dataset ends in 2020 and differs materially from the current WDI observations.

A source audit therefore compared the live WDI series with successive JRC LULUCF Data Hub releases. Version 3.1.1 is a close match to the current WDI data and is a newer primary-source release.

For the overlapping country-year observations in the raw source comparison:

| Indicator | v3.1.1 overlap | within 0.1 Mt | mean absolute difference |
| --- | ---: | ---: | ---: |
| LULUCF net | 4,392 | 4,270 (97.2%) | 0.289 Mt |
| Deforestation | 3,984 | 3,884 (97.5%) | 0.139 Mt |
| Forest | 4,317 | 4,222 (97.8%) | 0.101 Mt |

The residual differences show that WDI is not treated as an identical byte-for-byte redistribution. The direct current JRC release is canonical whenever it is available.

## No WDI fallback

The JRC provider does not mix WDI values into the direct series.

This is deliberate:

- the direct release is newer than the apparent JRC vintage represented by WDI;
- mixing older WDI observations into current JRC country-year gaps could reintroduce superseded national inventory values;
- the direct dataset already satisfies the configured country coverage requirements for the mapped statistics.

If future JRC releases change coverage materially, that should trigger a new source audit rather than silently enabling WDI fallback.

## Semantics and units

The NGHGI database is compiled by JRC from National Greenhouse Gas Inventories submitted to the UNFCCC using IPCC methodologies. Reported country CO₂ fluxes are harmonized into JRC classes and gaps are filled without altering the levels and trends of the reported data.

For the classes used here:

- `FOREST` is forest CO₂ flux excluding organic soils and harvested wood products (HWP), which are represented as separate JRC classes.
- `DEFORESTATION` is conversion of forest land to other land uses.
- `LULUCF` is the net LULUCF CO₂ flux.

The source unit is `Mt CO₂ yr⁻¹`. The existing Kartensammlung target unit remains `Mt CO₂e` for compatibility. For CO₂ alone the numeric conversion factor is exactly 1, so no values are rescaled.

The previous WDI text “excluding non-tropical fires” is not carried into the direct JRC description because the current JRC NGHGI release does not describe the selected `LULUCF` class using that qualifier.

## Additional JRC classes

Version 3.1.1 also exposes `ORG_SOILS`, `OTHER`, and `HWP`. They are intentionally not added in this migration. They can be evaluated as separate indicators later without changing the source policy for the three migrated WDI rows.
