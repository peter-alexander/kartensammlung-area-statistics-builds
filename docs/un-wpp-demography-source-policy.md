# UN WPP demography source policy

## Canonical source

For core demographic statistics, the canonical source is **United Nations, Department of Economic and Social Affairs, Population Division — World Population Prospects 2024 (WPP 2024)**.

The project already builds the direct UN WPP bulk downloads under provider `un-wpp` and explicitly distinguishes estimates from projections:

- estimates: 1950–2023
- projections: 2024–2100
- projection variant: Medium
- default year: 2023, the latest estimate year

The direct UN WPP provider remains source-pure. World Bank WDI values are not merged into projection years because doing so would mix differently sourced values with explicitly labelled UN projections.

## WDI duplicates removed

The following visible World Development Indicators duplicates are removed from `config/world-bank-indicators.json`:

- `SP.POP.TOTL` — population
- `SP.DYN.LE00.IN` — life expectancy at birth
- `SP.DYN.TFRT.IN` — total fertility rate

WDI metadata identifies these series as mixed-source products drawing on UN World Population Prospects as well as national statistical offices and, where applicable, Eurostat and other sources. They are therefore not identical redistributions of the direct UN WPP series.

The existing UN WPP indicator IDs are retained for compatibility. In particular, total fertility remains `fertility.total-rate`; it is not renamed to the former WDI ID.

## Source audit — 13 September 2026

The official WPP 2024 compact demographic CSV was compared with the three WDI series using the production country registry and ISO3 mapping.

All WPP `Country/Area` records mapped successfully: 237 countries/areas, with annual estimate values from 1950 through 2023. WPP projection rows after 2023 were deliberately excluded from the numerical comparison.

### Population

- WPP estimates: 17,538 observations, 237 areas, 1950–2023
- WDI: 14,226 observations, 216 areas, 1960–2025
- overlap: 13,794 country-years
- exact matches: 8,525
- WPP-only: 3,744
- WDI-only: 432
- maximum absolute difference: 20,008,528 persons

### Life expectancy at birth

- WPP estimates: 17,538 observations, 237 areas, 1950–2023
- WDI: 14,006 observations, 216 areas, 1960–2024
- overlap: 13,790 country-years
- within 0.01 year: 10,415
- WPP-only: 3,748
- WDI-only: 216
- maximum absolute difference: about 5.94 years

### Total fertility rate

- WPP estimates: 17,538 observations, 237 areas, 1950–2023
- WDI: 14,008 observations, 216 areas, 1960–2024
- overlap: 13,792 country-years
- within 0.01 birth per woman: 12,398
- WPP-only: 3,746
- WDI-only: 216
- maximum absolute difference: about 0.573 births per woman

The overlap is often close, but material historical differences exist. Therefore the project does not silently substitute WDI values for direct WPP values.

## Primary references

- UN World Population Prospects: https://population.un.org/wpp/
- WPP 2024 compact demographic bulk data: https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/CSV_FILES/WPP2024_Demographic_Indicators_Medium.csv.gz
- World Bank WDI population `SP.POP.TOTL`: https://data.worldbank.org/indicator/SP.POP.TOTL
- World Bank WDI life expectancy `SP.DYN.LE00.IN`: https://data.worldbank.org/indicator/SP.DYN.LE00.IN
- World Bank WDI fertility `SP.DYN.TFRT.IN`: https://data.worldbank.org/indicator/SP.DYN.TFRT.IN
