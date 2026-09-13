# UNHCR Refugee Population Statistics source policy

## Scope

The Kartensammlung publishes eight country-level annual series from the UNHCR Refugee Population Statistics Database.

Canonical source:

- provider: UNHCR
- dataset: Refugee Population Statistics Database
- audited release: 2025 annual statistics
- release date: 11 June 2026
- latest year: 2025
- license: CC BY 4.0
- frequency: annual end-year population stocks

Published series:

1. refugees by host country
2. refugees by country of origin
3. asylum-seekers by host country
4. asylum-seekers by country of origin
5. other people in need of international protection (OIP) by host country
6. OIP by country of origin
7. internally displaced people under UNHCR protection and/or assistance
8. stateless people by country of residence

## Keep UNHCR population categories separate

The population categories are not added together into a synthetic historical series.

In particular, OIP is a separate UNHCR category whose published history begins in 2018. Appending OIP to the much longer refugee series would create a methodological break in the mapped time series.

The production build therefore does not:

- merge refugees and OIP;
- fill one category from another;
- use fallback datasets;
- interpolate missing country-years;
- extrapolate future values.

## Historical availability

The direct UNHCR API was audited against the production country registry. The first positive mapped years are:

| Series | First positive mapped year |
| --- | ---: |
| Refugees by host country | 1951 |
| Refugees by origin country | 1960 |
| Asylum-seekers by host country | 2000 |
| Asylum-seekers by origin country | 2000 |
| Internally displaced people under UNHCR protection/assistance | 1993 |
| OIP by host country | 2018 |
| OIP by origin country | 2018 |
| Stateless people by residence | 2004 |

UNHCR documents refugee statistics as a category back to 1951. The production distinction above is more specific: when the live API is mapped to countries, the host-country refugee series has positive observations from 1951, while the origin-country refugee series begins in 1960.

These mapped starts are validated by the production build. A changed first positive year is treated as a source-model change that requires review.

## Host and origin dimensions

UNHCR publishes the same population categories along different geographic dimensions.

For refugees, asylum-seekers and OIP the Kartensammlung therefore keeps two separate maps:

- **host**: country of asylum/residence (`coa_iso`);
- **origin**: country of origin (`coo_iso`).

These dimensions answer different questions and must not be substituted for one another.

Statelessness is mapped only by country of residence. UNHCR-assisted IDPs are also mapped on the country-of-asylum/residence dimension because displacement remains within the affected country.

## September 2026 live audit

The 2025 annual data were audited directly from the UNHCR API against the 250-country production registry.

| Series | Countries with a positive 2025 value | 2025 mapped total |
| --- | ---: | ---: |
| Refugees by host country | 167 | 28.46 million |
| Refugees by origin country | 195 | 28.29 million |
| Asylum-seekers by host country | 157 | 9.00 million |
| Asylum-seekers by origin country | 204 | 7.42 million |
| OIP by host country | 23 | 7.18 million |
| OIP by origin country | 2 | 7.07 million |
| IDPs under UNHCR protection/assistance | 38 | 64.24 million |
| Stateless people by residence | 94 | 4.48 million |

The OIP origin series is highly concentrated in 2025: the mapped population is attributed to Venezuela and Afghanistan. This is a property of the source category, not a mapping fallback. Its mapped total differs from the host-country OIP total because the two dimensions are not interchangeable and because non-country source records are excluded from a country map.

## UNHCR IDPs are not the global IDP total

The UNHCR field `idps` counts internally displaced people to whom UNHCR provides protection and/or assistance. It therefore has a narrower scope than the global conflict-displacement stock published by the Internal Displacement Monitoring Centre (IDMC).

For 2025 the audited UNHCR total is about 64.24 million, while IDMC reports about 68.6 million conflict-related IDPs.

The production title is therefore deliberately:

**Binnenvertriebene unter UNHCR-Schutz/-Hilfe**

It must not be shortened to a label that implies complete worldwide IDP coverage.

IDMC would be the preferable source for a global IDP-total map, but it is not used in this provider. The audited original IDMC API requires an access key and its data carry a CC BY-NC-SA 3.0 IGO license. The Kartensammlung does not bypass those source conditions by retrieving the same IDMC material indirectly through another API.

## Non-country source codes

The live audit identified three UNHCR source codes that are not ordinary countries in the production registry:

- `UNK`: unknown origin/residence;
- `TIB`: Tibetan;
- `XXA`: stateless/non-country classification.

They are explicitly excluded from the country map and documented in provider diagnostics.

They are never guessed, reassigned or folded into a nearby country.

The production builder uses a strict allowlist containing only these three codes. Any additional non-empty UNHCR code that is not in the country registry causes the build to fail so that a source-model or code-list change cannot silently alter the map.

## Zeroes and missing values

A numeric zero is retained as a real reported value.

Missing fields, blank values and `-` are treated as unavailable data and are not converted to zero.

This distinction is important because absence of a reported population is not equivalent to a reported population of zero.

## Confidentiality rounding

UNHCR states that small population values may be rounded for protection and confidentiality. In particular, small counts can be rounded to the nearest multiple of five.

The Kartensammlung retains the values exactly as published by UNHCR. It does not attempt to reverse the rounding or infer suppressed individual-level counts.

Users should therefore not interpret very small mapped values as exact person-level counts.

## Fixed map classes

All eight series use the same logarithmic class boundaries:

`100 / 1,000 / 10,000 / 100,000 / 1,000,000 / 5,000,000 people`

This common scale makes population magnitudes comparable across categories and years while still displaying both small and very large affected populations.

The class boundaries are fixed. Colours therefore retain the same quantitative meaning when the time slider changes.

## Update strategy

The production workflow fetches the two UNHCR country dimensions directly from the population API and derives all eight indicators from those source responses.

For the audited release it pins and validates:

- latest source year: 2025;
- release date: 11 June 2026;
- exactly eight production indicators;
- the first positive mapped year of every production series;
- minimum positive-country coverage in 2025;
- non-negative finite population values;
- absence of duplicate country-year observations;
- the exact allowlist of non-country source codes;
- absence of any other unmapped source codes;
- presence of the UNHCR provider in the global provider catalogue.

The builder also records source-row counts, pagination, exclusions and per-indicator coverage in the provider index.

A future annual UNHCR release is not accepted merely because the API begins returning another year. `latestYear`, release metadata and coverage thresholds are advanced only after the new release has been audited.

After a successful `main` build, the workflow deploys the global statistics index, the UNHCR provider index and all eight immutable snapshot files. It then verifies browser CORS access and byte-for-byte equality between the locally built files and the public files.
