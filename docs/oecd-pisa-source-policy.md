# OECD PISA source policy

## Grundsatz

Für die Länderstatistiken werden ausschließlich von der OECD veröffentlichte aggregierte PISA-Ergebnistabellen verwendet. Es werden keine Mittelwerte aus Schüler-Mikrodaten neu berechnet.

PISA ist keine jährliche Statistik. Ausgegeben werden nur tatsächlich veröffentlichte Erhebungszyklen. Zwischenjahre werden weder interpoliert noch mit dem letzten bekannten Wert aufgefüllt.

## Kernfächer

Aktuelle Grundlage der drei Kernfächer ist **PISA 2025 Results (Volume I): Future-Ready Students**, veröffentlicht am 8. September 2026. Die Produktionsdaten stammen aus **Annex B1A** über den offiziellen Statlink `https://stat.link/mrq53f`.

Verwendet werden:

- `Table I.B1.2a.36` – Naturwissenschaften, PISA 2006–2025
- `Table I.B1.2a.37` – Lesen, PISA 2000–2025
- `Table I.B1.2a.38` – Mathematik, PISA 2003–2025

Die separaten 2025-Tabellen `I.B1.2a.1`, `I.B1.2a.2` und `I.B1.2a.3` werden nicht als zweite Datenquelle publiziert. Der Kern-Builder verwendet sie als Integritätsprüfung und verlangt, dass ihre numerischen 2025-Werte exakt mit den jeweiligen Trendtabellen übereinstimmen.

Die bestehende Kernlogik bleibt beim Ausbau der PISA-Kennzahlen unverändert. Der erweiterte Builder ruft denselben Kernparser auf und ergänzt die Sonderdomänen anschließend separat.

## Zusätzliche Domänen

Neun weitere offizielle PISA-Reihen werden direkt aus den zugehörigen OECD-Ergebnistabellen gelesen:

- **Fächerübergreifendes Problemlösen 2003** – `Table A5.2`, *Problem Solving for Tomorrow's World*
- **Digitales Lesen 2009 und 2012** – `T VI.2.4` sowie `Table B3.I.9`; die Reihe 2009/2012 wird als echte Zweizyklus-Reihe geführt
- **Computergestützte Mathematik 2012** – `Table B3.I.3`
- **Problemlösekompetenz 2012** – `Table V.2.2`, PISA 2012 Volume V
- **Finanzkompetenz 2012, 2015, 2018 und 2022** – `Table IV.B1.2.1`, PISA 2022 Volume IV
- **Kollaboratives Problemlösen 2015** – `Table V.3.2`, PISA 2015 Volume V
- **Globale Kompetenz 2018** – `Table VI.B1.6.1`, PISA 2018 Volume VI
- **Kreatives Denken 2022** – `Table III.B1.2.1`, PISA 2022 Volume III
- **Computationales Problemlösen 2025** – `Table I.B1.2a.4`, PISA 2025 Volume I

Die Teilnahme an optionalen und innovativen PISA-Domänen ist teilweise deutlich kleiner als in Mathematik, Lesen und Naturwissenschaften. Fehlende Länder werden nicht aus anderen Quellen ergänzt.

Kreatives Denken 2022 verwendet eine eigene Skala von **0 bis 60 Punkten**. Diese Reihe wird deshalb nicht mit der üblichen 200–700-PISA-Klassifikation dargestellt.

## Zeitachse

Die OECD-Zyklusbezeichnungen bleiben unverändert. Historische Sonderfälle wie PISA 2000+, PISA 2009+ oder PISA for Development können in einem späteren Kalenderjahr durchgeführt worden sein; für die Kartensammlung zählt das von der OECD veröffentlichte Zyklusjahr.

Bei Finanzkompetenz werden nur die in der OECD-Trendtabelle tatsächlich vorhandenen Werte für 2012, 2015, 2018 und 2022 veröffentlicht. Beim digitalen Lesen werden nur 2009 und 2012 geführt. Es gibt keine Fortschreibung auf spätere Jahre.

## Gebietszuordnung

OECD-PISA-„countries and economies“ werden nur dann auf eine Länderfläche gelegt, wenn die Einheit räumlich dem Gebiet der Kartensammlung entspricht.

Eigenständig erhalten bleiben insbesondere:

- Hong Kong (China) → `country:HKG`
- Macao (China) → `country:MAC`
- Chinese Taipei → `country:TWN`
- Palestinian Authority → `country:PSE`
- Kosovo → `country:XKX`

Diese Einheiten werden nicht auf einen anderen Staat umgebogen.

Teilstichproben werden nicht auf Ganzstaatenflächen übertragen. Dazu gehören je nach Tabelle insbesondere:

- B-S-J-Z (China)
- B-S-J-G (China)
- Shanghai-China
- Dushanbe (Tajikistan)
- Kurdistan Region (Iraq)
- Ukrainian regions (17 of 27 bzw. 18 of 27)
- Baku (Azerbaijan)
- England (United Kingdom)
- Scotland (United Kingdom)
- Flemish community of Belgium
- Canadian provinces

Beim Global-Competence-Test 2018 wird außerdem Israel nicht auf die Ganzstaatenfläche gelegt, weil die von OECD ausgewiesene Stichprobe ultraorthodoxe Schulen ausschließt und nicht national repräsentativ ist.

Neue oder nicht mehr auflösbare Quellnamen sowie Veränderungen der erwarteten Länderabdeckung führen zu einem Build-Abbruch und müssen bewusst geprüft werden.

## Qualitäts- und Vergleichbarkeitshinweise

Sterne an OECD-Ländernamen werden nicht stillschweigend entfernt:

- normale Stichproben-/Teilnahmehinweise werden als `samplingCautionAreasByYear` in den Quellmetadaten gespeichert;
- bei PISA 2022 Kreatives Denken werden doppelte Sterne für Fälle ohne ausreichend starke Verknüpfung mit der internationalen Skala getrennt als `scaleLinkageCautionAreasByYear` gespeichert.

Die numerischen Werte selbst werden dadurch nicht verändert.

## Lizenz

Die Lizenz wird **je konkrete Quellpublikation** gespeichert und nicht pauschal für den gesamten Provider behauptet.

Nach der OECD-Open-Access-Policy werden Veröffentlichungen ab **1. Juli 2024** grundsätzlich unter Creative-Commons-Lizenzen veröffentlicht; PISA 2025 Volume I ist **CC BY 4.0**. Die hier verwendeten PISA-2022-Volumes III und IV erschienen jedoch bereits am 18. bzw. 27. Juni 2024, und die älteren PISA-Publikationen stammen ebenfalls aus der Zeit davor. Für diese Quellen werden daher die **OECD Terms & Conditions** ausgewiesen.

Der Provider-Index verwendet entsprechend nur die Sammelbezeichnung **„OECD-Nutzungsbedingungen / CC BY 4.0 (quellenabhängig)“**. Jede einzelne Kennzahl enthält ihre konkrete Publikation, Attribution und Lizenz-URL in den Quellmetadaten.
