# ILOSTAT Gender Pay Gap source policy

## Scope

The Kartensammlung publishes the worldwide **unadjusted Gender Pay Gap** from the official ILOSTAT Wages and Working Time Statistics (COND) data family.

The indicator is part of the existing provider:

```text
ilostat-wages
```

and is shown alongside the worldwide minimum-wage indicators. Eurostat Gender Pay Gap data remain a separate regional source and are not mixed into the ILOSTAT series.

## Canonical source

The production source is the official annual ILOSTAT table:

```text
EAR_GGAP_OCU_RT_A
```

Table label:

```text
Gender wage gap by occupation (%)
```

Underlying indicator code:

```text
EAR_GGAP_OCU_RT
```

The country series uses:

```text
classif1 = OCU_SKILL_TOTAL
```

The build validates the table id, exact table label, annual frequency, indicator code and required classification against the current ILOSTAT catalogue before accepting the data.

## Meaning of the indicator

The published statistic is the unadjusted difference between average hourly earnings of men and women, expressed as a percentage of men's average hourly earnings.

Interpretation:

- positive values: women's average hourly earnings are lower than men's;
- zero: equal average hourly earnings in the published aggregate;
- negative values: women's average hourly earnings are higher than men's.

Negative observations are therefore valid values and are not converted to zero.

The indicator is **unadjusted**. It does not control for occupation, industry, education, experience, working-time patterns or other compositional differences that can contribute to observed earnings differences.

## Why `OCU_SKILL_TOTAL` is canonical

The source table contains multiple occupation-classification systems, including total categories for ISCO-08, skill level and ISCO-88.

A September 2026 audit found:

- `OCU_SKILL_TOTAL`: 1,156 mapped country-year observations, 124 countries, 1969–2025;
- `OCU_ISCO08_TOTAL`: a smaller subset;
- `OCU_ISCO88_TOTAL`: a much smaller historical subset.

Where two or more of these total classifications overlap, their published Gender Pay Gap values are numerically identical. No conflicting overlapping total values were found.

`OCU_SKILL_TOTAL` is therefore used directly because it contains the complete canonical country-year set without requiring a fallback chain, averaging or duplicate resolution.

## Why the broader derived series is not used

ILOSTAT also publishes average hourly earnings of employees by sex. A separate audit tested whether the Gender Pay Gap could be derived from the male and female local-currency hourly earnings series using:

```text
(male hourly earnings - female hourly earnings) / male hourly earnings × 100
```

This derived series would increase historical country coverage from 124 to 146 countries. Male and female observations also came from the same ILOSTAT source code for every matched pair in the audit.

However, comparison with the official published Gender Pay Gap for 1,136 overlapping country-years showed that the two series are not perfectly interchangeable:

- mean absolute difference: about 0.107 percentage points;
- 1,112 of 1,136 overlaps were within 0.05 percentage points;
- several historical observations differed materially;
- individual discrepancies reached more than 10 and in one case more than 20 percentage points.

The Kartensammlung therefore does **not** replace or extend the official statistic with its own calculation merely to gain more countries. The authoritative published ILOSTAT Gender Pay Gap remains the production source.

## Coverage audit, September 2026

Official canonical series:

```text
observations = 1,156
countries = 124
source years = 1969–2025
```

Exact-year coverage in recent years:

| Year | Countries |
|---:|---:|
| 2018 | 54 |
| 2019 | 64 |
| 2020 | 50 |
| 2021 | 61 |
| 2022 | 55 |
| 2023 | 50 |
| 2024 | 47 |
| 2025 | 28 |

Because the observations are survey/administrative-source statistics rather than a complete annual panel, no single recent exact year provides adequate worldwide coverage.

## Temporal display policy

The production frequency is:

```text
latest-observation-through-year
```

For every displayed cutoff year `Y`, each country shows its latest official ILOSTAT observation whose source year is less than or equal to `Y`.

Important consequences:

- values are carried forward **unchanged** only for map display;
- no value is interpolated;
- no trend is estimated;
- no missing recent value is replaced by another provider;
- the real `sourceYear` is retained for every displayed country value;
- `dataAgeYears` and `carriedForward` are retained as observation metadata;
- the frontend displays the actual data year in hover/InfoBox output.

The default cutoff is the current build year. With the 2026 build this is:

```text
defaultYear = 2026
```

while the newest real source observations are from 2025.

## Recency and stale observations

The source has uneven country update schedules. As of the 2026 cutoff:

- 124 countries have at least one official observation;
- 57 have a latest observation no more than 3 years old;
- 80 no more than 5 years old;
- 110 no more than 10 years old;
- a small number of countries have substantially older latest observations.

The oldest latest-country observation in the September 2026 audit was 47 years old.

The Kartensammlung deliberately does **not** impose an arbitrary maximum-age cutoff. Such a cutoff would create another undocumented statistical selection rule and would make historical coverage disappear at an arbitrary boundary. Instead, the actual source year remains visible so users can judge recency directly.

The absence of a recency cutoff must therefore not be interpreted as saying that all displayed country values are equally current.

## Countries intentionally absent

The official ILOSTAT series does not contain every country. In the September 2026 audit, for example:

```text
DEU = absent
POL = absent
JPN = absent
```

These countries are not fabricated from other data and are not filled from Eurostat inside the ILOSTAT payload.

Production validation instead requires countries known to exist in the official series across different regions:

```text
AUT, USA, IND, FRA, BRA, MEX
```

## Relationship to Eurostat

Eurostat publishes its own Gender Pay Gap series for European countries. It remains available as a separate regional indicator.

The two sources are not merged observation by observation and neither is a fallback for the other because their source systems, coverage and methodological production pipelines differ.

This means a European country can legitimately have:

- an ILOSTAT value with one source year;
- a separate Eurostat value with another year or value;
- or only one of the two sources.

Provider identity is part of the statistical meaning and must remain visible.

## Extreme values

The official ILOSTAT series contains both large positive and large negative observations. The September 2026 audit of each country's latest observation ranged approximately from:

```text
-125.2 % to +62.5 %
```

These values are retained exactly as published. The pipeline does not clamp, winsorise, replace or silently discard them.

Extreme values can reflect the composition of the measured workforce, source methodology, limited samples or unusual labour-market structures. They should therefore be interpreted together with country/source context rather than treated as errors solely because they are outside the common range.

## Fixed map classification

The production map uses stable fixed class boundaries:

```text
-10, 0, 5, 10, 15, 25
```

This gives seven classes and preserves the economically important zero boundary explicitly:

- below -10 %;
- -10 to below 0 %;
- 0 to below 5 %;
- 5 to below 10 %;
- 10 to below 15 %;
- 15 to below 25 %;
- 25 % and above.

The breaks are not recalculated from each data release, so the visual meaning remains stable over time.

## Provenance and update strategy

The provider downloads the current table directly from the ILOSTAT API during the scheduled build. Each generated payload records:

- source dataset id;
- source indicator id;
- selected classification;
- source-year range;
- source API URL;
- temporal selection policy;
- per-observation source code/status/note codes where provided by ILOSTAT.

The same production safeguards used by the minimum-wage provider remain in place: source-schema validation, coverage validation, content-addressed snapshot generation, FTP deployment, browser CORS checks and public byte comparison after deployment.
