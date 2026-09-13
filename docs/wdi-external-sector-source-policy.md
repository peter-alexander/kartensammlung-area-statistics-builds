# WDI external-sector source policy

## Scope

Three external-sector indicators intentionally remain in the World Bank WDI provider after a direct-source audit against the current IMF Balance of Payments (BOP) SDMX dataflow:

- `trade.current-account-balance-percent-gdp` → WDI `BN.CAB.XOKA.GD.ZS`
- `investment.fdi-net-inflows-percent-gdp` → WDI `BX.KLT.DINV.WD.GD.ZS`
- `investment.fdi-net-outflows-percent-gdp` → WDI `BM.KLT.DINV.WD.GD.ZS`

This is a deliberate source-policy decision, not an unfinished migration.

The audit used the production country registry with 250 country areas and the current IMF SDMX 3.0 BOP dataflow:

- dataflow: `IMF.STA:BOP(21.0.0)`
- data structure: `IMF.STA:DSD_BOP(24.0.0)`
- data API: `https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/BOP/21.0.0`

The BOP series key consists of:

`COUNTRY.BOP_ACCOUNTING_ENTRY.INDICATOR.UNIT.FREQUENCY`

## Current-account balance

The direct annual IMF BOP numerator is:

`*.NETCD_T.CAB.USD.A`

where:

- `NETCD_T` = net credits less debits;
- `CAB` = current-account balance;
- `USD` = US dollars;
- `A` = annual frequency.

The IMF dataflow does not expose an annual percent-of-GDP variant of this series. The Kartensammlung indicator is therefore not obtainable from IMF BOP alone.

World Bank metadata for `BN.CAB.XOKA.GD.ZS` identifies the source organizations as:

- IMF Balance of Payments Statistics;
- World Bank World Development Indicators;
- OECD national accounts data.

This is consistent with the indicator being a ratio whose current-account numerator and GDP denominator can come from different source systems.

### Value audit

For the audit, the direct IMF BOP USD numerator was divided by WDI `NY.GDP.MKTP.CD` for the same country and year and multiplied by 100.

Registry-mapped coverage was:

| Series | Observations | Areas | Years | 2021 | 2022 | 2023 | 2024 | 2025 |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| IMF BOP current account, USD | 7,897 | 200 | 1948–2025 | 182 | 181 | 181 | 168 | 134 |
| IMF BOP / WDI GDP, derived % | 7,717 | 198 | 1960–2025 | 179 | 178 | 178 | 165 | 131 |
| WDI current account, % GDP | 7,715 | 200 | 1960–2025 | 181 | 180 | 179 | 165 | 97 |

There were 7,658 overlapping country-years between the derived series and WDI:

| Absolute difference | Matching observations |
| --- | ---: |
| ≤ `1e-9` percentage points | 7,411 / 7,658 = 96.77% |
| ≤ `0.01` pp | 7,458 / 7,658 = 97.39% |
| ≤ `0.1` pp | 7,544 / 7,658 = 98.51% |
| ≤ `0.5` pp | 7,608 / 7,658 = 99.35% |
| ≤ `1.0` pp | 7,627 / 7,658 = 99.60% |

The median absolute difference was zero and the mean absolute difference was approximately `0.01675 pp`. Austria and India reproduced the WDI ratio essentially exactly through 2024; recent differences for some countries demonstrate that numerator and/or denominator vintages are not always identical.

### Decision

The numerical audit strongly confirms the IMF BOP lineage, but replacing WDI would not create a genuinely direct single-source indicator. It would create a new Kartensammlung composite with:

- IMF BOP as numerator;
- World Bank GDP as denominator;
- potentially different revision timing from WDI/OECD GDP inputs.

That adds cross-provider coupling and reconstruction logic while retaining a World Bank dependency. The current WDI ratio therefore remains the preferred production source.

A future direct IMF-BOP indicator in **absolute USD** would be a different indicator and can be considered separately; it would not replace the existing percent-of-GDP series.

## FDI net inflows and outflows

The current IMF BOP dataflow exposes annual direct-investment flows under the asset/liability presentation:

- inward-side candidate: `*.L_NIL_T.D_F.USD.A`
  - `L_NIL_T` = liabilities, net incurrence of liabilities;
  - `D_F` = direct investment, total financial assets/liabilities.
- outward-side candidate: `*.A_NFA_T.D_F.USD.A`
  - `A_NFA_T` = assets, net acquisition of financial assets;
  - `D_F` = direct investment, total financial assets/liabilities.

The IMF accounting-entry codelist also defines directional concepts:

- `NI` = Net FDI inward;
- `NO` = Net FDI outward.

However, direct probes of both country-specific and all-country annual USD queries returned **zero observations** for `NI` and `NO` in the current `BOP(21.0.0)` dataflow. These codelist entries therefore cannot be used as production series today.

### WDI lineage

World Bank metadata confirms that the WDI FDI indicators are not simple republishes of one IMF BOP series.

For `BX.KLT.DINV.WD.GD.ZS` (net inflows), WDI names:

- IMF International Financial Statistics and Balance of Payments databases;
- World Bank International Debt Statistics;
- World Bank GDP estimates;
- OECD GDP estimates.

For `BM.KLT.DINV.WD.GD.ZS` (net outflows), WDI explicitly states that IMF Balance of Payments data are supplemented by:

- UNCTAD;
- official national sources.

The WDI definitions describe net investment **into the reporting economy from foreign investors** and net investment **from the reporting economy to the rest of the world**. Those directional concepts are not interchangeable with the available IMF BOP asset/liability accounting entries for every economy and year.

### Inflow comparison

Registry-mapped coverage:

| Series | Observations | Areas | Years | 2021 | 2022 | 2023 | 2024 | 2025 |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| IMF `L_NIL_T.D_F`, USD | 7,836 | 199 | 1948–2025 | 182 | 181 | 181 | 168 | 134 |
| IMF / WDI GDP, derived % | 7,656 | 197 | 1960–2025 | 179 | 178 | 178 | 165 | 131 |
| WDI FDI inflows, % GDP | 9,306 | 202 | 1970–2025 | 196 | 195 | 195 | 192 | 97 |

Among 7,543 overlapping country-years:

- 93.11% matched within `1e-9 pp`;
- 94.39% within `0.01 pp`;
- 96.34% within `0.1 pp`;
- 98.69% within `1 pp`.

The median absolute difference was zero, but the mean was approximately `1.47 pp` because several economies showed very large conceptual differences. Luxembourg in 2015, for example, produced approximately `1103.44%` from the IMF liability-flow candidate versus `75.63%` in WDI.

WDI also contained 1,763 country-years absent from the derived direct candidate, spanning 157 areas. The direct candidate therefore does not reproduce WDI's broader supplemented series.

### Outflow comparison

Registry-mapped coverage:

| Series | Observations | Areas | Years | 2021 | 2022 | 2023 | 2024 | 2025 |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| IMF `A_NFA_T.D_F`, USD | 7,331 | 198 | 1948–2025 | 174 | 171 | 171 | 160 | 133 |
| IMF / WDI GDP, derived % | 7,161 | 196 | 1960–2025 | 171 | 168 | 168 | 157 | 130 |
| WDI FDI outflows, % GDP | 7,299 | 197 | 1970–2025 | 174 | 172 | 170 | 170 | 91 |

Among 6,531 overlapping country-years:

- 89.71% matched within `1e-9 pp`;
- 91.85% within `0.01 pp`;
- 95.59% within `0.1 pp`;
- 98.35% within `1 pp`.

Again, the median difference was zero but large financial-centre differences show that the available IMF asset-flow series is not a safe semantic substitute. Luxembourg in 2015 produced approximately `1235.62%` from the direct candidate versus `53.14%` in WDI.

For 2024, WDI also had materially broader coverage: 170 countries versus 157 for the direct derived candidate.

### Decision

The two WDI FDI indicators remain in WDI because a direct migration would fail at least two source-policy requirements:

1. **Semantic equivalence is not assured.** The available IMF BOP asset/liability series is not identical to WDI's directional net-inflow/net-outflow concept for all economies, while the IMF `NI`/`NO` directional entries currently contain no observations in the audited dataflow.
2. **Coverage would regress.** WDI deliberately supplements IMF data with World Bank, UNCTAD and national sources and has substantially broader coverage in important years.

The direct IMF asset/liability series may be useful as separate financial-account indicators in the future, but they must not replace the existing WDI FDI indicators under the same IDs.

## Consequence for future source audits

These three WDI indicators should not be proposed again for a simple direct IMF-BOP migration unless the upstream situation materially changes.

Reopen the audit if one of the following occurs:

- IMF BOP begins publishing populated annual `NI` and `NO` directional FDI series with broad country coverage;
- IMF adds direct percent-of-GDP variants with clearly documented semantics;
- WDI changes its source construction materially;
- a canonical global FDI source offers the WDI directional concept with equal or better coverage under compatible redistribution terms;
- the project decides to add absolute BOP/FDI USD indicators as new metrics rather than replacements.

Until then:

- `BN.CAB.XOKA.GD.ZS` remains the canonical production source for current-account balance as a percentage of GDP;
- `BX.KLT.DINV.WD.GD.ZS` remains canonical for FDI net inflows as a percentage of GDP;
- `BM.KLT.DINV.WD.GD.ZS` remains canonical for FDI net outflows as a percentage of GDP.
