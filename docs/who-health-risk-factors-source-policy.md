# WHO health risk factors source policy

## Scope

The Kartensammlung publishes seven country indicators from direct World Health Organization data for three major health risk factors: adult obesity, current tobacco use and total alcohol consumption.

All seven indicators remain inside the existing `who` provider. No World Bank WDI fallback is used because the direct WHO series already have broad, internally consistent country coverage.

## Canonical direct sources

### Adult obesity

- WHO indicator: `NCD_BMI_30A`
- UUID: `BEFA58B`
- published name: `Obesity in adults (age 18+)`
- age: 18 years and older
- measure: age-standardized prevalence, BMI >= 30
- sexes: total, male, female
- production years: 1990-2022
- mapped Kartensammlung countries: 192 for every published year and each sex
- confidence intervals: retained

The September 2026 live WHO CSV contains a complete annual panel through 2022. This is newer than the year range still shown on some human-readable WHO metadata pages; the production build validates the current machine-readable download directly.

### Current tobacco use

- WHO indicator: `M_Est_tob_curr_std`
- UUID: `75DDA77`
- published name: `Tobacco use`
- age: 15 years and older
- measure: age-standardized current use of smoked and/or smokeless tobacco
- e-cigarettes: not included in this indicator
- sexes: total, male, female
- mapped Kartensammlung countries: 165
- confidence intervals: retained

The current source file contains broad model years 2000, 2005, 2007, 2010, 2015, 2020, 2021, 2022, 2025 and 2030 plus a special 2018 partial release.

Production deliberately publishes only the non-future series through 2022. The 2025 and 2030 values are not exposed as ordinary historical observations because the current country-statistics frontend/provider contract does not yet distinguish model projections from observations/estimates. They may be added later with explicit projection semantics.

The source year 2018 is also deliberately excluded from the map series: it contains only seven mapped countries per sex and would otherwise appear in the year selector as if it were a comparable worldwide data year. The exclusion is explicit in configuration and is copied into payload source metadata as `excludedYears: [2018]`.

After these rules the production years are:

`2000, 2005, 2007, 2010, 2015, 2020, 2021, 2022`

Coverage in 2022 is 165 countries for total, men and women. In 2021 one male and total-country value is missing, which is retained as a real source gap rather than filled or interpolated.

### Alcohol consumption

- WHO indicator: `SA_0000001688`
- UUID: `EE6F72A`
- published name: `Alcohol consumption (age 15+)`
- measure: litres of pure alcohol consumed per person aged 15+ per year
- production years: 2000-2022
- mapped Kartensammlung countries: 188 in every year
- sex dimension: total only in this WHO series
- confidence intervals: retained

The WHO measure covers total consumption, including recorded and unrecorded alcohol, with adjustments for tourist/cross-border consumption. It corresponds to the SDG 3.5.2 concept.

## Production indicators

The seven published ids are:

- `risk-factor.obesity-adults-percent`
- `risk-factor.obesity-adults-male-percent`
- `risk-factor.obesity-adults-female-percent`
- `risk-factor.tobacco-use-percent`
- `risk-factor.tobacco-use-male-percent`
- `risk-factor.tobacco-use-female-percent`
- `risk-factor.alcohol-consumption-litres`

## No interpolation or cross-provider splicing

No missing country-year value is interpolated, extrapolated or filled from another provider. Direct WHO values are the complete production source for these indicators.

The tobacco series therefore remains intentionally sparse in time, and the single 2021 source gap remains visible.

## Confidence intervals

All seven source series provide lower and upper uncertainty bounds. The WHO builder retains them in the normalized payload and validates for every direct observation that the point estimate lies within its published interval.

## Stable map classes

Adult obesity, all sexes:

`5 / 10 / 20 / 30 / 40 / 50 %`

Tobacco use, all sexes:

`5 / 10 / 20 / 30 / 40 / 50 %`

Using the same tobacco breaks for total, male and female series makes direct visual comparison possible.

Alcohol consumption:

`1 / 3 / 5 / 7 / 10 / 15 litres of pure alcohol per person aged 15+ per year`

These boundaries are fixed and are not recalculated when WHO updates the source.

## Live audit, 13 September 2026

The direct WHO downloads were audited against the production country registry before implementation. Results after M49 mapping:

- obesity total: 192 countries, 1990-2022, 192 countries in 2022
- obesity male: 192 countries, 1990-2022, 192 countries in 2022
- obesity female: 192 countries, 1990-2022, 192 countries in 2022
- tobacco total: 165 countries through 2022; 2018 excluded as a 7-country partial year
- tobacco male: 165 countries through 2022; one country missing in 2021
- tobacco female: 165 countries through 2022
- alcohol total: 188 countries, annual 2000-2022, 188 countries in 2022

All required sanity-check countries Austria, Germany, the United States and India are present in the 2022 values of every new indicator.

## Update strategy

The normal monthly WHO workflow downloads the current WHO files directly. Source schemas, indicator ids, configured dimensions, country coverage, value ranges and confidence intervals are validated before a snapshot can be published. Production deployment continues to use the existing content-addressed snapshot, FTP, public-manifest comparison and browser-access checks.
