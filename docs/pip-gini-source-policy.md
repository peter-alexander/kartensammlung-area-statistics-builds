# World Bank PIP Gini source policy

## Scope

This document records the source and temporal policy for the country-statistics indicator `income-inequality.gini` from the World Bank Poverty and Inequality Platform (PIP).

The decision is intentionally different from the other PIP indicators in this repository. Poverty headcounts, poverty gaps and the other existing PIP welfare indicators are built from the annualized `fill_gaps=true` PIP series. Gini is not.

## Current upstream release

Audit date: 2026-09-13.

PIP production version used for the audit:

- version: `20260324_2021_01_02_PROD`
- release date: 2026-03-24
- PPP version: 2021
- reporting level: national

## Why Gini cannot use the existing annualized PIP query

The public PIP API exposes a `gini` column, but its content depends on the temporal query mode.

Fresh live queries against the current production release showed:

| Query | Non-null Gini observations | Countries | Years |
| --- | ---: | ---: | --- |
| survey query, default / `fill_gaps=false` | 2,475 | 171 | 1963–2025 |
| survey query, explicit `fill_gaps=false` | 2,475 | 171 | 1963–2025 |
| `povline=3`, `fill_gaps=false` | 2,475 | 171 | 1963–2025 |
| no poverty line, `fill_gaps=true` | 0 | 0 | — |
| `povline=3`, `fill_gaps=true` | 0 | 0 | — |

The official World Bank `pipr::get_stats()` interface is consistent with this behavior: its default is `povline = NULL` and `fill_gaps = FALSE`.

Decision: **Gini is a survey/distribution indicator. It must be built from actual PIP survey observations. PIP's annual interpolation/extrapolation path must not be used for Gini.**

The Kartensammlung does not invent interpolation or extrapolation for this indicator.

## Income versus consumption distributions

The 2,475 non-null API rows contain:

- 1,520 income-distribution observations;
- 955 consumption-distribution observations.

There are 88 country-year groups with more than one valid distribution. All 88 duplicates have different Gini values. The difference can be large: the maximum audited spread between parallel distributions for the same country and year was about 0.19348 on the 0–1 scale, or 19.35 Gini points on the displayed 0–100 scale.

Therefore the builder must never:

- take the first API row arbitrarily;
- globally prefer income over consumption;
- globally prefer consumption over income;
- average the parallel distributions.

### Canonical PIP selection

The existing PIP `fill_gaps=true` series contains exactly one canonical row per country-year and retains the `welfare_type`, even though its Gini field is null.

The audit compared the survey rows with that canonical annual PIP series:

- all 88 duplicate country-years were uniquely resolved by matching `welfare_type`;
- 88/88 duplicate groups produced exactly one canonical survey row;
- no welfare-type mismatch was found among canonical survey observations for which a matching annual PIP row exists;
- 50 older singleton survey observations have no annual comparison row, mostly because they predate the annualized PIP series; these do not create any selection ambiguity.

After canonical selection:

- **2,387 country-year Gini observations** remain;
- **171 countries** are represented;
- source years run from **1963 through 2025**.

Decision: **PIP's own canonical `welfare_type` is authoritative whenever multiple survey distributions exist for a country-year.** Singleton survey observations are retained directly; if a corresponding canonical annual row exists, their welfare type must agree.

## Temporal representation on the map

Survey coverage is necessarily irregular. Exact-year country coverage in recent canonical survey years is much smaller than total country coverage; for example:

- 2018: 93 countries
- 2019: 78
- 2020: 70
- 2021: 81
- 2022: 72
- 2023: 56
- 2024: 24
- 2025: 4

A hard recency cutoff would discard a large amount of legitimate survey information. For example, using only observations at most five years old would show roughly 115 countries at the 2025 cutoff, while the complete canonical survey history covers 171 countries.

At the same time, relabeling an old survey value as if it had been measured in the current year would be misleading.

Decision: **Gini uses `latest-observation-through-year` semantics.**

For every displayed cutoff year `Y`:

1. select, for each country, the latest canonical PIP survey observation whose source year is `<= Y`;
2. carry that value forward unchanged for display at cutoff `Y`;
3. never interpolate, extrapolate or otherwise alter the Gini value;
4. preserve the actual `sourceYear` in observation metadata;
5. expose the actual source/data year in the user interface.

The cutoff series ends at the PIP release year, not the browser's current calendar year. For the current release this means:

- source observations: 1963–2025;
- displayed cutoffs: 1963–2026;
- default cutoff: 2026;
- countries at the default cutoff: 171.

The payload frequency is therefore `latest-observation-through-year`, not `annual`.

## Observation metadata

Each displayed Gini observation carries at least:

- `sourceYear`: actual PIP reporting/data year;
- `dataAgeYears`: cutoff year minus source year;
- `carriedForward`: whether the displayed cutoff differs from the source year;
- `welfareType`: income or consumption;
- PIP survey/distribution metadata where available;
- a human-readable `sourceNote` stating whether the value is the original observation for the cutoff year or a previous unchanged survey value.

This provenance is essential because a value displayed at cutoff 2026 may originate from an earlier household survey.

## Relationship to Eurostat Gini

The existing Eurostat indicator `income-inequality.gini` remains intentionally separate and visible.

Eurostat measures the Gini coefficient of equivalised disposable income within its European social-statistics framework. PIP uses the income or consumption welfare distribution available for the country's poverty/inequality survey system. These are methodologically different series, not distributor copies of one another.

Decision: **do not merge Eurostat and PIP Gini into a single mixed observation series.** Provider identity is analytically meaningful.

## Production validation

A full normal PR build against the live PIP production release succeeded with the survey-based implementation:

- canonical Gini observations: 2,387;
- countries: 171;
- duplicate groups resolved canonically: 88;
- source years: 1963–2025;
- displayed cutoffs: 1963–2026;
- default cutoff: 2026;
- default coverage: 171 countries;
- PIP provider indicators after addition: 15;
- test snapshot: `25c6e244a1c6cd1f`.

The existing 14 PIP indicators continued to build with their previous annualized semantics and coverage. No existing PIP indicator is migrated to the survey-based path.
