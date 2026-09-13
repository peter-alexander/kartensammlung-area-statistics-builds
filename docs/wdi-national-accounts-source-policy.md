# WDI national-accounts source policy

## Scope

Eleven national-accounts and trade indicators intentionally remain in the World Bank World Development Indicators (WDI) provider after a direct-source audit against the United Nations Statistics Division (UNSD) National Accounts Main Aggregates Database / *Analysis of Main Aggregates* (AMA):

- `gdp.current-usd` → WDI `NY.GDP.MKTP.CD`
- `gdp-per-capita.current-usd` → WDI `NY.GDP.PCAP.CD`
- `gni.current-usd` → WDI `NY.GNP.MKTP.CD`
- `gni-per-capita.atlas-current-usd` → WDI `NY.GNP.PCAP.CD`
- `trade.exports-current-usd` → WDI `NE.EXP.GNFS.CD`
- `trade.imports-current-usd` → WDI `NE.IMP.GNFS.CD`
- `trade.external-balance-current-usd` → WDI `NE.RSB.GNFS.CD`
- `trade.external-balance-percent-gdp` → WDI `NE.RSB.GNFS.ZS`
- `trade.openness-percent-gdp` → WDI `NE.TRD.GNFS.ZS`
- `trade.exports-percent-gdp` → WDI `NE.EXP.GNFS.ZS`
- `trade.imports-percent-gdp` → WDI `NE.IMP.GNFS.ZS`

This is a deliberate source-policy decision, not an unfinished migration.

The audit was performed on 13 September 2026 against the current production country registry and the UNSD AMA data upload published in January 2026.

## Why UNSD AMA was audited

UNSD is the specialist United Nations body for national accounts and annually collects official national-accounts statistics from Member States through a questionnaire based on the System of National Accounts (SNA).

The AMA database publishes a complete and consistent set of main national-account aggregates from 1970 onward for more than 200 countries and areas. Its current downloadable files include, among other series:

- GDP and its expenditure breakdown at current prices in US dollars;
- GDP per capita in current US dollars;
- GNI at current prices in US dollars.

The GDP expenditure workbook also directly contains exports and imports of goods and services. The external balance and the four GDP-ratio indicators can therefore be derived from the same internally consistent UNSD GDP/export/import observations.

The audit used the public AMA workbook API:

- GDP and expenditure breakdown, current USD: `https://unstats.un.org/unsd/amaapi/api/file/2`
- GDP per capita, current USD: `https://unstats.un.org/unsd/amaapi/api/file/9`
- GNI, current USD: `https://unstats.un.org/unsd/amaapi/api/file/24`

The production registry already carries numeric M49 codes, so normal UNSD countries can be mapped by code instead of country-name heuristics. Kosovo is the only special production case: AMA uses its own `412` code while the Kartensammlung registry uses `XKX` without a standard UN M49 code.

Historical former states and sub-country components in AMA were intentionally not mapped to present-day production countries.

## AMA is not a single original-source series

The source audit initially considered moving the ten semantically comparable indicators to UNSD AMA and retaining WDI only as a fallback.

That would not improve the source chain in the way that a migration from a distributor to a genuine original source does.

UNSD describes AMA as a harmonized global series built from:

1. official annual national-accounts statistics collected from countries;
2. secondary sources;
3. UNSD estimates where official data are incomplete or inconsistent.

Country-specific AMA metadata confirms that the secondary-source and estimation layer can itself include sources such as:

- World Bank World Development Indicators;
- IMF World Economic Outlook;
- OECD national accounts;
- UNSD National Accounts Database official data;
- UNSD-derived interpolation, backward extrapolation and other estimation procedures.

Consequently, the unusually complete AMA coverage in recent years is not equivalent to having an official observed national value for every country. In some economies, recent AMA observations are estimates constructed from other international databases.

WDI is likewise a global compilation rather than a single original-source series. Its current metadata for these indicators identifies combinations of official country statistics, national statistical offices and central banks, OECD national accounts and World Bank staff estimates.

The correct comparison is therefore between two independent international compilation/harmonization products, not between an original source and a redundant distributor.

## Numerical audit

The audit mapped both databases to the same production country registry and excluded WDI observations marked as forecasts.

### GDP and GNI

| Indicator | UNSD AMA | WDI | Overlap | Median difference | 2024 median difference |
| --- | --- | --- | ---: | ---: | ---: |
| GDP, current USD | 10,845 obs; 210 areas; 1970–2024 | 11,739 obs; 213 areas; 1960–2025 | 10,049 | 0.75% relative | 0.428% relative |
| GDP per capita, current USD | 10,845 obs; 210 areas; 1970–2024 | 11,739 obs; 213 areas; 1960–2025 | 10,049 | 1.520% relative | 1.189% relative |
| GNI, current USD | 10,845 obs; 210 areas; 1970–2024 | 11,208 obs; 208 areas; 1960–2025 | 9,694 | 1.582% relative | 1.364% relative |

Recent coverage illustrates the different strengths of the products:

| Indicator | AMA 2024 | WDI 2024 | WDI 2025 |
| --- | ---: | ---: | ---: |
| GDP | 210 | 200 | 186 |
| GDP per capita | 210 | 200 | 186 |
| GNI | 210 | 198 | 182 |

AMA therefore has denser coverage in the last complete year, while WDI provides a longer history and already publishes substantial 2025 coverage.

The overlap is not a simple rounded copy. Historical differences can be very large, especially around currency changes, conflict periods and reconstructed time series. Examples include Iraq in the early 1990s, Azerbaijan in 1992 and Guinea in 1985.

Those differences are consistent with two independently revised global compilation systems and are a reason not to silently replace one historical series with the other under the same indicator IDs.

### Exports and imports

| Indicator | UNSD AMA | WDI | Overlap | Median difference | 2024 median difference |
| --- | --- | --- | ---: | ---: | ---: |
| Exports, current USD | 10,845 obs; 210 areas; 1970–2024 | 9,045 obs; 194 areas; 1960–2025 | 8,012 | 0.0891% relative | 0.4266% relative |
| Imports, current USD | 10,845 obs; 210 areas; 1970–2024 | 9,054 obs; 194 areas; 1960–2025 | 8,013 | 0.0886% relative | 0.3361% relative |

For both direct trade aggregates AMA has 210 mapped countries in 2024. WDI has 171 in 2024 and 138 already available in 2025.

The median recent differences are small, but the full history again contains material differences. WDI also contains historical observations outside AMA's 1970-starting time range.

### Derived external-balance and trade-share indicators

For the audit, AMA ratios were reconstructed only from internally consistent AMA components for the same country and year:

- external balance = exports − imports;
- external balance % GDP = `(exports − imports) / GDP × 100`;
- trade % GDP = `(exports + imports) / GDP × 100`;
- exports % GDP = `exports / GDP × 100`;
- imports % GDP = `imports / GDP × 100`.

| Indicator | Overlap | Median difference | 2024 median difference |
| --- | ---: | ---: | ---: |
| External balance, current USD | 8,012 | 0.2325% relative | 3.861% relative |
| External balance, % GDP | 8,006 | 0.00147 percentage points | 0.2603 pp |
| Trade, % GDP | 8,006 | 0.00471 pp | 0.5671 pp |
| Exports, % GDP | 8,006 | 0.00228 pp | 0.2487 pp |
| Imports, % GDP | 8,007 | 0.00214 pp | 0.2953 pp |

The low medians conceal significant outliers. Historical external-balance values can even differ in sign for individual country-years. Large percentage-point discrepancies also occur for economies affected by major historical reconstruction or exceptional national-account conditions.

Replacing WDI by a Kartensammlung-derived AMA ratio would therefore create a materially different harmonized series, not simply recover the same WDI value from a more direct upstream source.

## GNI per capita: Atlas method is intrinsically World Bank methodology

`NY.GNP.PCAP.CD` is not semantically equivalent to AMA's ordinary GNI per capita at current US-dollar exchange rates.

The WDI indicator explicitly applies the World Bank Atlas method. The Atlas conversion smooths exchange-rate movements over a three-year period and adjusts for inflation differences before dividing GNI by population.

AMA's downloadable `Per Capita GNI at current prices in US Dollars` is an ordinary current-USD conversion and must not replace an indicator whose title and description promise the Atlas method.

Current mapped coverage is:

- AMA ordinary current-USD GNI per capita: 10,845 observations, 210 areas, 1970–2024;
- WDI Atlas-method GNI per capita: 10,619 observations, 207 areas, 1962–2025.

No numerical migration test was used for this row because the definitions are intentionally different.

Decision: `NY.GNP.PCAP.CD` remains a World-Bank-specific canonical indicator.

## Coverage and default-year consequence

The Kartensammlung WDI builder does not automatically use the numerically newest year as the default year. A year must reach the configured broad-coverage threshold, currently 75% of all areas that have any observation for that indicator.

This already protects the UI from selecting a sparse new WDI year merely because it exists.

Examples from the audited current data:

- GDP/GDP per capita: WDI 2025 has 186 mapped areas and can legitimately qualify as a broadly covered newest year;
- exports/imports: WDI 2025 has only 138 mapped areas, so the broad-coverage rule can retain an earlier, more complete year as the default.

A separate AMA provider would therefore not be necessary merely to obtain a sensible default year.

## Redistribution

The AMA downloads are publicly and freely available. UNdata's published terms allow data and metadata to be copied, duplicated and further distributed provided UNdata is cited as the reference.

Redistribution was therefore not the reason against migration. The decision is based on provenance, semantics, revision behavior, history and update coverage.

## Decision

All eleven audited indicators remain in the World Bank WDI provider.

For the ten semantically comparable GDP/GNI/trade indicators, WDI remains canonical because:

1. **UNSD AMA is not a uniformly more direct original source.** It is itself a global compilation that can incorporate WDI, IMF WEO, OECD, official national data and UNSD estimates depending on country and period.
2. **WDI has materially longer history.** The relevant WDI series reach into the 1960s, while AMA's complete global time series starts in 1970.
3. **WDI is currently more up to date at the leading edge.** The audited WDI series already contain 2025 observations; the January 2026 AMA release ends in 2024.
4. **AMA's denser 2024 coverage is not purely observed-country coverage.** Its completeness is deliberately achieved by supplementing incomplete official series with secondary sources and estimates.
5. **The numerical series are genuinely different.** Historical revisions and estimation choices produce material differences and occasional extreme outliers; migration would silently change the meaning of the existing time series.
6. **The existing WDI product already represents a legitimate harmonized multi-source series.** Under the project source policy, such aggregation, extra history and current-year availability constitute real value rather than redundant distribution.

For `gni-per-capita.atlas-current-usd`, the decision is even stronger: the Atlas method is a World Bank methodology and has no semantically equivalent AMA substitute.

No UNSD fallback is added. Mixing two independent international compilation products observation-by-observation would make provenance harder to interpret and would create discontinuities between revision systems without a compelling gap that the project needs to fill.

## Consequence for future source audits

These eleven WDI indicators should not be proposed again for a simple UNSD-AMA migration unless the upstream situation materially changes.

Reopen the audit if one of the following occurs:

- UNSD publishes a clearly identifiable official-only global series with sufficient coverage and without secondary-source reconstruction for the target indicators;
- AMA gains a materially longer or more current time series while its provenance becomes a better fit for the project's original-source policy;
- WDI changes the construction or source organizations of these indicators materially;
- a different canonical global national-accounts source provides the same definitions with clearly superior provenance and equal or better coverage;
- the project decides to expose AMA as a separate, explicitly different harmonized national-accounts product rather than as a replacement.

Until then, the existing WDI indicator IDs and production routing remain unchanged.