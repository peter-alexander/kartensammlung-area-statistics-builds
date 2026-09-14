# OECD – Hitze & Temperaturbelastung: Quellen- und Verarbeitungspolitik

## Quelle

Produktiv verwendet wird der OECD-Datensatz **Historical exposure to extreme temperature** im OECD Data Explorer.

- Datenflow: `OECD.ENV.EPI:DSD_ECH@EXT_TEMP_H(2.0)`
- SDMX-API: `https://sdmx.oecd.org/public/rest/data/OECD.ENV.EPI,DSD_ECH@EXT_TEMP_H,2.0`
- offiziell beschriebener Zeitraum beim Integrationsaudit: je nach Kennzahl 1979 bzw. 1981 bis 2024
- Datengrundlagen laut OECD: Copernicus Climate Change Service ERA5 sowie Global Human Settlement Layer (GHSL) für die Bevölkerungsgewichtung
- die Expositionsindikatoren wurden von OECD und IEA gemeinsam aufbereitet

Der produktive Builder greift direkt auf die OECD-SDMX-API zu. Es werden keine Daten aus Drittportalen oder Suchergebnissen übernommen.

## Lizenz und Attribution

Für die OECD-Daten gelten die **OECD Terms and Conditions**:

`https://www.oecd.org/en/about/terms-conditions.html`

Die im Snapshot hinterlegte Attribution lautet:

`OECD/IEA; Copernicus Climate Change Service ERA5; Global Human Settlement Layer (GHSL)`

## Aufgenommene Kennzahlen

Vier jährliche Länderreihen werden veröffentlicht:

1. bevölkerungsgewichtete Zahl heißer Tage mit Tagesmaximum über 35 °C (`HD_PW_EXP`, `H_35`), ab 1979;
2. bevölkerungsgewichtete Zahl starker Hitzestresstage mit UTCI über 32 °C (`UTCI_PW_EXP`, `H_32`), ab 1981;
3. bevölkerungsgewichtete Zahl sehr starker Hitzestresstage mit UTCI über 38 °C (`UTCI_PW_EXP`, `H_38`), ab 1981;
4. bevölkerungsgewichtete Zahl extremer Hitzestresstage mit UTCI über 46 °C (`UTCI_PW_EXP`, `H_46`), ab 1981.

Der **Universal Thermal Climate Index (UTCI)** bildet thermische Belastung nicht nur aus der Lufttemperatur ab, sondern berücksichtigt auch Luftfeuchtigkeit, Wind und Strahlung. Damit liefern die drei UTCI-Reihen einen anderen Informationsgehalt als die bereits vorhandenen reinen Temperatur- und Extremtemperaturreihen aus ERA5 und CRU-CY.

Die Einheit der vier OECD-Reihen ist `D_Y` (Tage pro Jahr). Durch die räumliche Bevölkerungsgewichtung sind Dezimalwerte normal und werden unverändert erhalten.

## Länderzuordnung

Die Länderregistry enthält 250 Gebiete. Die OECD-REF_AREA-Codeliste kennt beim Audit alle 250 dafür benötigten nationalen Codes. Es gibt genau eine explizite Codeabweichung:

- Registry `XKX` (Kosovo) → OECD `XKV`

Es findet **kein Fuzzy-Matching nach Ländernamen** statt.

## Auditierte Abdeckung

Stand der vollständigen Live-Prüfung vom 14. September 2026:

### Heiße Tage > 35 °C

- 1979–2024: 46 vollständig veröffentlichte Jahresstände
- 235 Registry-Gebiete mit Werten
- 235 Gebiete auch 2024
- dauerhaft fehlend: `ALA`, `ATA`, `BES`, `BLM`, `CCK`, `CUW`, `FLK`, `GIB`, `GLP`, `GUF`, `MAF`, `MTQ`, `MYT`, `REU`, `SXM`

### UTCI-Hitzestress

Für alle drei UTCI-Schwellen:

- 1981–2024: 44 vollständig veröffentlichte Jahresstände
- 232 Registry-Gebiete mit mindestens einem Wert
- 231 Gebiete im Jahr 2024
- ohne irgendeinen Wert: `ALA`, `ATA`, `ATF`, `BES`, `BLM`, `BVT`, `CCK`, `CUW`, `FLK`, `GIB`, `HMD`, `IOT`, `MAF`, `NFK`, `PCN`, `SGS`, `SXM`, `UMI`
- 2024 zusätzlich ohne Wert: `MYT`

Diese Mengen sind bewusst als Regressionen im Build verankert. Eine Quellenänderung wird daher sichtbar und nicht stillschweigend als neue Normalität übernommen.

## Unvollständige nachlaufende Jahre

Die Live-SDMX-API lieferte beim ersten Produktions-Build am 14. September 2026 bereits **Teilwerte für 2025**, obwohl die OECD-Datensatzbeschreibung zu diesem Zeitpunkt weiterhin einen Zeitraum bis 2024 auswies:

- heiße Tage > 35 °C: 234 Gebiete für 2025 statt 235 im auditierten Jahr 2024;
- UTCI-Hitzestress: 229 Gebiete für 2025 statt 231 im auditierten Jahr 2024.

Solche nachlaufenden Teiljahre werden vollständig eingelesen und validiert, aber **nicht in `availableYears` und nicht in `values` veröffentlicht**, solange ihre Länderabdeckung unter der auditierten Abdeckung des Jahres 2024 liegt. Die Quelle wird in den Metadaten mit `sourceLatestYear` und `excludedTrailingYears` transparent dokumentiert.

Sobald ein neueres Jahr mindestens dieselbe Abdeckung wie 2024 erreicht, wird es automatisch als veröffentlichbares Standardjahr übernommen. Dadurch vermeiden wir eine scheinbar weltweite Karte, die in Wirklichkeit noch aus einem unvollständigen Zwischenstand besteht.

## Qualitätsregeln

Der Build stoppt bei unerwarteten Änderungen, insbesondere wenn:

- der OECD-Datenflow nicht mehr `OECD.ENV.EPI:DSD_ECH@EXT_TEMP_H(2.0)` ist;
- Frequenz, Einheit, Dauer, Maß oder Temperaturschwelle von den festgelegten Dimensionen abweichen;
- unbekannte oder nicht angeforderte REF_AREA-Codes erscheinen;
- doppelte Länder-Jahr-Werte vorkommen;
- Werte nicht endlich sind oder außerhalb 0–366 Tage/Jahr liegen;
- die Quelljahre Lücken enthalten;
- der letzte veröffentlichbare Datenstand hinter 2024 zurückfällt;
- die auditierte Länderabdeckung oder die 2024-Fehlmengen abweichen;
- Pflichtländer im gewählten Standardjahr fehlen.

Es gibt **keine Interpolation, keine Extrapolation und keinen Fallback auf andere Anbieter**.

## Aktualisierung

Der GitHub-Workflow lädt die Daten monatlich direkt von OECD neu. Ein neues Jahr darf automatisch zum Standardjahr werden, wenn seine Länderabdeckung mindestens der auditierten 2024-Abdeckung der jeweiligen Reihe entspricht. Die 2024-Werte und ihre Abdeckung bleiben zugleich als feste Regressionsbasis erhalten.
