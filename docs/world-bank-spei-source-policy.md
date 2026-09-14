# Weltbank – Dürre (SPEI): Quellen- und Verarbeitungspolitik

## Quelle

Der Provider `world-bank-spei` verwendet ausschließlich die direkte Weltbank-Zeitreihe `EN.CLC.SPEI.XD` (**Standardised Precipitation-Evapotranspiration Index**) aus den Sovereign-ESG-Daten.

Die Daten werden über die World-Bank Indicators API geladen. Als zugrunde liegende Quelle nennt die Weltbank die **Global SPEI database (SPEIbase)**.

Die zum Audit verwendeten Metadaten nennen:

- Periodizität: jährlich,
- Aggregationsmethode: `Average`,
- verwendete SPEI-Zeitskala: 12 Monate,
- räumliche Grundlage von SPEIbase: globale Landflächen auf einem 0,5°-Raster.

SPEI kombiniert Niederschlag und potenzielle Evapotranspiration. Negative standardisierte Werte stehen für trockenere, positive Werte für feuchtere Bedingungen relativ zu den lokalen Normalbedingungen. Die Werte sind dimensionslose standardisierte Indexwerte.

## Zeitraum und Abdeckung

Der am 14. September 2026 vollständig geprüfte Quellstand umfasst 1960–2023.

Für jedes der 64 Jahre liegen exakt **189** Werte für unsere Registry mit 250 Ländern/Gebieten vor. Es gibt keine zeitlichen Lücken innerhalb dieses Zeitraums.

Die 61 dauerhaft fehlenden Registry-Codes sind:

`ABW, AIA, ALA, ASM, ATA, ATF, BES, BLM, BMU, BVT, CCK, COK, CUW, CXR, CYM, ESH, FLK, FRO, GGY, GIB, GLP, GRL, GUF, GUM, HKG, HMD, IMN, IOT, JEY, MAC, MAF, MDV, MHL, MNP, MSR, MTQ, MYT, NCL, NFK, NIU, NRU, PCN, PRI, PSE, PYF, REU, SGS, SHN, SJM, SPM, SXM, TCA, TKL, TUV, TWN, UMI, VAT, VGB, VIR, WLF, XKX`.

Es wird **kein** fehlendes Gebiet aus anderen Datenquellen ergänzt und insbesondere Kosovo (`XKX`) nicht synthetisch erzeugt.

## Umgang mit neuen Jahren

Die historisch geprüfte Reihe 1960–2023 muss weiterhin vollständig und lückenlos bleiben.

Ein neueres Jahr wird nur veröffentlicht, wenn es dieselbe geprüfte Abdeckung von 189 Registry-Gebieten besitzt und dieselbe 61-Gebiete-Fehlmenge beibehält. Ein noch unvollständig publiziertes nachlaufendes Jahr darf in der Weltbank-API bereits vorhanden sein, wird aber nur in den Quelldiagnosen als `sourceLatestYear` bzw. `excludedTrailingYears` geführt und noch nicht in `availableYears` übernommen.

Ändert sich die Gebietskulisse selbst – etwa weil ein bisher fehlendes Gebiet erstmals Werte erhält – schlägt der Build bewusst fehl und verlangt einen neuen Quellen-Audit.

## Datenverarbeitung

- Mapping ausschließlich über `countryiso3code` der World-Bank-API auf die ISO3-Codes unserer 250er-Registry.
- `country.id` wird nicht verwendet, weil es bei dieser API den ISO2-Code enthält.
- Keine unscharfe Namenszuordnung.
- Keine Interpolation.
- Keine Extrapolation.
- Kein Fallback auf WDI, CCKP, CRU-CY oder andere Provider.
- Doppelte Land/Jahr-Werte sind ein harter Fehler.
- Nicht endliche Werte und Werte außerhalb des technischen Plausibilitätsbereichs `[-10, 10]` sind ein harter Fehler.
- Die sieben auditierten Länderwerte für 2023 werden als Regression geprüft.

## Klassifikation

Die Darstellung verwendet die international üblichen symmetrischen SPEI-Schwellen:

- `< -2`: extrem trocken,
- `-2 bis -1,5`: stark trocken,
- `-1,5 bis -1`: mäßig trocken,
- `-1 bis +1`: nahe normal,
- `+1 bis +1,5`: mäßig feucht,
- `+1,5 bis +2`: stark feucht,
- `> +2`: extrem feucht.

Daraus ergeben sich die festen Klassengrenzen `[-2, -1.5, -1, 1, 1.5, 2]`.

## Lizenz

Die konkrete World-Bank-DataBank-Metadatenseite für `EN.CLC.SPEI.XD` weist derzeit **CC BY 4.0** aus. Diese konkrete Metadaten-URL wird im Provider und in jedem Indikator-Snapshot gespeichert.

Es gibt derzeit eine Inkonsistenz innerhalb der Weltbank-Oberflächen: Die separate Sovereign-ESG-Weboberfläche hat für denselben Indikator auch ODbL-Text angezeigt. Deshalb behandeln wir die Lizenzangabe nicht als stillschweigend dauerhaft: Eine Änderung der konkreten DataBank-Metadaten oder eine eindeutige Klarstellung der Weltbank muss vor einer Änderung unseres Lizenzfeldes erneut geprüft werden.

Attribution im Snapshot:

`World Bank; Global SPEI database (SPEIbase)`

## Audit-Referenzwerte 2023

- AUT: `0.1622`
- CHN: `-1.3289`
- DEU: `0.2704`
- IND: `0.4919`
- NAM: `-0.8997`
- USA: `0.1948`
- ZAF: `-0.7253`

Diese Werte dienen nicht als manuell gepflegte Datenquelle, sondern ausschließlich als Regressionstest gegen unbeabsichtigte Änderungen der Quellreihe oder des Parsers.
