# IMF CPI source policy

## Canonical source

The country indicator `inflation.cpi-annual-percent` is sourced directly from the International Monetary Fund (IMF) Consumer Price Index (CPI) SDMX dataflow.

The production series is:

- dataflow: `IMF.STA:CPI`
- index type: `CPI`
- COICOP aggregate: `_T` (all items)
- transformation: `YOY_PCH_PA_PT`
- frequency: `A` (annual)
- source indicator key: `CPI._T.YOY_PCH_PA_PT.A`
- source rows must carry `IFS_FLAG=true`

The values are taken directly from the IMF annual percentage-change series. The builder does **not** calculate inflation from the CPI index.

## Country-code mapping

The production country registry uses ISO3-style codes `XKX` and `PSE`, while the IMF CPI dataflow currently uses:

- `KOS` → `XKX`
- `WBG` → `PSE`

These are explicit source aliases. The audit found no other unmapped IMF country codes in the selected annual series.

## Time range

The IMF source contains observations before 1960. The migrated indicator deliberately retains `1960` as its first published year so that replacing the former World Bank WDI series does not also change the visible historical time range.

This is a product-compatibility boundary, not a limitation of the IMF source. It can be revisited separately if older CPI history is wanted later.

## Relationship to World Bank WDI

The former source was World Bank WDI indicator `FP.CPI.TOTL.ZG` (`Inflation, consumer prices (annual %)`). WDI identifies IMF International Financial Statistics among the underlying sources, but WDI is an aggregator and can contain older snapshots, revisions or additional country observations.

A production-registry audit on 13 September 2026 compared the direct IMF annual series with WDI:

- direct IMF observations: 5,544 before the 1960 product cutoff, covering 199 registry areas
- WDI observations in the comparison: 9,136 across 193 registry areas
- overlapping country-years: 5,267
- exactly equal within `1e-12`: 4,375
- within `0.0001` percentage points: 4,964
- within `0.01` percentage points: 5,202
- within `0.1` percentage points: 5,262
- median absolute difference: approximately `2.1e-14` percentage points

Recent coverage is better in the direct IMF series. For 2025 the audit found 174 IMF country values versus 165 WDI values.

The five overlapping observations differing by more than 0.1 percentage points were:

- Djibouti 2013
- Brunei 2016
- Brunei 2017
- Brunei 2018
- Netherlands 1996

The audit checked IMF reference-period and overlap metadata around these observations and found no index-break change. They are therefore treated as source/revision differences rather than evidence that the direct IMF annual series is semantically wrong.

## Transformation audit

The current IMF CPI dataflow exposes both `POP_PCH_PA_PT` and `YOY_PCH_PA_PT` at annual frequency. Across all 5,544 audited observations the two annual series were bit-for-bit identical.

`YOY_PCH_PA_PT` is used in production because its code states the intended year-on-year percentage-change semantics explicitly.

## No WDI fallback

The IMF provider remains source-pure. Missing IMF observations are left missing rather than filled from World Bank WDI. This avoids mixing differently revised source snapshots inside one time series.

The WDI duplicate `FP.CPI.TOTL.ZG` is removed from the visible World Bank provider once the direct IMF provider is adopted.

## Source and usage terms

Primary references:

- IMF CPI dataset: `https://data.imf.org/en/Datasets/CPI`
- IMF Data API: `https://data.imf.org/en/Resource-Pages/IMF-API`
- IMF copyright and data-usage terms: `https://www.imf.org/en/about/copyright-and-terms`

IMF Data API documentation explicitly supports importing IMF datasets into data systems and applications. IMF statistical-data terms permit downloading, extracting, creating derivative works, publishing and distributing IMF Data subject to attribution and the stated usage conditions. The provider therefore records IMF attribution and links to the IMF Data Usage Terms rather than presenting the data under a Creative Commons licence.
