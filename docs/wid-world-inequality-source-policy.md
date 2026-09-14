# WID.world source policy

## Scope

The `wid-world-inequality` provider publishes eight country-level distribution indicators from the World Inequality Database (WID.world):

- pre-tax national income shares for the bottom 50%, middle 40%, top 10% and top 1%;
- net-wealth shares for the bottom 50%, middle 40%, top 10% and top 1%.

All eight series use WID Equal-Split Adults aged 20+ (`992j`). Resources of couples are split equally between both adults by the WID population concept. WID fractions are converted to percentages by the builder.

## Source and client pinning

Production data are downloaded through the official WID R client from the WID API. The client is installed from the audited Git commit recorded in `config/wid-world-inequality-indicators.json`, rather than from an unpinned moving package release.

The build validates the client version and API signature before accepting data. A client/API change therefore fails closed until it has been reviewed.

## Time-series policy

The complete annual series published by WID.world are retained. The build does not impose an arbitrary modern start year such as 1980.

WID harmonizes distributional series across sources and may use imputations, interpolation and extrapolation. These modeled observations are part of the published WID series. The Kartensammlung does not create additional interpolated, extrapolated or fallback values of its own.

An audit of the official WID R client compared these eight target series with `include_extrapolations=TRUE` and `include_extrapolations=FALSE`. The switch removed no observations from the target data. It therefore cannot be used as a general filter for every modeled observation already contained in the harmonized published series.

The default map year is the newest year that satisfies the configured coverage threshold and contains all required audit countries. This allows the default year to advance automatically when WID publishes a sufficiently complete newer year.

## Country mapping

Country matching is deterministic and code-based. Fuzzy name matching is not used.

The current registry contains 250 country areas. The WID country list has 232 direct ISO2 overlaps with that registry. Kosovo is the one explicit alias needed for the target series: WID publishes these observations under `KS`, while the registry uses `XK` / `XKX`. The production query therefore requests the 232 direct country codes plus `KS`.

Namibia is explicitly asserted because its ISO2 code `NA` can be misinterpreted as a missing value by statistical software. The CSV parser is configured so `NA` remains the literal Namibia code.

The audited 2024 coverage is at least 216 registry countries for every target indicator after the Kosovo mapping.

## Data-quality field

WID bulk country files expose a `data_quality` field with values from 0 to 5. WID documents these as quality grades, broadly from lower to higher quality, but the detailed interpretation depends on the series and underlying source construction.

No observations are removed merely because their quality grade is 0. The earlier prototype that filtered quality-0 rows was rejected after the source audit. The production API path does not expose this field in a form that is suitable for attaching a stable row-level quality flag to every published observation, so the current normalized output does not present it as a per-value quality score.

## Mathematical validation

For every comparable country-year, the builder validates that:

- bottom 50% + middle 40% + top 10% is approximately 100%;
- the top-1% share does not exceed the top-10% share.

Negative bottom-50 wealth shares are valid. They occur when debts of the group exceed its assets, and must not be clipped to zero. South Africa's negative 2024 bottom-50 wealth share is retained as an explicit regression check.

## Licensing and attribution

WID.world describes its downloadable datasets as open-access data. During the source audit no named data license such as CC BY or ODbL was identified for these data.

The provider therefore uses the deliberately conservative wording `Open-Access-Daten` and attribution `WID.world – World Inequality Database`. It does not claim a Creative Commons license that WID has not stated for the dataset.
