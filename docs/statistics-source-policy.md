# Statistik-Quellen-, Duplikat- und Release-Policy

Stand: 12. September 2026

Diese Policy beschreibt, wie die Kartensammlung Statistikquellen auswählt, überlappende Reihen bewertet und veröffentlichte Statistik-Snapshots verwaltet.

## 1. Grundsatz: Originalquelle vor Distributor

Für eine Kennzahl soll grundsätzlich die fachlich zuständige Originalquelle die kanonische Quelle sein.

Beispiele:

- Arbeitsmarkt: ILOSTAT / ILO
- Bevölkerung und demografische Modellreihen: UN World Population Prospects, sofern die konkrete Reihe tatsächlich aus WPP stammt
- Gesundheit: WHO bzw. die konkrete WHO-Datenbank
- Landwirtschaft und Landnutzung: FAOSTAT / FAO
- Wasser: AQUASTAT / FAO
- Bildung: UNESCO UIS
- Elektrizität: Ember, soweit Ember die fachlich passendere direkte Quelle ist

Aggregatoren und Distributoren wie die World Bank World Development Indicators (WDI) bleiben nur dann kanonisch, wenn ihre Reihe einen echten Mehrwert gegenüber der direkt verfügbaren Originalquelle bietet.

Ein echter Mehrwert kann insbesondere sein:

- bessere historische Abdeckung,
- bessere Länderabdeckung,
- eine andere, fachlich sinnvolle Definition,
- eine eigenständige Harmonisierung oder Transformation,
- eine aktuellere Reihe,
- eine relevante Aggregation mehrerer Originalquellen.

Die bloße bequemere API oder die Tatsache, dass WDI dieselbe Reihe nochmals verteilt, ist kein Grund, eine Doppelung dauerhaft zu behalten.

## 2. Provider-Namen

Provider-Namen sollen die tatsächlich verwendete Datenbank benennen und nicht mehr Urheberschaft suggerieren, als fachlich gerechtfertigt ist.

Daher heißt der bisherige Provider `World Bank` im Katalog `World Bank WDI`. Er repräsentiert die World Development Indicators als Distributions- und Aggregationsschicht. Die fachliche Originalorganisation einzelner WDI-Reihen kann davon abweichen und wird bei der Duplikatprüfung berücksichtigt.

## 3. Duplikatprüfung

Eine ähnlich klingende Kennzahl ist nicht automatisch ein Duplikat. Vor dem Entfernen einer Reihe werden mindestens folgende Punkte geprüft:

1. Originalorganisation und Quellendatenbank
2. Definition und Bezugsgröße
3. Einheit
4. Geschlecht, Altersgruppe oder andere Subgruppen
5. beobachtete Werte gegen modellierte Schätzungen
6. historischer Zeitraum
7. aktuelle Länderabdeckung
8. Revisions- und Aktualisierungsstand
9. tatsächliche Werte in überlappenden Ländern und Jahren

Wenn zwei Reihen fachlich dieselbe Reihe darstellen, wird die direkte Originalquelle bevorzugt. Wenn sie trotz ähnlichem Namen methodisch verschieden sind, dürfen beide bestehen bleiben.

## 4. Numerischer Vergleich

Bei potenziellen Duplikaten reicht die Metadatenbeschreibung allein nicht aus. Wo möglich werden die veröffentlichten normalisierten Reihen zusätzlich numerisch verglichen.

Dabei werden für gemeinsame Länder und Jahre unter anderem betrachtet:

- Zahl gemeinsamer Beobachtungen,
- Anteil exakt gleicher Werte,
- mediane absolute Differenz,
- mediane relative Differenz,
- Differenz im jüngsten gemeinsamen Jahr.

Sehr kleine Rundungsunterschiede können trotzdem dieselbe fachliche Reihe darstellen. Umgekehrt kann ein identischer Median Unterschiede in einzelnen Ländern verdecken.

## 5. Audit vom 12. September 2026

Der produktive Katalog umfasste zum Zeitpunkt des Audits 15 Provider und 300 veröffentlichte Indikatoren.

### WDI versus UN World Population Prospects

#### Bevölkerung

`world-bank:population.total` und `un-wpp:population.total` überlappen 1960–2025.

- 14.226 gemeinsame Länder-Jahr-Werte
- rund 61,7 % exakt identisch
- mediane absolute Differenz: 0
- 2025: rund 55,6 % exakt identisch; mediane absolute Differenz 0

Entscheidung: **vorerst beide behalten**. WDI ist hier nicht nur eine triviale Kopie; die World-Bank-Reihe kann nationale Quellen und weitere Komponenten kombinieren.

#### Lebenserwartung bei Geburt

`world-bank:life-expectancy.at-birth-years` und `un-wpp:life-expectancy.at-birth-years` überlappen 1960–2024.

- 14.006 gemeinsame Werte
- mediane absolute Differenz etwa 0,0003 Jahre
- 2024 median etwa 0,0004 Jahre

Entscheidung: **UN WPP soll kanonisch sein; die WDI-Doppelung kann nach abschließender Migrationsprüfung entfallen.**

#### Gesamtfertilitätsrate

`world-bank:fertility.total-births-per-woman` und `un-wpp:fertility.total-rate` überlappen 1960–2024.

- 14.008 gemeinsame Werte
- mediane absolute Differenz etwa 0,0003 Kinder je Frau

Entscheidung: **UN WPP soll kanonisch sein; die WDI-Doppelung kann nach abschließender Migrationsprüfung entfallen.**

#### Säuglingssterblichkeit

`world-bank:mortality.infant-per-1000` und `un-wpp:infant-mortality.rate` sind keine identischen Reihen.

- 11.830 gemeinsame Werte
- mediane absolute Differenz etwa 1,53 je 1.000 Lebendgeburten
- 2024 median etwa 1,34 je 1.000

Die WDI-Reihe basiert auf der UN Inter-agency Group for Child Mortality Estimation (IGME), während die vorhandene direkte UN-Reihe aus WPP stammt.

Entscheidung: **beide vorerst behalten**. Mittelfristig soll geprüft werden, ob IGME direkt integriert werden kann; dann wäre die direkte IGME-Reihe gegenüber WDI zu bevorzugen.

#### Unter-5-Sterblichkeit

`world-bank:mortality.under5-per-1000` und `un-wpp:under-five-mortality.rate` sind ebenfalls methodisch verschieden.

- 11.861 gemeinsame Werte
- mediane absolute Differenz etwa 0,56 je 1.000
- 2024 median etwa 1,02 je 1.000

Entscheidung: **beide vorerst behalten; direkte IGME-Integration prüfen.**

### WDI versus FAOSTAT

#### Waldanteil

`world-bank:forest.area-percent` und `faostat:land-use.forest-land-share` überlappen 1990–2023.

- 6.926 gemeinsame Werte
- mediane absolute Differenz etwa 0,12 Prozentpunkte
- 2023 median etwa 0,43 Prozentpunkte

WDI weist FAOSTAT als wesentliche Quelle aus, die veröffentlichten Werte sind jedoch nicht überall identisch.

Entscheidung: **noch nicht löschen**. Zuerst Definition, Bezugsfläche und Transformation im Detail vergleichen. Wenn die FAOSTAT-Reihe dieselbe fachliche Kennzahl direkt abbildet, wird FAOSTAT kanonisch.

## 6. Nächste Bereinigungsblöcke

### Arbeitsmarkt

Die WDI-Arbeitslosenquote `SL.UEM.TOTL.ZS` ist eine modellierte ILO-Schätzung. ILOSTAT ist deshalb die bevorzugte kanonische Quelle.

Status: **umgesetzt am 12. September 2026.**

- Direkte ILOSTAT-Reihe: `UNE_2EAP_SEX_AGE_RT_A`, beide Geschlechter, 15+.
- Zusätzlich wurde die direkte Jugendarbeitslosenquote für 15–24-Jährige aus derselben ILOEST-Reihe integriert.
- Beide direkten Reihen decken 188 Länder über den Gesamtzeitraum und 183 Länder im letzten Nicht-Prognosejahr 2025 ab; ILOEST-Prognosen beginnen 2026.
- WDI `SL.UEM.TOTL.ZS` und die direkte ILOSTAT-Gesamtarbeitslosenquote wurden über 6.496 gemeinsame Länder-Jahr-Werte verglichen: **6.496/6.496 Werte waren exakt identisch**.
- Im Jahr 2025 waren alle 181 gemeinsamen Länderwerte exakt identisch.
- Konsequenz: ILOSTAT ist die kanonische Quelle; die WDI-Doppelung `unemployment.total-percent` wurde entfernt.

### Gesundheit

Mehrere WDI-Reihen stammen fachlich aus WHO-Datenbanken, darunter beispielsweise:

- Suizidrate,
- vorzeitige NCD-Sterblichkeit,
- Gesundheitsausgaben,
- Ärzte sowie Pflege-/Hebammenpersonal,
- DPT-Impfquote,
- Masern-Impfquote.

Diese Reihen sollen einzeln gegen direkt verfügbare WHO-Datensätze geprüft und bei mindestens gleichwertiger Abdeckung in den direkten WHO-Provider verlagert werden.

### Weitere Themen

Dasselbe Verfahren gilt anschließend für WDI-Reihen aus FAO, UNESCO, ILO, WHO und anderen Originalorganisationen.

## 7. Release-Policy

Für jeden Statistik-Provider wird dauerhaft **nur der aktuell aktive Snapshot** auf dem Produktionsserver behalten.

Es wird kein zusätzliches vergangenes Release als dauerhafte Sicherung vorgehalten.

Der vorherige Snapshot bleibt jedoch während eines Deployments unangetastet, bis der neue Snapshot vollständig verifiziert wurde.

Die Reihenfolge ist:

1. neuen Snapshot in ein eigenes Release-Verzeichnis hochladen,
2. sämtliche neuen Release-Dateien öffentlich über HTTPS bytegenau mit den lokalen Build-Dateien vergleichen,
3. Provider- und globales Manifest atomar veröffentlichen,
4. beide öffentlichen Manifeste bytegenau vergleichen,
5. erst danach alle anderen Snapshot-Verzeichnisse dieses Providers löschen.

Bei einem Fehler vor Schritt 5 werden keine alten Snapshots gelöscht.

### Produktiver Test

Die Policy wurde erstmals mit dem World-Bank-WDI-Produktionslauf `34703596939` getestet.

- aktiver Snapshot: `400142088ee3203e`
- 51 Release-Dateien bytegenau verifiziert
- Provider- und globales Manifest bytegenau verifiziert
- anschließend 8 veraltete WDI-Snapshots gelöscht
- Ergebnis: nur der aktive WDI-Snapshot bleibt erhalten

Mehrere temporäre SSL-Verbindungs-Timeouts während der HTTPS-Verifikation wurden durch die Retry-Logik abgefangen. Die Löschung begann erst nach vollständig erfolgreicher Verifikation.

## 8. Änderungsregel

Eine bestehende Statistikreihe wird nicht allein wegen eines ähnlich benannten Direktproviders gelöscht.

Entfernung erfolgt erst, wenn dokumentiert ist, dass:

- die direkte Quelle fachlich dieselbe oder die eindeutig bevorzugte Reihe liefert,
- die benötigte Länder- und Zeitabdeckung ausreichend ist,
- die normalisierten Werte plausibel sind,
- und der Frontend-Nutzer durch die Migration keinen relevanten Informationsverlust erleidet.

Diese Policy ist bewusst konservativ: **Doppelungen sollen reduziert werden, aber nicht auf Kosten methodischer Vielfalt oder Datenabdeckung.**
