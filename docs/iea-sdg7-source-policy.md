# IEA SDG 7.2 source policy

## Scope

The country-statistics build uses the International Energy Agency (IEA) Energy Statistics Data Browser as the direct source for:

- `energy.renewable-final-consumption-percent` → IEA indicator `SDG72`, flow `MRENEW`

The indicator is the renewable share of total final energy consumption. It includes energy uses beyond electricity and preserves the existing Kartensammlung indicator ID, title, unit, and classification.

This provider deliberately uses `SDG72`. It does **not** use `SDG72modern`, which is a different IEA statistic for modern renewables that excludes traditional bioenergy.

## Direct IEA source

The production source is:

- IEA Energy Statistics Data Browser
- API: `https://api.iea.org/stats/indicators/SDG72`
- flow: `MRENEW`
- flow label: `Share of renewables`
- unit: percent
- observed source period in the audited release: 1990–2022
- licence: CC BY 4.0

The IEA browser is the primary direct distribution used here. The build validates the returned row semantics rather than relying only on the descriptive metadata attached to the API indicator, because that metadata text can lag the observations available from the endpoint.

The builder fails if the source no longer starts by 1990, if its latest year regresses below 2022, if the flow/unit semantics change, or if an unexpected geography code appears.

## Why direct IEA instead of WDI

The World Bank WDI row previously used was:

- `EG.FEC.RNEW.ZS` — Renewable energy consumption (% of total final energy consumption)

A production-registry source audit found that the direct IEA series is materially more complete and contains upstream revisions that have not yet propagated consistently to WDI.

| Source | Mapped country-year observations | Countries with any value | 2021 coverage | 2022 coverage |
| --- | ---: | ---: | ---: | ---: |
| World Bank WDI | 6,746 | 212 | 212 | 71 |
| Direct IEA `SDG72` | 7,148 | 224 | 223 | 149 |

For the 6,625 overlapping production-country observations, the direct IEA and WDI series had:

- median absolute difference: about 0.03 percentage points;
- mean absolute difference: about 0.64 percentage points;
- maximum absolute difference: about 33.85 percentage points;
- 83.6% within 0.1 percentage points;
- 95.8% within 1 percentage point.

The larger differences are not explained by rounding. They reflect revisions in the upstream energy balances. Examples include Lesotho and Nigeria, where the direct IEA series differs substantially from the older WDI values.

The direct IEA series therefore provides both wider coverage and a more current audited upstream vintage than the current WDI redistribution.

## Default year and partial latest year

The audited direct IEA source contains:

- 224 mapped countries with at least one value;
- 223 countries in 2021;
- 149 countries in 2022.

The build retains the partial 2022 observations but does not make 2022 the default map year. The default year is the latest year with at least 200 mapped countries, which is currently 2021.

This avoids presenting a substantially incomplete latest year as the main global comparison while still making the newer country observations available through the year selector.

## Geography mapping

The IEA `SDG72` endpoint mixes ISO3 codes with legacy IEA/UNSD-style geography codes. The build therefore uses an explicit audited alias table instead of heuristic name matching.

The audited source used 75 such aliases. Examples include:

- `AFGHANIS` → `AFG`
- `BHUTAN` → `BTN`
- `CAFRICREP` → `CAF`
- `FPOLYNESIA` → `PYF`
- `LESOTHO` → `LSO`
- `PALESTINE` → `PSE`

Known non-country aggregates such as `WORLD`, `EU27_2020`, and WEO regional groups are explicitly allowed to be ignored. Any new unmapped geography code fails the build so that source changes are audited before deployment.

## Audit against the current UN SDG compilation

The audit also compared the direct IEA source with the current UN Global SDG Indicators Database series `EG_FEC_RNEW`.

That UN compilation is newer and combines two current custodian sources:

- IEA World Energy Balances (2025);
- UN Statistics Division Energy Balances (2025).

Mapped to the Kartensammlung registry, it contained 230 countries overall, 225 countries through 2023, and 84 observations for 2024 at audit time. It is therefore more current than the free direct IEA `SDG72` endpoint.

The UN SDG API is **not** mixed into this provider. The public Global SDG platform does not expose redistribution terms as clearly compatible with the Kartensammlung publication model as the IEA Energy Statistics Data Browser does for its CC BY 4.0 data. Using the UN compilation only as an audit benchmark avoids silently mixing sources with different distribution terms.

UNSD Energy Statistics itself has separate reuse terms and an SDMX service. A future source audit may evaluate a direct IEA + UNSD reconstruction if it can reproduce the current custodian compilation robustly and with suitable redistribution rights. That is deliberately kept separate from this migration.

## No WDI fallback

The IEA provider does not fill direct-source gaps with World Bank WDI values.

This is deliberate because:

- WDI has lower overall and latest-year coverage;
- some WDI observations represent older pre-revision values;
- mixing WDI into current direct IEA gaps would create an undocumented mixture of source vintages.

If direct IEA coverage changes materially, the build should fail its configured coverage thresholds and trigger a new audit rather than silently falling back to WDI.
