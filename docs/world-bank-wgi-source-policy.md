# World Bank Worldwide Governance Indicators source policy

## Scope

The Kartensammlung publishes the six headline dimensions of the World Bank Worldwide Governance Indicators (WGI) as country statistics.

Canonical source:

- provider: World Bank
- dataset: Worldwide Governance Indicators (WGI)
- release: 2025 Revision
- period: 1996–2024
- frequency: annual observations where WGI publishes a value
- license: CC BY 4.0
- production representation: absolute governance score on the fixed 0–100 scale

The six dimensions are:

- Voice and Accountability (`GOV_WGI_VA_SC`)
- Political Stability and Absence of Violence/Terrorism (`GOV_WGI_PV_SC`)
- Government Effectiveness (`GOV_WGI_GE_SC`)
- Regulatory Quality (`GOV_WGI_RQ_SC`)
- Rule of Law (`GOV_WGI_RL_SC`)
- Control of Corruption (`GOV_WGI_CC_SC`)

## Why the 0–100 score is used

The 2025 WGI revision introduced absolute governance scores on a fixed 0–100 scale in addition to the traditional WGI estimate and percentile-rank representations.

The Kartensammlung uses the absolute 0–100 score because it has three advantages for a time-enabled world map:

1. the scale has a stable and immediately understandable lower and upper bound;
2. a country's value can be compared between years without being mechanically affected by changes in the rank positions of other countries;
3. the six governance dimensions can use the same fixed map classes and are therefore visually comparable with each other.

Percentile ranks are deliberately not used as the primary mapped values because they are relative rankings. The traditional approximately -2.5 to +2.5 estimates are also not used because the new 0–100 score is more understandable for non-specialists while retaining an absolute interpretation within the WGI methodology.

## Methodological revision

The 2025 WGI revision made substantial methodological changes and recalculated the historical estimates back to 1996 to provide a consistent time series under the revised methodology.

Therefore:

- the 2025 revision is treated as one internally consistent release;
- older WGI vintages must not be spliced into the revised historical series;
- no values from other governance datasets are used as fallbacks;
- no interpolation or extrapolation is performed.

A later WGI methodology revision must be audited before production metadata is changed to a new release.

## Interpretation

WGI are perception-based composite governance indicators constructed from multiple underlying data sources. They summarize broad governance concepts and are appropriate for broad cross-country comparison, research and exploratory mapping.

They are not treated by the Kartensammlung as definitive institutional rankings or as precise measurements of individual agencies, laws or policies. Small score differences should not be over-interpreted.

Higher values represent better governance outcomes for all six published dimensions.

## September 2026 live audit

The direct World Bank Indicators API was audited against the production 250-country registry.

Results:

| Dimension | Observations | Countries | Period | 2024 coverage |
| --- | ---: | ---: | --- | ---: |
| Voice and Accountability | 5,259 | 206 | 1996–2024 | 204 |
| Political Stability | 5,229 | 206 | 1996–2024 | 206 |
| Government Effectiveness | 5,142 | 204 | 1996–2024 | 204 |
| Regulatory Quality | 5,143 | 204 | 1996–2024 | 204 |
| Rule of Law | 5,270 | 206 | 1996–2024 | 206 |
| Control of Corruption | 5,175 | 206 | 1996–2024 | 206 |

All source ISO3 codes with observations mapped directly to the production country registry. Austria, Germany, the United States, Brazil and India have 2024 values in every dimension.

## Fixed map classes

All six WGI dimensions deliberately use the same fixed class boundaries:

`20 / 35 / 50 / 65 / 80 / 90 points`

The common classes make maps across dimensions directly comparable. They were selected after auditing the complete 1996–2024 score distributions of all six dimensions rather than optimizing each dimension independently.

The fixed scale also prevents map colours from changing meaning between years.

## Update strategy

The provider is rebuilt directly from the World Bank Indicators API. The build validates:

- the exact six WGI score indicator codes;
- the 0–100 value range;
- minimum historical and current country coverage;
- the 1996 start of the revised history;
- the presence of required reference countries;
- absence of duplicate country-year observations;
- absence of unexpected unmapped ISO3 codes.

The latest sufficiently covered year is used as the default year. For the audited 2025 Revision this is 2024 for all six indicators.
