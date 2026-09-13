# Tax revenue source policy

## Scope

The Kartensammlung publishes OECD general-government tax statistics and a deliberately separate World Bank WDI tax-revenue indicator because the available worldwide sources use materially different government and revenue concepts.

The OECD provider also publishes selected harmonized tax-structure categories from the same Global Revenue Statistics dataflow.

OECD and WDI values must not be merged, spliced or used as fallbacks for each other.

## 1. OECD: general-government taxes and contributions

Canonical source:

- provider: OECD
- dataset: Global Revenue Statistics
- SDMX dataflow: `OECD.CTP.TPS:DSD_REV_COMP_GLOBAL@DF_RSGLOBAL(2.1)`
- measure: `TAX_REV`
- sector: `S13` (general government)
- unit: `PT_B1GQ` (percent of GDP)
- frequency: annual
- production start year: 1990

The OECD concept covers government as a whole, across all levels of government. Compulsory social security contributions paid to general government are treated as taxes.

### Total tax and contribution burden

- revenue code: `TOTALTAX`
- standard-revenue selector: `_T`
- id: `fiscal.tax-and-social-contributions-percent-gdp`
- title: `Steuer- und Abgabenquote`

The September 2026 live audit mapped 142 Kartensammlung country areas over 1990-2024. Coverage was 141 countries in every year from 2015 through 2023 and 128 countries in 2024. India is not present in this OECD Global Revenue Statistics series and is therefore not fabricated or filled from another provider.

### Tax-structure indicators

Five additional indicators use the same general-government dataflow and the same percent-of-GDP unit:

| OECD revenue code | Production id | Map title |
| --- | --- | --- |
| `1100` | `fiscal.personal-income-taxes-percent-gdp` | Einkommensteuern von Privatpersonen |
| `1200` | `fiscal.corporate-income-taxes-percent-gdp` | Unternehmenssteuern |
| `2000` | `fiscal.social-security-contributions-percent-gdp` | Sozialversicherungsbeiträge |
| `4000` | `fiscal.property-taxes-percent-gdp` | Steuern auf Vermögen und Eigentum |
| `5111` | `fiscal.vat-percent-gdp` | Mehrwertsteuer-Einnahmen |

The September 2026 direct-source audit found:

- personal income taxes: 136 mapped countries overall; 124 in 2024;
- corporate income taxes: 137 mapped countries overall; 124 in 2024;
- compulsory social security contributions: 127 mapped countries overall; 112 in 2024;
- taxes on property: 139 mapped countries overall; 128 in 2024;
- VAT: 140 mapped countries overall; 126 in 2024.

All five series cover 1990-2024 in the current source. India is absent from these OECD series as well and remains missing.

### Zero and negative values are observations

The OECD files contain genuine zero values. They are retained exactly and are never interpreted as missing data. This matters particularly for:

- VAT: the United States has `0` in 2024 because the OECD VAT category does not substitute state and local sales taxes for VAT;
- social security contributions: some countries report zero compulsory contributions under this category.

The corporate-income-tax series also contains a small number of genuine negative source values in historical observations. They are retained rather than clamped to zero.

No interpolation or extrapolation is applied.

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

## Why OECD and WDI are not fallbacks for each other

The numerical audit confirms the conceptual difference. Across 2,839 overlapping country-years the median absolute difference was about 6.21 percentage points of GDP. Examples from 2024:

- Germany: OECD 38.02%, WDI 10.89%
- Austria: OECD 43.37%, WDI 25.78%
- United States: OECD 25.62%, WDI 10.77%
- Brazil: OECD 33.68%, WDI 15.41%

These are not ordinary source discrepancies. They reflect different coverage of government levels and different treatment of compulsory social security contributions.

Accordingly:

- no OECD value is used to fill a WDI gap;
- no WDI value is used to fill an OECD gap;
- India remains missing from OECD indicators even where WDI has values;
- users can select the indicators separately and see their definitions in the metadata.

## Fixed map classes

The fixed boundaries are based on the September 2026 audit of the full historical distributions plus the 2023 and 2024 cross-sections. They are not recalculated automatically when OECD updates the source.

- total tax and contributions: `10 / 15 / 20 / 25 / 30 / 40 %`
- personal income taxes: `0.5 / 1 / 2 / 4 / 8 / 12 %`
- corporate income taxes: `0 / 1 / 2 / 3 / 5 / 7 %`
- social security contributions: `0.5 / 2 / 4 / 7 / 10 / 14 %`
- taxes on property: `0.1 / 0.25 / 0.5 / 1 / 2 / 3 %`
- VAT: `1 / 3 / 5 / 7 / 9 / 11 %`
- WDI tax revenue: `5 / 10 / 15 / 20 / 25 / 30 %`

The OECD distribution audit showed, for example, 2024 medians of approximately 3.24% of GDP for personal income taxes, 3.23% for corporate income taxes, 2.86% for social security contributions, 0.42% for property taxes and 6.09% for VAT.

## Update strategy

Both source families are rebuilt from their direct upstream APIs. The OECD provider makes one combined SDMX request for the total series and five tax-structure categories, then strictly validates each row against its expected category code and common dimensions before publishing separate indicator payloads.

The WDI indicator uses the established World Bank provider pipeline and its broad-coverage default-year policy.

Neither source family is interpolated or extrapolated.
