# Eurostat / UN WPP demography overlap policy

## Scope

Two Eurostat indicators intentionally remain visible alongside conceptually similar global UN World Population Prospects (WPP) indicators:

- Eurostat `life-expectancy.at-birth-years` (`demo_mlexpec`) versus UN WPP `life-expectancy.at-birth-years` (`LEx`);
- Eurostat `fertility.total-children-per-woman` (`demo_find`) versus UN WPP `fertility.total-rate` (`TFR`).

The similar titles do not represent accidental duplicate distribution. The two providers publish methodologically different products for different purposes.

The audit was performed on 13 September 2026 using fresh builds from the then-current Eurostat dissemination API and UN World Population Prospects 2024 bulk data, mapped through the same production country registry.

## Methodological distinction

### Eurostat

Eurostat's national demographic statistics are built from detailed national figures supplied by national statistical institutes. Eurostat derives demographic indicators using common calculation methods.

For fertility, `demo_find` is calculated from national live-birth and population data. The total fertility rate is the sum of age-specific fertility rates for a given year.

For mortality, Eurostat collects detailed national death statistics and produces life tables and `demo_mlexpec` life-expectancy statistics from those data.

The current Kartensammlung Eurostat build therefore represents a regional European official-statistics product. At the time of the audit both target series already contained observations through 2024.

Reference metadata:

- fertility: `https://ec.europa.eu/eurostat/cache/metadata/en/demo_fer_esms.htm`
- mortality: `https://ec.europa.eu/eurostat/cache/metadata/en/demo_mor_esms.htm`

### UN World Population Prospects 2024

WPP 2024 is a global demographic estimation and projection system for 237 countries and areas.

Its historical estimates combine empirical information from civil registration and vital statistics, censuses, demographic surveys, administrative records and other country-specific evidence. The Population Division reassesses and harmonizes past demographic trajectories rather than simply redistributing each country's currently published annual statistic.

For WPP 2024, annual fertility, mortality and migration estimates cover calendar years through 2023. From 2024 onward, fertility and mortality trajectories are projections produced with probabilistic models. The Kartensammlung deliberately uses 2023 as the WPP default year for these indicators so a projection is not presented as the latest observed/estimated historical value.

Reference methodology:

- `https://population.un.org/wpp/assets/Files/WPP2024_Methodology.pdf`

This means a 2024 Eurostat observation and a 2024 WPP value are not interchangeable: the former is part of Eurostat's annual regional statistics, while the latter belongs to the WPP projection horizon.

## Numerical audit

The comparison used only common country/year observations through 2023, the last WPP historical estimate year. WPP projection years were excluded from the numerical overlap test.

### Life expectancy at birth

Current source coverage at audit time:

- Eurostat: 46 mapped countries/areas over 1960–2024; default year 2024 with 36 mapped values;
- UN WPP: 237 mapped countries/areas over 1950–2100; default year 2023 with 237 mapped values.

Within the common WPP estimate period:

- common observations: **1,703**;
- Eurostat-only observations inside the compared country/year key space: **0**;
- median absolute difference: **0.1106 years**;
- mean absolute difference: **0.2390 years**;
- maximum absolute difference: **4.311 years**;
- exactly identical observations: **0 / 1,703**.

Difference distribution:

- within 0.01 years: 89 / 1,703 (5.23%);
- within 0.1 years: 785 / 1,703 (46.10%);
- within 0.25 years: 1,309 / 1,703 (76.86%);
- within 0.5 years: 1,511 / 1,703 (88.73%);
- within 1 year: 1,630 / 1,703 (95.71%).

Recent overlap:

| Year | Common areas | Median absolute difference | Maximum absolute difference |
| ---: | ---: | ---: | ---: |
| 2019 | 40 | 0.0597 years | 3.310 years |
| 2020 | 35 | 0.0781 years | 1.470 years |
| 2021 | 35 | 0.0918 years | 1.344 years |
| 2022 | 35 | 0.3121 years | 1.766 years |
| 2023 | 36 | 0.2897 years | 1.375 years |

The largest historical differences occur especially for Azerbaijan and Georgia. For example, Azerbaijan 2006 is 72.8 years in the current Eurostat build and 68.489 years in WPP, a difference of 4.311 years.

The complete absence of exact equality and the material country/year differences prove that the Eurostat series is not a simple regional mirror of WPP.

### Total fertility rate

Current source coverage at audit time:

- Eurostat: 47 mapped countries/areas over 1960–2024; default year 2024 with 37 mapped values;
- UN WPP: 237 mapped countries/areas over 1950–2100; default year 2023 with 237 mapped values.

Within the common WPP estimate period:

- common observations: **1,882**;
- median absolute difference: **0.005 children per woman**;
- mean absolute difference: **0.0170**;
- maximum absolute difference: **0.49**;
- exactly identical observations: **15 / 1,882 (0.80%)**.

Difference distribution:

- within 0.01: 1,393 / 1,882 (74.02%);
- within 0.05: 1,725 / 1,882 (91.66%);
- within 0.1: 1,809 / 1,882 (96.12%);
- within 0.25: 1,867 / 1,882 (99.20%).

Recent overlap:

| Year | Common areas | Median absolute difference | Maximum absolute difference |
| ---: | ---: | ---: | ---: |
| 2019 | 41 | 0.0063 | 0.3107 |
| 2020 | 37 | 0.0060 | 0.3150 |
| 2021 | 36 | 0.0074 | 0.2136 |
| 2022 | 38 | 0.0127 | 0.1453 |
| 2023 | 37 | 0.0578 | 0.1733 |

The largest historical differences are concentrated in countries for which the WPP harmonized demographic reconstruction diverges from the current Eurostat series. Moldova 2014, for example, is 1.33 children per woman in Eurostat and 1.82 in WPP.

The fertility series are often numerically close, but they are still independent statistical products rather than byte-for-byte or rounded copies of one another.

## Decision

**Keep both Eurostat and UN WPP visible for life expectancy and total fertility.**

No provider migration, fallback or observation-level merging is introduced.

Reasons:

1. **Different statistical products.** Eurostat is the regional official-statistics series derived from national submissions; WPP is a globally harmonized UN estimation and projection system.
2. **Different latest periods.** Eurostat already supplies 2024 annual values for many European countries. WPP 2024's historical estimation period ends in 2023 and its 2024 values belong to the projection horizon.
3. **Material numerical differences.** Life expectancy has no exactly identical observations in the 1,703-row overlap and shows meaningful recent and historical differences. Fertility is closer but still visibly revised/harmonized differently.
4. **Different geographic purpose.** WPP provides globally complete comparability across 237 countries/areas; Eurostat provides a more current and regionally authoritative European view.
5. **Observation-level fallback would be misleading.** Filling one series with the other would silently mix two revision and estimation systems under one indicator identity.

The two Eurostat indicators therefore remain useful regional complements to the global WPP indicators. Similar names are acceptable because the provider identity conveys a real methodological choice to the user.

## Reopen conditions

Reopen this audit only if one of the following materially changes:

- Eurostat begins distributing the WPP series directly rather than its own demographic statistics;
- WPP changes its historical estimation boundary or methodology such that the products become demonstrably identical;
- the UI gains a dedicated concept for selecting statistical vintages or source methodologies and the provider-level parallel presentation is redesigned;
- one provider loses the coverage or timeliness that currently justifies keeping both.

Until then, no duplicate-cleanup action is required for these two pairs.