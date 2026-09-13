# ILOSTAT minimum-wage source policy

## Scope

The Kartensammlung uses ILOSTAT as the worldwide source for statutory or representative monthly minimum wages.

This provider is intentionally separate from the existing `ilostat` provider. The existing provider contains **ILO Modelled Estimates (ILOEST)** for labour-market indicators. Minimum wages come from the ILOSTAT **Wages and Working Time Statistics (COND)** family and represent reported statutory or methodologically selected minimum-wage values rather than ILO modelled labour-market estimates.

Provider id:

```text
ilostat-wages
```

## Canonical source

The production source is the current ILOSTAT annual table:

```text
EAR_INEE_CUR_NB_A
```

Table label:

```text
Monthly minimum wage by currency
```

The rows themselves use the indicator code:

```text
EAR_INEE_CUR_NB
```

The build validates the table id, table label, annual frequency, underlying indicator code and the expected currency classifications before accepting the source.

The older table id `EAR_4MMN_CUR_NB_A` is not used. The current ILOSTAT API no longer accepts it.

## Published indicators

Two internationally comparable views are published.

### Purchasing-power-adjusted monthly minimum wage

Filter:

```text
classif1 = CUR_TYPE_PPP
```

Unit:

```text
2021 PPP dollars per month
```

This is the primary comparison layer because purchasing-power adjustment reduces the effect of different national price levels.

### Monthly minimum wage in nominal US dollars

Filter:

```text
classif1 = CUR_TYPE_USD
```

Unit:

```text
US dollars per month
```

This is retained as a second view because nominal USD values are useful for monetary comparisons, but they must not be interpreted as a cost-of-living-adjusted measure.

### Local-currency series

ILOSTAT also provides:

```text
classif1 = CUR_TYPE_LCU
```

The local-currency series is deliberately not published as a world map. Values expressed in different national currencies are not directly comparable across countries, so a common choropleth classification would be misleading.

## PPP basis

ILOSTAT has updated its international-comparison conversions to the **2021 International Comparison Program purchasing-power parities**, including PPPs for private consumption. The Kartensammlung therefore labels the current PPP minimum-wage series explicitly as **2021 PPP dollars**.

This basis is part of the visible unit metadata rather than being hidden behind a generic `PPP` label.

## Meaning of “minimum wage” across countries

The source cannot be interpreted as if every country had one identical legal minimum-wage system.

ILOSTAT applies harmonisation rules where there is no single national statutory minimum. Depending on the national system, the reported comparison value can represent a selected regional or sectoral minimum wage according to ILOSTAT methodology. This is why the Kartensammlung descriptions call the series **statutory or representative monthly minimum wage**.

The series is therefore suitable for broad international comparison, but country-specific legal detail should always be checked against the national wage-setting system.

### Austria

Austria is intentionally **not** a required country in the production validation. Austria does not have a general national statutory minimum wage comparable to the systems represented by this ILOSTAT series. Its absence must not be treated as a data-pipeline error.

The production guard instead requires several countries with established values across different regions:

```text
DEU, USA, IND, FRA, POL
```

## Coverage audit, September 2026

The source audit was run against the production country registry with 250 areas.

### PPP series

- 168 mapped countries with at least one value
- source years: 1991–2026
- 2018: 159 countries
- 2019: 160
- 2020: 162
- 2021: 162
- 2022: 159
- 2023: 156
- **2024: 155**
- 2025: 30
- 2026: 4

### Nominal USD series

- 168 mapped countries with at least one value
- source years: 1980–2026
- 2018: 158 countries
- 2019: 159
- 2020: 162
- 2021: 159
- 2022: 164
- 2023: 160
- **2024: 154**
- 2025: 29
- 2026: 1

All source ISO-3 country codes in the PPP and USD subsets mapped to the production registry in the audit. No duplicate country-year observations were found within either currency subset.

## Default-year policy

The build does **not** blindly use the numerically latest year.

A year is eligible as the default only when:

1. at least 150 registry countries have a value; and
2. all configured required countries have a value.

The latest eligible year is selected.

With the September 2026 source state this yields:

```text
defaultYear = 2024
```

for both indicators.

This is intentional. ILOSTAT already contains some 2025 and 2026 observations, but those years are still much too sparse for a useful worldwide default map. They remain available in the time series and automatically become candidates for the default once coverage becomes sufficiently broad.

A maximum default-year age guard additionally prevents the pipeline from silently accepting a stale source.

## Fixed classifications

The production maps use stable rounded class boundaries rather than recalculating quantiles from every source update.

PPP dollars per month:

```text
150, 300, 600, 1000, 1500, 2500
```

Nominal US dollars per month:

```text
50, 100, 200, 400, 800, 1600
```

The boundaries were selected after inspecting the 2024 distribution. They provide useful separation across the current global range while remaining simple enough to retain a consistent meaning over time.

For reference, the audited 2024 medians were about 626 PPP dollars per month and 308 nominal US dollars per month.

## Relationship to Eurostat

Eurostat already provides regional minimum-wage indicators in EUR and PPS for participating European countries. Those series remain visible.

The ILOSTAT and Eurostat series are **not merged observation by observation** and neither is used as a fallback for the other. They have different geographic scope, source systems and harmonisation rules. Provider identity therefore remains part of the statistical meaning.

For users comparing countries worldwide, the ILOSTAT PPP series is the preferred global view. For EU-focused analysis, the Eurostat EUR/PPS series remains useful as the regional source.

## Provenance and update strategy

The build downloads the current ILOSTAT table directly from the ILOSTAT API at build time. It records the table id, underlying indicator id, selected currency classification and API URL in each generated indicator payload.

The provider is rebuilt monthly and can also be rebuilt manually. The produced snapshot is content-addressed. Production deployment keeps the same validation pattern as the other country-statistics providers: build validation, browser CORS check and public byte comparison after deployment.

ILOSTAT data are attributed to the International Labour Organization under the source metadata and licence information shipped with the provider.
