# IMF Fiscal Monitor source policy

## Ziel

Der Provider `imf-fiscal-monitor` ergänzt die Länderstatistiken um fiskalische Kennzahlen, die im IMF DataMapper breit und aktuell aus dem **Fiscal Monitor** verfügbar sind, aber im bestehenden WEO-Provider nicht als eigene DataMapper-Reihen angeboten werden.

Die Quelle bleibt bewusst getrennt vom Provider `imf-weo`. Der World Economic Outlook und der Fiscal Monitor sind unterschiedliche IMF-Datensätze mit eigener Veröffentlichung, Metadaten und teilweise unterschiedlicher Länderabdeckung.

## Kanonische Quelle

Verwendet wird die offizielle IMF-DataMapper-API v2:

- API: `https://www.imf.org/external/datamapper/api/v2`
- Dataset-Code: `FM`
- Quelle beim Audit vom 13. September 2026: **Fiscal Monitor (April 2026)**
- in den DataMapper-Metadaten ausgewiesener Projektionsbeginn: **2026**

Der Builder prüft Dataset-Code, Quellbezeichnung, Einheit, Projektionsbeginn, Aktualität und Mindestabdeckung bei jedem Lauf. Ein stiller Wechsel auf einen anderen IMF-Datensatz soll dadurch fehlschlagen statt unbemerkt andere Daten auszuliefern.

## Sichtbare Kennzahlen

### Staatseinnahmen

- DataMapper-Code: `GGR_G01_GDP_PT`
- Definition: Revenue des General Government in Prozent des BIP
- Audit: 197 Länder mit mindestens einem Wert
- 2025: 194 Länder
- Zeitreihe: 1990–2031

### Staatsausgaben

- DataMapper-Code: `G_X_G01_GDP_PT`
- Definition: Expenditure des General Government in Prozent des BIP
- Audit: 196 Länder mit mindestens einem Wert
- 2025: 193 Länder
- Zeitreihe: 1990–2031

### Primärsaldo des Gesamtstaats

- DataMapper-Code: `GGXONLB_G01_GDP_PT`
- Definition: Overall balance ohne Nettozinszahlungen, in Prozent des BIP
- Audit: 189 Länder mit mindestens einem Wert
- 2025: 185 Länder
- Zeitreihe: 1990–2031

Positive Werte bedeuten einen Primärüberschuss, negative Werte ein Primärdefizit.

## Bewusst nicht zusätzlich angezeigte Fiscal-Monitor-Reihen

### Budgetsaldo und Bruttoschulden

Der Fiscal Monitor stellt auch den allgemeinen Budgetsaldo (`GGXCNL_G01_GDP_PT`) und die Bruttoschulden (`G_XWDG_G01_GDP_PT`) bereit. Beide werden **nicht** zusätzlich sichtbar gemacht, weil dieselben Konzepte bereits im kanonischen WEO-Provider vorhanden sind.

Der Live-Audit zeigte eine praktisch vollständige Übereinstimmung zwischen WEO und Fiscal Monitor. Die mediane absolute Differenz lag bei etwa 0,025 Prozentpunkten; die maximale Differenz blieb unter 0,05 Prozentpunkten. Das entspricht im Wesentlichen der geringeren Rundungspräzision der WEO-DataMapper-Ausgabe. WEO hat zudem die längere Historie ab 1980.

Doppelte sichtbare Kennzahlen würden daher keinen inhaltlichen Mehrwert bringen.

### Nettoschulden

`GGXWDN_G01_GDP_PT` ist fachlich interessant, erreicht aber nur 85 Länder; Indien fehlt vollständig. Für eine weltweite Standardkarte ist die Abdeckung derzeit zu gering. Die Reihe bleibt deshalb vorerst ausgeschlossen.

### Konjunkturbereinigte Salden

- `GGCB_G01_PGDP_PT`: 83 Länder
- `GGCBP_G01_PGDP_PT`: 81 Länder

Auch diese Reihen sind für den weltweiten Standardprovider derzeit zu lückenhaft.

## Public Finances in Modern History (FPP)

Der IMF DataMapper enthält zusätzlich die **Public Finances in Modern History Database (Dec 2025)** mit sehr langen Reihen bis 1800, unter anderem für Einnahmen, Ausgaben, Primärsaldo, Zinsausgaben und Bruttoschulden.

Die FPP-Reihen werden **nicht** als historischer Fallback unter die Fiscal-Monitor-Kennzahlen gemischt:

- nur rund 151 Länder;
- anderer Datensatz und andere historische Harmonisierung;
- in vielen Überschneidungen identische Werte, aber bei einzelnen Ländern und Perioden deutliche methodische Abweichungen;
- bei Bruttoschulden und Primärsaldo existieren besonders große Ausreißer.

Wenn FPP später integriert wird, soll es als eigener historischer Provider bzw. klar separat ausgewiesene Datenquelle erfolgen. Dadurch bleibt sichtbar, wann sich Quelle und Methodik ändern.

## Zeitsemantik

Der Fiscal Monitor weist 2026 als Projektionsbeginn aus. Der Builder verwendet deshalb standardmäßig das letzte ausreichend abgedeckte Jahr **vor** dem Projektionsbeginn; beim aktuellen Release ist das 2025.

Jahre ab 2026 bleiben verfügbar und werden über `projectionStartYear` im Provider-Index als IMF-Fiscal-Monitor-Projektionen gekennzeichnet. Es werden keine eigenen Werte interpoliert, extrapoliert oder zwischen IMF-Datensätzen verschnitten.
