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

- WDI: 14.006 Beobachtungen, 216 Länder, 1960–2024
- UN WPP: 35.787 Beobachtungen, 237 Länder, 1950–2100; letztes Schätzjahr 2023, danach Medium-Projektion
- 14.006 gemeinsame Werte; **keine einzige WDI-Beobachtung liegt außerhalb der WPP-Abdeckung**
- mediane absolute Differenz etwa 0,0003 Jahre; 2024 etwa 0,0004 Jahre
- einzelne Länder weichen dennoch deutlich ab: US Virgin Islands 2024 WDI 80,7707 vs. WPP 75,6994 Jahre; maximale historische Differenz etwa 5,94 Jahre

Entscheidung: **beide dauerhaft behalten.** Die aktuelle WDI-Metadatenbank nennt ausdrücklich drei Quellengruppen: UN World Population Prospects, nationale Statistikämter und Eurostat. WDI ist damit eine gemischte/harmonisierte Distributionsreihe und nicht bloß eine Kopie der WPP-Modellreihe. Die deutlichen nationalen Ausnahmen sind deshalb ein echter methodischer Mehrwert: WPP liefert die konsistente globale Modellreihe, WDI kann beobachtete bzw. nationale Reihen übernehmen.

#### Gesamtfertilitätsrate

`world-bank:fertility.total-births-per-woman` und `un-wpp:fertility.total-rate` überlappen 1960–2024.

- WDI: 14.008 Beobachtungen, 216 Länder, 1960–2024
- UN WPP: 35.787 Beobachtungen, 237 Länder, 1950–2100; letztes Schätzjahr 2023, danach Medium-Projektion
- 14.008 gemeinsame Werte; **keine einzige WDI-Beobachtung liegt außerhalb der WPP-Abdeckung**
- mediane absolute Differenz etwa 0,0003 Kinder je Frau
- einzelne Länder weisen dennoch echte Abweichungen auf, z. B. Curaçao 2024 WDI 1,40 vs. WPP 1,0712 und Färöer 2023 WDI 1,8676 vs. WPP 2,2402; maximale historische Differenz etwa 0,573 Kinder je Frau

Entscheidung: **beide dauerhaft behalten.** Auch die aktuelle WDI-Metadatenbank nennt UN WPP, nationale Statistikämter und Eurostat gemeinsam als Quellen. Zusätzlich beschreibt WDI die Nutzung registrierter Lebendgeburten sowie, je nach Datenlage, Zensus-/Survey-Daten, Extrapolationen und Modelle. Damit bildet WDI bewusst eine andere, gemischte Datenreihe als die reine WPP-Serie ab.

#### Kindersterblichkeit: direkte UN-IGME-Integration

Die frühere Prüfung gegen UN World Population Prospects bleibt methodisch relevant: WPP und IGME sind unterschiedliche Modellreihen. Deshalb bleiben die vorhandenen WPP-Reihen weiterhin bestehen. Zusätzlich wurde nun die eigentliche Originalquelle der drei WDI-Kindersterblichkeitsreihen direkt integriert: die United Nations Inter-agency Group for Child Mortality Estimation (UN IGME) über die UNICEF-SDMX-API.

Verwendete direkte IGME-Indikatoren:

- `CME_MRY0`: Säuglingssterblichkeit (Infant mortality rate),
- `CME_MRM0`: Neugeborenensterblichkeit (Neonatal mortality rate),
- `CME_MRY0T4`: Sterblichkeit unter 5 Jahren (Under-five mortality rate).

Alle drei Reihen werden für beide Geschlechter zusammen (`SEX=_T`) bezogen und sind in Todesfällen bzw. Sterbewahrscheinlichkeiten je 1.000 Lebendgeburten angegeben. Die UNICEF-SDMX-Antwort kennzeichnet die Datenquelle ausdrücklich als `UN_IGME` und liefert zu jeder einzelnen Beobachtung Unter- und Obergrenze des 90-%-Unsicherheitsintervalls.

Numerischer Vergleich mit WDI:

- Neugeborenensterblichkeit `SH.DYN.NMRT`: 10.070 gemeinsame Länder-Jahr-Werte. **10.070/10.070** WDI-Werte entsprechen exakt der auf eine Dezimalstelle gerundeten direkten IGME-Schätzung. UN IGME enthält zusätzlich 343 Länder-Jahr-Werte; WDI enthält keinen einzigen zusätzlichen Wert.
- Säuglingssterblichkeit `SP.DYN.IMRT.IN`: 11.830 gemeinsame Werte. **11.830/11.830** entsprechen exakt `round(IGME, 1)`. UN IGME enthält zusätzlich 1.395 Länder-Jahr-Werte; WDI enthält keinen zusätzlichen Wert.
- Unter-5-Sterblichkeit `SH.DYN.MORT`: 11.861 gemeinsame Werte. **11.861/11.861** entsprechen exakt `round(IGME, 1)`. UN IGME enthält zusätzlich 1.434 Länder-Jahr-Werte; WDI enthält keinen zusätzlichen Wert.
- Die maximale Differenz zwischen direkter IGME-Schätzung und WDI beträgt bei allen drei Reihen weniger als 0,05 je 1.000 und ist vollständig durch die WDI-Rundung auf eine Dezimalstelle erklärt.
- Direkte UN-IGME-Abdeckung im Jahr 2024: jeweils 200 Länder gegenüber 196 in WDI.
- Historie: Säuglings- und Unter-5-Sterblichkeit 1931–2024, Neugeborenensterblichkeit 1951–2024. WDI beginnt jeweils erst 1960.
- Unsicherheitsintervalle: direktes IGME **für 100 % der Beobachtungen**; WDI verteilt nur die gerundeten Punktwerte.

Entscheidung: **UN IGME ist für alle drei Kennzahlen kanonisch.** Die sichtbaren WDI-Doppelungen `SP.DYN.IMRT.IN`, `SH.DYN.NMRT` und `SH.DYN.MORT` werden vollständig entfernt. Ein WDI-Fallback ist nicht erforderlich, weil WDI keine einzige zusätzliche Länder-Jahr-Beobachtung besitzt. Die vorhandenen WPP-Kindersterblichkeitsreihen bleiben als methodisch eigenständige UN-WPP-Modellreihen bestehen.

Testbuild des direkten Providers:

- Säuglingssterblichkeit: 13.225 Beobachtungen, 200 Länder, 1931–2024,
- Neugeborenensterblichkeit: 10.413 Beobachtungen, 200 Länder, 1951–2024,
- Unter-5-Sterblichkeit: 13.295 Beobachtungen, 200 Länder, 1931–2024,
- jeweils Standardjahr 2024 mit 200 Ländern,
- 90-%-Unsicherheitsintervalle vollständig für alle 36.933 Beobachtungen vorhanden.

### WDI versus FAOSTAT

#### Waldfläche: direkte FAOSTAT-/FRA-Reihe

Die beiden WDI-Waldreihen weisen in der World-Bank-Metadatenbank ausdrücklich FAOSTAT der FAO und die Land-Use-Datenbank `RL` als Quelle aus. Die direkte aktuelle FAOSTAT-Land-Use-Reihe `Forest land` (`Item Code 6646`) enthält sowohl den Anteil an der Landfläche (`Element Code 7209`, `%`) als auch die absolute Fläche (`Element Code 5110`, `1000 ha`). Für die Kartensammlung wird die absolute Fläche mit dem exakten Faktor 10 von `1000 ha` in km² umgerechnet.

Die aktuelle FAOSTAT-Waldreihe beruht auf der jüngsten FAO Global Forest Resources Assessment (FRA 2025). Die Abweichungen gegenüber WDI sind daher kein Hinweis auf eine eigenständige World-Bank-Methodik, sondern auf unterschiedliche Distributions-/Revisionsstände derselben fachlichen FAO-Datenquelle.

Numerischer Vergleich:

- Waldanteil: FAOSTAT direkt 7.674 Beobachtungen in 226 Ländern, 1990–2024; WDI `AG.LND.FRST.ZS` 7.029 Beobachtungen in 213 Ländern, 1990–2023.
- 6.926 gemeinsame Länder-Jahr-Werte; mediane absolute Differenz 0,12 Prozentpunkte, 2023 rund 0,425 Prozentpunkte. Nur 43 gemeinsame Werte sind auf `1e-12` exakt identisch.
- Direkte FAOSTAT-Reihe besitzt 748 zusätzliche Länder-Jahr-Beobachtungen gegenüber WDI.
- Absolute Waldfläche: FAOSTAT direkt 7.899 Beobachtungen in 226 Ländern, 1990–2025; WDI `AG.LND.FRST.K2` 7.029 Beobachtungen in 213 Ländern, 1990–2023.
- Wieder 6.926 gemeinsame Werte; mediane absolute Differenz 22,55 km², mediane relative Differenz rund 0,71 %. Größere Abweichungen, etwa bei Brasilien oder der Zentralafrikanischen Republik, zeigen substanzielle FRA-Revisionen älterer Werte.
- Direkte FAOSTAT-Reihe besitzt bei der absoluten Fläche 973 zusätzliche Länder-Jahr-Beobachtungen.
- WDI besitzt für beide Reihen zusammen betrachtet nur dieselben 103 Länder-Jahr-Werte, die im aktuellen direkten FAOSTAT-Datensatz fehlen. Sie betreffen ausschließlich Gibraltar, Monaco, Nicaragua und Nauru und sind selbst FAO/FAOSTAT-originäre ältere Distributionswerte.

Entscheidung: **FAOSTAT ist für Waldanteil und absolute Waldfläche kanonisch.** Die sichtbaren WDI-Doppelungen `AG.LND.FRST.ZS` und `AG.LND.FRST.K2` werden entfernt. Für die wenigen historischen Länder-/Jahrlücken bleibt WDI ausschließlich als explizit markierter Fallback innerhalb der direkten FAOSTAT-Kennzahlen erhalten. Direkte aktuelle FAOSTAT-Werte haben immer Vorrang; ein älterer WDI-Distributionsstand darf eine aktuelle FRA-Revision niemals überschreiben.

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

Mehrere WDI-Reihen stammen fachlich aus WHO-Datenbanken. Der erste WHO-Bereinigungsbatch umfasst Suizidsterblichkeit und vorzeitige NCD-Sterblichkeit.

Status erster Batch: **vollständig umgesetzt am 12. September 2026.**

#### Suizidsterblichkeit

Direkte WHO-Quelle: World Health Data Hub, `SDGSUICIDE`, UUID `16BBF41`, Jahre 2000–2021. Die WHO-Datei enthält Gesamt-, Männer- und Frauenwerte sowie Konfidenzintervalle.

Vergleich mit WDI:

- Gesamt `SH.STA.SUIC.P5`: 4.018 gemeinsame Länder-Jahr-Werte; alle 4.018 liegen innerhalb der WDI-Rundung auf zwei Dezimalstellen, maximale absolute Differenz rund 0,0050 je 100.000.
- Männer `SH.STA.SUIC.MA.P5`: 4.016 gemeinsame Werte; alle innerhalb ±0,0051 je 100.000.
- Frauen `SH.STA.SUIC.FE.P5`: 4.024 gemeinsame Werte; alle innerhalb ±0,0051 je 100.000.
- Direkte WHO-Abdeckung 2021: 183 Länder; WDI: 185 Länder.

Die durchgehend nur bei WDI vorhandenen Gebiete sind Palästina (M49 275) und Puerto Rico (M49 630). Zusätzlich existieren wenige historische Einzellücken, insbesondere bei Antigua und Barbuda sowie St. Vincent und den Grenadinen.

Entscheidung: **WHO ist kanonisch.** Der WHO-Builder übernimmt direkte WHO-Werte und Konfidenzintervalle. Nur fehlende Länder-/Jahrbeobachtungen werden aus der WHO-originären WDI-Reihe ergänzt. Jeder solche Wert wird in `observationMetadata` ausdrücklich als `world-bank`-Fallback markiert. Damit bleibt die WDI-Abdeckung von 185 Ländern erhalten, ohne eine zweite sichtbare Kennzahl zu benötigen.

Testbuild des neuen WHO-Providers:

- Suizid gesamt: 4.018 direkte WHO-Beobachtungen + 52 WDI-Fallbacks
- Suizid Männer: 4.016 direkte + 54 Fallbacks
- Suizid Frauen: 4.024 direkte + 46 Fallbacks
- jeweils 185 Länder im Standardjahr 2021
- produktiver WHO-Snapshot: `a33516af1b331847` (Run `34705969833`)
- alle sechs WHO-Release-Dateien und beide Manifeste wurden bytegenau verifiziert; erst danach wurde der vorherige WHO-Snapshot entfernt

#### Vorzeitige NCD-Sterblichkeit

Direkte WHO-Quelle: World Health Data Hub, `NCDMORT3070`, UUID `1F96863`, Jahre 2000–2021, Gesamtbevölkerung im Alter 30–69.

- WDI `SH.DYN.NCOM.ZS` und WHO haben 4.024 gemeinsame Länder-Jahr-Werte.
- **4.024/4.024 Werte sind exakt identisch.**
- Direkte WHO-Abdeckung 2021: 183 Länder; WDI: 185 Länder.
- Durchgehend zusätzliche WDI-Gebiete: Palästina und Puerto Rico; zwei zusätzliche historische WDI-Werte für Saudi-Arabien.

Entscheidung: **WHO ist kanonisch**, mit derselben expliziten WDI-Fallback-Regel für fehlende Länder/Jahre.

Testbuild:

- 4.024 direkte WHO-Beobachtungen + 46 WDI-Fallbacks
- 185 Länder im Standardjahr 2021

Konsequenz nach erfolgreicher WHO-Produktion: Die vier sichtbaren WDI-Doppelungen `SH.STA.SUIC.P5`, `SH.STA.SUIC.MA.P5`, `SH.STA.SUIC.FE.P5` und `SH.DYN.NCOM.ZS` wurden aus dem WDI-Provider entfernt. Die zusätzliche WDI-Abdeckung bleibt ausschließlich als explizit markierter Fallback innerhalb der kanonischen WHO-Kennzahlen erhalten.

#### DTP3-Impfquote

Direkte WHO-Quelle: World Health Data Hub, `WHS4_100`, UUID `F8E084C`. Die Direktdatei enthält jährliche WHO/UNICEF-Schätzungen für 2000–2024; WDI `SH.IMM.IDPT` reicht zusätzlich bis 1980 zurück.

- 4.756 gemeinsame Länder-Jahr-Werte wurden verglichen.
- **4.756/4.756 Werte sind exakt identisch.**
- WHO direkt deckt im Jahr 2024 193 Länder ab, WDI 192.
- WDI liefert vor allem die Historie 1980–1999 sowie einzelne Länder-/Jahrlücken; WHO direkt enthält zusätzlich Cookinseln und Niue.

Entscheidung: **WHO ist kanonisch.** Die direkte WHO-Reihe wird für 2000–2024 verwendet; WDI ergänzt ausschließlich frühere Jahre und Lücken als explizit markierter Fallback. Die produktive WHO-Veröffentlichung wurde unter Snapshot `94452f4dbc452a01` (Run `34707302423`) erfolgreich abgeschlossen: alle sieben WHO-Release-Dateien und beide Manifeste wurden bytegenau verifiziert, danach wurde der vorherige WHO-Snapshot entfernt. Anschließend wurde die sichtbare WDI-Doppelung `SH.IMM.IDPT` aus dem WDI-Provider entfernt; die historische Abdeckung 1980–1999 und einzelne Länder-/Jahrlücken bleiben innerhalb der kanonischen WHO-Reihe als explizit markierte WDI-Fallbacks erhalten.

#### Gesundheitsausgaben / WHO GHED

Die drei bisher unter World Bank WDI sichtbaren Kennzahlen zu laufenden Gesundheitsausgaben stammen fachlich aus der **WHO Global Health Expenditure Database (GHED)**. WHO bezeichnet GHED selbst als Originalquelle der in WDI und im WHO Global Health Observatory republizierten Gesundheitsausgaben. Der vollständige GHED-XLSX-Download enthält 195 Länder und Territorien seit 2000 sowie das eingebettete Codebook und Versionsinformationen.

Geprüfte direkte GHED-Spalten:

- `che_gdp` → laufende Gesundheitsausgaben (CHE) in % des BIP,
- `che_pc_usd` → CHE pro Kopf in aktuellen US-Dollar,
- `che_ppp_pc` → CHE pro Kopf in aktuellen internationalen Dollar (KKP/PPP).

Vergleich mit den entsprechenden WDI-Reihen:

- `SH.XPD.CHEX.GD.ZS`: 4.562 gemeinsame Länder-Jahr-Werte; **alle Werte bis auf reine Gleitkomma-Repräsentation identisch** (maximale absolute Differenz etwa `7.1e-15`). GHED enthält zusätzlich 48 Beobachtungen, WDI keine zusätzlichen.
- `SH.XPD.CHEX.PC.CD`: 4.559 gemeinsame Werte; **inhaltlich vollständig identisch** (maximale Gleitkomma-Differenz etwa `1.8e-12`). GHED enthält zusätzlich 48 Beobachtungen, WDI keine zusätzlichen.
- `SH.XPD.CHEX.PP.CD`: 4.561 gemeinsame Werte; 4.548 liegen innerhalb `1e-9`, Median der absoluten Differenz etwa `3.4e-13`. Reale Abweichungen konzentrieren sich auf Zimbabwe, insbesondere 2019–2023. Die World Bank weist für Zimbabwe auf besondere Umrechnungsfaktoren bei Mehrfach-/Parallelwechselkursen hin. Da GHED die fachlich zuständige Originaldatenbank ist und zugleich die größere Abdeckung hat, wird der aktuelle GHED-Stand als kanonisch behandelt.

Die aktuelle GHED-Datei meldet `Last updated: December 12th, 2025`; sie enthält 2024 nur als vorläufige Teilabdeckung. Deshalb bleiben die 2024-Werte verfügbar und werden in `observationMetadata` als vorläufig markiert, während **2023 das Standardjahr** bleibt.

Lizenz: **CC BY 4.0**. Die aktuelle WDI-Metadatenanzeige weist für diese ausdrücklich aus WHO GHED stammenden Reihen CC BY 4.0 aus.

Entscheidung: **vollständig umgesetzt am 12. September 2026. WHO GHED ist der kanonische Provider für alle drei CHE-Reihen.** Ein WDI-Fallback ist nicht nötig, weil GHED in allen drei Reihen mindestens dieselbe und insgesamt größere Länder-/Jahresabdeckung hat. Die produktive GHED-Veröffentlichung lief als Run `34708549477` mit Snapshot `13bf44dede477b15`; alle drei Release-Dateien sowie Provider- und globales Manifest wurden bytegenau verifiziert. Anschließend wurden die drei sichtbaren WDI-Doppelungen `SH.XPD.CHEX.GD.ZS`, `SH.XPD.CHEX.PC.CD` und `SH.XPD.CHEX.PP.CD` aus dem WDI-Provider entfernt. Der bereinigte WDI-Produktionslauf `34708827152` veröffentlichte Snapshot `fd62c7271267f842` mit 42 Indikatoren; alle 42 Release-Dateien sowie Provider- und globales Manifest wurden bytegenau verifiziert. Erst danach wurde der vorherige WDI-Snapshot gelöscht.

Produkt-Testbuild:

- Snapshot `13bf44dede477b15`
- `% BIP`: 4.610 Beobachtungen, 195 Länder, Standardjahr 2023 mit 194 Ländern
- `US$/Kopf`: 4.607 Beobachtungen, 195 Länder, Standardjahr 2023 mit 193 Ländern
- `PPP/Kopf`: 4.609 Beobachtungen, 195 Länder, Standardjahr 2023 mit 194 Ländern
- 2024: jeweils 22 vorläufige Länderwerte; nicht als Standardjahr ausgewählt

#### Ärzte

Die direkte WHO-Reihe `HWF_0001` misst die Ärztedichte je 10.000 Einwohner. Für den Vergleich wurde sie auf je 1.000 Einwohner skaliert. WDI `SH.MED.PHYS.ZS` nennt ausdrücklich WHO Global Health Workforce Statistics, OECD und nationale Daten als gemeinsame Quellen und ist daher keine reine WHO-Kopie.

- WHO direkt: 3.682 Beobachtungen, 194 Länder, 1990–2024; 72 Länder mit Wert 2024.
- WDI: 5.355 Beobachtungen, 207 Länder, 1960–2023; deutlich längere Historie und zusätzliche Gebiete.
- 3.397 gemeinsame Länder-Jahr-Werte; 3.122 davon numerisch identisch innerhalb `1e-6`.
- Mediane absolute Differenz: 0; mittlere absolute Differenz etwa 0,0245 Ärzte je 1.000; maximale Differenz 5,8.
- Auch in aktuellen Jahren existieren reale Abweichungen, z. B. 2022 bis 1,542 Ärzte je 1.000.

Entscheidung: **WDI bleibt für diese Kennzahl kanonisch und sichtbar.** Die gemischte WHO/OECD/Länderreihe bietet eigenständige Harmonisierung, zusätzliche Historie und zusätzliche Länder-/Gebietsabdeckung. Eine zweite, fast gleich benannte direkte WHO-Kennzahl würde den Katalog eher duplizieren als ergänzen.

#### Pflegepersonal und Hebammen

Die direkte WHO-Reihe `HWF_0006` misst Pflege- und Hebammenpersonal je 10.000 Einwohner und wurde für den Vergleich auf je 1.000 skaliert. WDI `SH.MED.NUMW.P3` ist ebenfalls eine gemischte WHO/OECD/Länderreihe.

- WHO direkt: 3.582 Beobachtungen, 194 Länder, 1990–2024; 75 Länder mit Wert 2024.
- WDI: 3.410 Beobachtungen, 198 Länder, 1990–2023.
- 3.323 gemeinsame Länder-Jahr-Werte; 2.713 davon numerisch identisch innerhalb `1e-6`.
- Mediane absolute Differenz praktisch 0; mittlere absolute Differenz etwa 0,0704 je 1.000; maximale Differenz 5,284.
- Reale Abweichungen bestehen auch in jüngeren Jahren; 2023 betrug die maximale Differenz 3,278 je 1.000.

Entscheidung: **WDI bleibt kanonisch und sichtbar.** Die Reihe ist methodisch keine bloße Replikation des direkten WHO-Indikators; die abweichenden nationalen/OECD-Komponenten sind ein echter Mehrwert.

#### Masern-Impfquote (MCV1)

Direkte WHO-Quelle: Global Health Observatory, `WHS8_110`, WHO/UNICEF Estimates of National Immunization Coverage (WUENIC). Die aktuelle direkte Reihe umfasst 2000–2025. WDI `SH.IMM.MEAS` verteilt dieselbe fachliche WHO/UNICEF-Schätzung, reicht aber historisch bis 1980 und lag beim Audit nur bis 2024 vor.

- WHO direkt: 5.051 Beobachtungen, 195 Länder, 2000–2025; 195 Länder mit Wert 2025.
- WDI: 7.931 Beobachtungen, 193 Länder, 1980–2024; 192 Länder mit Wert 2024.
- 4.805 gemeinsame Länder-Jahr-Werte; 4.649 davon exakt gleich.
- Mediane absolute Differenz: 0. Die verbleibenden Unterschiede sind jedoch teilweise groß und konzentrieren sich auf revidierte jüngere WHO/UNICEF-Schätzungen; 2024 beträgt die maximale Differenz 31 Prozentpunkte.
- Der direkte WHO-GHO-Stand ist aktueller und enthält bereits 2025. Deshalb haben bei gemeinsamen Länder/Jahren direkte WHO-Werte Vorrang; ältere WDI-Vintages dürfen neuere WHO-Revisionen nicht überschreiben.

Entscheidung: **WHO ist kanonisch.** `WHS8_110` wird direkt aus dem WHO-GHO-OData-Endpunkt gebaut. WDI `SH.IMM.MEAS` ergänzt ausschließlich 1980–1999 sowie Länder-/Jahrlücken als explizit markierter Fallback. Die sichtbare WDI-Doppelung wird entfernt.

#### Müttersterblichkeit

WDI `SH.STA.MMRT` ist die modellierte Müttersterblichkeitsrate der UN Maternal Mortality Estimation Inter-Agency Group (MMEIG). Die fachlich zuständige gemeinsame Schätzgruppe besteht aus WHO, UNICEF, UNFPA, World Bank Group und UNDESA/Population Division. Die direkte WHO-GHO-Reihe verwendet den Indikator `MDG_0000000026` (SDG 3.1.1). WHO veröffentlichte am 7. April 2025 die neue MMEIG-Runde „Trends in maternal mortality 2000 to 2023“ und bezeichnet sie ausdrücklich als die aktuellsten international vergleichbaren MMEIG-Schätzungen; die neue Runde ersetzt frühere Schätzstände.

Numerischer Vergleich des aktuellen WHO-GHO-Stands mit WDI:

- WHO direkt: 7.605 Beobachtungen, 195 Länder, 1985–2023; in jedem Jahr 195 Länder.
- WDI: 7.566 Beobachtungen, 194 Länder, 1985–2023; in jedem Jahr 194 Länder.
- 7.566 gemeinsame Länder-Jahr-Werte; **7.481/7.566 WDI-Werte entsprechen exakt der auf ganze Zahlen gerundeten aktuellen WHO-Schätzung.**
- WHO besitzt zusätzlich alle 39 Jahreswerte der Cookinseln; WDI besitzt keinen einzigen zusätzlichen Länder-Jahr-Wert.
- Für alle 7.605 direkten WHO-Beobachtungen stehen Unter- und Obergrenzen des von MMEIG verwendeten 80-%-Unsicherheitsintervalls zur Verfügung.
- 85 gemeinsame Werte weichen über reine Rundung hinaus ab. Sie betreffen Kenia (39 Jahre), Mosambik (39), Luxemburg (4) sowie Haiti, Pakistan und Sudan (je 1). Bei Kenia liegen 35 der 39 WDI-Werte sogar außerhalb des aktuellen WHO-Unsicherheitsintervalls. Das ist ein deutlicher Revisionsstand-Unterschied und kein fachlicher Mehrwert von WDI.

Entscheidung: **WHO/MMEIG ist kanonisch.** Die direkte aktuelle GHO-Reihe hat größere Abdeckung, höhere numerische Präzision und vollständige 80-%-Unsicherheitsintervalle. WDI `SH.STA.MMRT` wird als sichtbare Doppelung entfernt. Ein WDI-Fallback ist nicht erforderlich, weil WDI keine einzige zusätzliche Länder-Jahr-Beobachtung besitzt; ältere WDI-Schätzstände dürfen aktuelle MMEIG-Revisionen nicht überschreiben.

Status des offenen WHO/WDI-Gesundheitsaudits: **abgeschlossen am 12. September 2026.**

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
