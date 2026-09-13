# WHO health-workforce source policy

## Canonical direct source

The country-statistics build uses the WHO World Health Data Hub as the canonical source for the two SDG 3.c.1 health-workforce indicators:

- `HWF_0001` / UUID `217795A`: density of physicians.
- `HWF_0006` / UUID `5C8435F`: density of nursing and midwifery personnel.

WHO publishes both source datasets as rates per 10,000 population. The Kartensammlung keeps the existing user-facing unit per 1,000 population, so direct WHO values are multiplied by `0.1`. The transformation is recorded in each generated indicator payload.

## World Bank WDI fallback

The former visible WDI indicators `SH.MED.PHYS.ZS` and `SH.MED.NUMW.P3` are no longer separate visible statistics. They remain explicit fallbacks inside the WHO build and are used only for country-year observations missing from the direct WHO dataset.

Unlike the immunization and some mortality fallbacks, these WDI workforce series must not be described as an identical WHO redistribution: World Bank metadata lists WHO Global Health Workforce Statistics, OECD and country data as sources. Generated fallback metadata therefore records this mixed provenance explicitly.

## Audit results, 13 September 2026

Direct WHO CSV versus WDI after normalizing WHO from per 10,000 to per 1,000:

- Physicians: 3,396 direct WHO observations across 194 ISO countries, 1990–2023. Of 3,383 overlapping country-years, 3,368 differ by at most 0.1 per 1,000. WDI contributes 1,972 non-overlapping observations, mainly older history and gaps.
- Nursing and midwifery personnel: 3,374 direct WHO observations across 194 ISO countries, 1990–2023. Of 3,356 overlapping country-years, 3,347 differ by at most 0.1 per 1,000. WDI contributes 54 non-overlapping observations.

The few large historical differences are retained in favour of the current direct WHO dataset rather than silently substituting WDI. WHO metadata explicitly notes that original national sources and coverage differ and may include practising personnel or all registered personnel; historical comparability is therefore not guaranteed. Known large audit differences were concentrated in Austria and Denmark for older physician observations and the Russian Federation for older nursing/midwifery observations.

## Measles

The measles MCV1 statistic was already canonical direct WHO/UNICEF WUENIC (`WHS8_110`) before this audit, with World Bank WDI `SH.IMM.MEAS` only as a marked fallback. No source migration is required for measles.
