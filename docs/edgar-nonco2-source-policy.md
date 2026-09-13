# EDGAR-Policy für Methan und Lachgas

Stand: 13. September 2026

Diese Ergänzung dokumentiert die Quellenentscheidung für die beiden Länderkennzahlen `climate.methane-total-excluding-lulucf-mtco2e` und `climate.n2o-total-excluding-lulucf-mtco2e`.

## Kanonische Quelle

Kanonische Direktquelle ist **EDGAR 2026** der Europäischen Kommission / Joint Research Centre (JRC), Datensatz `EDGAR_2026_GHG`.

Verwendet werden ausschließlich die Reihen:

- `GWP_100_AR5_CH4` für Methan (CH₄)
- `GWP_100_AR5_N2O` für Lachgas (N₂O)

Die Werte sind in `Mt CO₂eq/yr` angegeben und verwenden IPCC AR5 GWP-100. Der direkte EDGAR-Zeitraum reicht von 1970 bis 2025.

Fossiles CO₂ und Gesamt-Treibhausgasemissionen werden aus diesem EDGAR-Provider bewusst **nicht** veröffentlicht, weil diese EDGAR-Bereiche einer separaten IEA-Lizenz unterliegen. Die EDGAR-Integration beschränkt sich deshalb strikt auf CH₄ und N₂O.

## Kombinierte EDGAR-Gebiete

EDGAR führt mehrere Ländergruppen als gemeinsame Gebiete. Diese Werte werden nicht künstlich auf Einzelstaaten verteilt und auch keinem einzelnen Land zugeschrieben:

- `CHE`: Switzerland and Liechtenstein
- `ESP`: Spain and Andorra
- `FRA`: France and Monaco
- `ISR`: Israel and Palestine, State of
- `ITA`: Italy, San Marino and the Holy See
- `SDN`: Sudan and South Sudan

Für Einzelstaaten, für die dadurch kein direkter EDGAR-Wert vorliegt, darf der explizite WDI-Fallback verwendet werden.

## WDI-Fallback

WDI bleibt ausschließlich als gekennzeichneter Lücken-Fallback innerhalb des EDGAR-Builders erhalten:

- Methan: `EN.GHG.CH4.MT.CE.AR5`
- Lachgas: `EN.GHG.N2O.MT.CE.AR5`
- Fallback nur bis einschließlich 2024
- Direkte EDGAR-Werte haben immer Vorrang
- Ein WDI-Wert darf niemals einen vorhandenen EDGAR-Wert überschreiben

Die früher sichtbaren WDI-Kennzahlen für Methan und Lachgas werden aus `config/world-bank-indicators.json` entfernt. Im veröffentlichten Katalog existiert damit jeweils nur noch eine sichtbare Kennzahl; deren kanonischer Provider ist EDGAR.

## Validierter Teststand

Der vollständige Testbuild ergab je Kennzahl:

- 11.200 direkte EDGAR-Werte
- 770 explizite WDI-Fallbackwerte
- 214 Gebiete insgesamt
- Standardjahr 2025
- 200 direkte Länder im Standardjahr 2025

Der Builder validiert zusätzlich den EDGAR-Zeitraum, die Einheit, die zulässigen Stoffreihen, Mindestabdeckungen und die Vorrangregel Direktquelle vor Fallback.

Bei den Sektordaten gilt: EDGAR führt Sektoren mit Nullwert nicht zwingend als eigene Zeile. Die Validierung verlangt deshalb nicht mehr für jedes Land/Jahr/Stoff-Paar eine explizite Zeile für jeden Null-Sektor, sondern prüft die tatsächlich vorhandenen Sektoren gegen die zulässige Sektorliste.
