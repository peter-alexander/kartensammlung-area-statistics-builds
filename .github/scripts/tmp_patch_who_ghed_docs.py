#!/usr/bin/env python3
from pathlib import Path

path = Path("docs/statistics-source-policy.md")
text = path.read_text(encoding="utf-8")
marker = "#### Nächste WHO-Prüfungen\n"
if marker not in text:
	raise SystemExit("WHO next-checks marker not found")
if "#### Gesundheitsausgaben / WHO GHED" in text:
	raise SystemExit("WHO GHED section already exists")
section = '''#### Gesundheitsausgaben / WHO GHED

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

Entscheidung: **WHO GHED wird als eigener Provider und kanonische Quelle für alle drei CHE-Reihen integriert.** Ein WDI-Fallback ist nicht nötig, weil GHED in allen drei Reihen mindestens dieselbe und insgesamt größere Länder-/Jahresabdeckung hat. Die drei sichtbaren WDI-Doppelungen werden erst nach erfolgreicher produktiver GHED-Veröffentlichung entfernt.

Produkt-Testbuild:

- Snapshot `13bf44dede477b15`
- `% BIP`: 4.610 Beobachtungen, 195 Länder, Standardjahr 2023 mit 194 Ländern
- `US$/Kopf`: 4.607 Beobachtungen, 195 Länder, Standardjahr 2023 mit 193 Ländern
- `PPP/Kopf`: 4.609 Beobachtungen, 195 Länder, Standardjahr 2023 mit 194 Ländern
- 2024: jeweils 22 vorläufige Länderwerte; nicht als Standardjahr ausgewählt

'''
text = text.replace(marker, section + marker, 1)
old = "- Gesundheitsausgaben,\n"
if text.count(old) != 1:
	raise SystemExit(f"expected one health-expenditure next-check bullet, found {text.count(old)}")
text = text.replace(old, "", 1)
path.write_text(text, encoding="utf-8")
