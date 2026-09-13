# Tax revenue source policy

## Scope

The Kartensammlung publishes two deliberately separate country indicators for taxation because the available worldwide sources use materially different government and revenue concepts.

They must not be merged, spliced or used as fallbacks for each other.

## 1. OECD: tax and compulsory social contributions, general government

Canonical source:

- provider: OECD
- dataset: Global Revenue Statistics
- SDMX dataflow: `OECD.CTP.TPS:DSD_REV_COMP_GLOBAL@DF_RSGLOBAL(2.1)`
- measure: `TAX_REV`
- sector: `S13` (general government)
- revenue code: `TOTALTAX`
- unit: `PT_B1GQ` (percent of GDP)
- frequency: annual
- production start year: 1990

Production indicator:

- id: `fiscal.tax-and-social-contributions-percent-gdp`
- title: `Steuer- und Abgabenquote`

The OECD concept covers government as a whole, across all levels of government. Compulsory social security contributions paid to general government are treated as taxes. This makes it the preferred harmonized indicator for the broad tax burden where OECD Global Revenue Statistics has coverage.

The September 2026 live audit mapped 142 Kartensammlung country areas over 1990-2024. Coverage was 141 countries in every year from 2015 through 2023 and 128 countries in 2024. India is not present in this OECD Global Revenue Statistics series and is therefore not fabricated or filled from another provider.

## 2. World Bank WDI / IMF GFS: tax revenue

Canonical source:

- provider: World Bank World Development Indicators
- indicator: `GC.TAX.TOTL.GD.ZS`
- primary source: IMF Government Finance Statistics Yearbook and data files
- unit: percent of GDP

Production indicator:

- id: `fiscal.tax-revenue-percent-gdp`
- title: `Steuereinnahmen des Staates`

This is a narrower concept. World Bank metadata describes compulsory transfers to central government for public purposes and notes that most social security contributions are excluded. For many countries the source is consolidated central government, while others report only budgetary central government. In federal states this can omit substantial subnational government activity.

The September 2026 live audit mapped 161 Kartensammlung countries over 1972-2024. Recent annual coverage declines from 146 countries in 2015 to 128 in 2021, 118 in 2022, 111 in 2023 and 89 in 2024. The ordinary WDI broad-coverage default-year rule therefore selects a sufficiently complete year rather than blindly selecting the sparsest latest year.

## Why the two series are not fallbacks for each other

The numerical audit confirms the conceptual difference. Across 2,839 overlapping country-years the median absolute difference was about 6.21 percentage points of GDP. Examples from 2024:

- Germany: OECD 38.02%, WDI 10.89%
- Austria: OECD 43.37%, WDI 25.78%
- United States: OECD 25.62%, WDI 10.77%
- Brazil: OECD 33.68%, WDI 15.41%

These are not ordinary source discrepancies. They reflect different coverage of government levels and different treatment of compulsory social security contributions.

Accordingly:

- no OECD value is used to fill a WDI gap;
- no WDI value is used to fill an OECD gap;
- India remains missing from the OECD indicator even though WDI has values;
- users can select the two indicators separately and see their definitions in the metadata.

## Fixed map classes

OECD tax and compulsory social contributions, percent of GDP:

`10 / 15 / 20 / 25 / 30 / 40 %`

WDI tax revenue, percent of GDP:

`5 / 10 / 15 / 20 / 25 / 30 %`

These boundaries are fixed so that map colours remain comparable between years.

## Update strategy

Both series are rebuilt from their direct upstream APIs. The OECD provider validates the exact SDMX dimensions before publishing. The WDI indicator uses the established World Bank provider pipeline and its broad-coverage default-year policy.

Neither series is interpolated or extrapolated.
