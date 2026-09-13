#!/usr/bin/env python3
from pathlib import Path

wdi_path = Path("config/world-bank-indicators.json")
lines = wdi_path.read_text(encoding="utf-8").splitlines(keepends=True)
needle = '"id":"energy.electricity-access-percent"'
matches = [index for index, line in enumerate(lines) if needle in line]
if len(matches) != 1:
	raise SystemExit(f"Expected exactly one WDI electricity-access row, found {len(matches)}")
del lines[matches[0]]
wdi_path.write_text("".join(lines), encoding="utf-8")

policy_path = Path("docs/statistics-source-policy.md")
policy = policy_path.read_text(encoding="utf-8")
marker = "## 6. Nächste Bereinigungsblöcke"
heading = "### WDI versus World Bank Global Electrification Database"
if marker not in policy:
	raise SystemExit("Source-policy insertion marker not found")
if heading in policy:
	raise SystemExit("Electricity-access audit section already present")

section = '''### WDI versus World Bank Global Electrification Database

Die WDI-Reihe `EG.ELC.ACCS.ZS` (Zugang zu Elektrizität, % der Bevölkerung) weist als fachliche Quelle die `SDG 7.1.1 Electrification Dataset` der World Bank aus. Die aktuelle World-Bank-Metadatenbank bezeichnet die zugrunde liegende Datenbank ausdrücklich als **World Bank Global Electrification Database** aus *Tracking SDG 7: The Energy Progress Report*. Die direkte Veröffentlichung erfolgt über Tracking SDG 7; der aktuelle XLSX-Datensatz enthält im Blatt `UN reporting` die Reihe `EG_ACS_ELEC`, Indikator `7.1.1`, Einheit `PERCENT`, `Location=ALLAREA`, `Reporting Type=G`, `Source=World Bank` und echte Ländercodes in `ISOalpha3`. Die World-Bank-Metadaten weisen für die Reihe CC BY 4.0 aus.

Der direkte Datensatz enthält zusätzlich zu den Werten pro Beobachtung die Datenart (`Nature`). Für die 5.400 gemappten Direktbeobachtungen sind dies 1.280 `C` (Country data), 1.534 `E` (Estimated data) und 2.586 `M` (Modeled data). Diese Information wird in der Kartensammlung in `observationMetadata` erhalten.

Numerischer Vergleich mit WDI:

- Direkte Global Electrification Database: 5.400 gemappte Beobachtungen, 217 Länder/Gebiete, 2000–2024.
- WDI `EG.ELC.ACCS.ZS`: 6.712 Beobachtungen, 215 Länder/Gebiete, 1990–2024.
- 5.325 gemeinsame Länder-Jahr-Werte; Median der absoluten Differenz `0`, maximale Differenz `0,05` Prozentpunkte. 2.861 Werte sind bereits als Roh-Float exakt identisch; sämtliche übrigen Unterschiede liegen innerhalb der Rundung der auf eine Dezimalstelle verteilten WDI-Werte. Die direkte Datei bewahrt die höhere veröffentlichte Präzision.
- Direkte Reihe zusätzlich: 75 Beobachtungen, exakt 25 Jahre für Anguilla (`AIA`), Cookinseln (`COK`) und Niue (`NIU`).
- WDI zusätzlich: 1.387 Beobachtungen, **ausschließlich 1990–1999**. Ab 2000 besitzt WDI keinen einzigen Länder-Jahr-Wert, der in der direkten Reihe fehlt.
- Kosovo (`XKX`) ist ein Sonderfall des historischen Fallbacks: WDI besitzt 1990–1999 jeweils 100 %, während der aktuelle direkte Workbook für Kosovo keine Beobachtung enthält. Dadurch umfasst die kombinierte Historie 218 Registry-Gebiete, das aktuelle Jahr 2024 aber 217 direkte Gebiete.
- Der Quellcode `CHI` bezeichnet das Sammelgebiet *Channel Islands*. Unsere Registry führt Jersey und Guernsey getrennt; der Sammelwert wird deshalb bewusst nicht einem der beiden Gebiete zugeordnet und nicht künstlich dupliziert.

Entscheidung: **Die World Bank Global Electrification Database ist für den Zugang zu Elektrizität kanonisch.** Die sichtbare WDI-Doppelung `EG.ELC.ACCS.ZS` wird entfernt. WDI bleibt ausschließlich als explizit markierter historischer Fallback für fehlende Beobachtungen bis einschließlich 1999 erhalten. Direkte Werte haben immer Vorrang. Der Builder bricht absichtlich ab, falls künftig ein WDI-Fallback nach 1999 nötig würde, damit ein Rückgang oder Strukturbruch der direkten Quelle nicht unbemerkt durch WDI verdeckt wird.

'''
policy_path.write_text(policy.replace(marker, section + marker, 1), encoding="utf-8")
