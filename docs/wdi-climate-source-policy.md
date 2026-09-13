# WDI climate source policy

## Scope

Six climate indicators intentionally remain in the World Bank WDI provider instead of being migrated to a direct EDGAR/JRC provider:

- `co2-emissions-excluding-lulucf.per-capita` → WDI `EN.GHG.CO2.PC.CE.AR5`
- `climate.ghg-total-excluding-lulucf-mtco2e` → WDI `EN.GHG.ALL.MT.CE.AR5`
- `climate.ghg-total-excluding-lulucf-per-capita` → WDI `EN.GHG.ALL.PC.CE.AR5`
- `climate.co2-total-excluding-lulucf-mtco2e` → WDI `EN.GHG.CO2.MT.CE.AR5`
- `climate.co2-intensity-gdp-ppp` → WDI `EN.GHG.CO2.RT.GDP.PP.KD`
- `climate.ghg-total-including-lulucf-mtco2e` → WDI `EN.GHG.ALL.LU.MT.CE.AR5`

This is a deliberate source-policy decision, not an unfinished migration.

## Upstream lineage

The public `WDI_GHG_emissions` preparation repository maintained by Thijs Benschop documents how the WDI greenhouse-gas series are assembled:

- repository: `https://github.com/thijsbenschop/WDI_GHG_emissions`
- audited preparation script: `20251117_prepare_EDGAR_data_for_WDI_v2.R`
- current EDGAR source documented by that script: EDGAR 2025 GHG, published in October 2025.

The preparation script combines several EDGAR datasets including:

- total greenhouse gases in AR5 CO₂-equivalents;
- methane;
- nitrous oxide;
- F-gases;
- the `IEA_EDGAR_CO2` fossil-CO₂ dataset.

The script maps these data to WDI indicator codes and explicitly creates `EN.GHG.ALL.MT.CE.AR5` and `EN.GHG.CO2.MT.CE.AR5`. It also documents the current country-level EDGAR coverage and the special treatment of world totals, which include international aviation and shipping.

For LULUCF, the same upstream pipeline uses the European Forest Observatory / JRC NGHGI data. The WDI total including LULUCF is explicitly constructed as:

`EN.GHG.ALL.LU.MT.CE.AR5 = EN.GHG.ALL.MT.CE.AR5 + EN.GHG.CO2.LU.MT.CE.AR5`

The three standalone LULUCF CO₂ indicators are handled separately by the Kartensammlung `jrc-lulucf` provider because the direct JRC NGHGI release is CC BY 4.0 and has already passed a dedicated source audit.

## Derived WDI indicators

A production-registry audit verified the formulas behind the derived WDI climate indicators using only the 250 country codes in the Kartensammlung country registry. World Bank regional and global aggregate codes were deliberately excluded.

| Relationship | Country-year overlap | Match within `1e-12` | Match within `1e-9` |
| --- | ---: | ---: | ---: |
| CO₂ per capita = CO₂ total × 1,000,000 / population | 11,165 | 11,165 (100%) | 11,165 (100%) |
| GHG per capita = GHG total × 1,000,000 / population | 11,165 | 11,165 (100%) | 11,165 (100%) |
| CO₂ intensity = CO₂ total × 1,000,000,000 / constant-2021-PPP GDP | 6,583 | 6,583 (100%) | 6,583 (100%) |
| GHG including LULUCF = GHG excluding LULUCF + CO₂ LULUCF net flux | 4,224 | 4,218 (99.858%) | 4,224 (100%) |

The six observations in the last row outside `1e-12` differ only by floating-point rounding; the largest absolute difference is approximately `1.82e-12 Mt`.

This confirms that the three ratio/intensity indicators are exact WDI derivations of their component series for production countries, and that the country-level total including LULUCF is the sum documented by the upstream preparation code.

A preliminary audit that included World Bank aggregate codes showed larger differences for codes such as `WLD`, `OSS`, `EAP`, and `ECA`. Those differences disappear when the comparison is restricted to production countries and therefore reflect aggregate-construction rules rather than country-data inconsistencies.

## Why these indicators remain in WDI

EDGAR 2025 is not governed by one uniform licence for every component used by the WDI pipeline.

The official EDGAR 2025 data page (`https://edgar.jrc.ec.europa.eu/dataset_ghg2025`) states that European Commission / JRC material is generally distributed under CC BY 4.0. However, the fossil-fuel CO₂ component `IEA-EDGAR CO2 (v4)`, based on IEA energy data, is distributed under **CC BY-NC-ND 4.0** and carries additional IEA attribution and use conditions.

That distinction matters for the Kartensammlung build system:

- `EN.GHG.CO2.MT.CE.AR5` depends directly on the IEA-EDGAR fossil-CO₂ component;
- CO₂ per capita and CO₂ intensity are mathematical derivatives of that CO₂ series;
- total GHG includes fossil CO₂ as a component;
- total GHG per capita derives from that total;
- total GHG including LULUCF derives from the same total plus the direct JRC LULUCF series.

A direct Kartensammlung provider would therefore not be a simple CC BY 4.0 redistribution of open JRC data. It would reproduce or derive from a component whose direct redistribution and modification terms are materially more restrictive.

For that reason, the project does **not** reconstruct these six indicators directly from EDGAR/IEA inputs. They remain sourced through World Bank WDI under the existing World Bank provider policy.

## Consequence for future source audits

These six indicators should not be proposed again for a direct EDGAR migration unless the upstream licensing situation materially changes or a different primary source with suitable redistribution rights is identified.

A future audit should be reopened if one of the following happens:

- EDGAR replaces the IEA-derived fossil-CO₂ component with a source suitable for the project's redistribution model;
- the IEA-EDGAR licence changes materially;
- World Bank changes the construction or provenance of the WDI greenhouse-gas series;
- another authoritative global source offers equivalent country coverage under compatible terms.

The direct `edgar` provider can continue to be used for audited emissions components whose source and licensing permit direct redistribution. The direct `jrc-lulucf` provider remains canonical for the three migrated land-use CO₂ indicators.
