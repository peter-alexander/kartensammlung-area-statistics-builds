from pathlib import Path

path = Path("docs/statistics-source-policy.md")
text = path.read_text(encoding="utf-8")

old_life = """#### Lebenserwartung bei Geburt

`world-bank:life-expectancy.at-birth-years` und `un-wpp:life-expectancy.at-birth-years` überlappen 1960–2024.

- 14.006 gemeinsame Werte
- mediane absolute Differenz etwa 0,0003 Jahre
- 2024 median etwa 0,0004 Jahre

Entscheidung: **UN WPP soll kanonisch sein; die WDI-Doppelung kann nach abschließender Migrationsprüfung entfallen.**
"""
new_life = """#### Lebenserwartung bei Geburt

`world-bank:life-expectancy.at-birth-years` und `un-wpp:life-expectancy.at-birth-years` überlappen 1960–2024.

- WDI: 14.006 Beobachtungen, 216 Länder, 1960–2024
- UN WPP: 35.787 Beobachtungen, 237 Länder, 1950–2100; letztes Schätzjahr 2023, danach Medium-Projektion
- 14.006 gemeinsame Werte; **keine einzige WDI-Beobachtung liegt außerhalb der WPP-Abdeckung**
- mediane absolute Differenz etwa 0,0003 Jahre; 2024 etwa 0,0004 Jahre
- einzelne Länder weichen dennoch deutlich ab: US Virgin Islands 2024 WDI 80,7707 vs. WPP 75,6994 Jahre; maximale historische Differenz etwa 5,94 Jahre

Entscheidung: **vorerst beide behalten.** UN WPP hat die deutlich bessere Abdeckung, WDI ist aber nicht in allen Ländern lediglich eine identische Kopie. Vor einer Löschung muss geklärt werden, welche nationalen Quellen bzw. Harmonisierungsschritte die deutlichen Ausnahmen verursachen und ob dieser methodische Unterschied für Nutzer relevant ist.
"""

old_fert = """#### Gesamtfertilitätsrate

`world-bank:fertility.total-births-per-woman` und `un-wpp:fertility.total-rate` überlappen 1960–2024.

- 14.008 gemeinsame Werte
- mediane absolute Differenz etwa 0,0003 Kinder je Frau

Entscheidung: **UN WPP soll kanonisch sein; die WDI-Doppelung kann nach abschließender Migrationsprüfung entfallen.**
"""
new_fert = """#### Gesamtfertilitätsrate

`world-bank:fertility.total-births-per-woman` und `un-wpp:fertility.total-rate` überlappen 1960–2024.

- WDI: 14.008 Beobachtungen, 216 Länder, 1960–2024
- UN WPP: 35.787 Beobachtungen, 237 Länder, 1950–2100; letztes Schätzjahr 2023, danach Medium-Projektion
- 14.008 gemeinsame Werte; **keine einzige WDI-Beobachtung liegt außerhalb der WPP-Abdeckung**
- mediane absolute Differenz etwa 0,0003 Kinder je Frau
- einzelne Länder weisen dennoch echte Abweichungen auf, z. B. Curaçao 2024 WDI 1,40 vs. WPP 1,0712 und Färöer 2023 WDI 1,8676 vs. WPP 2,2402; maximale historische Differenz etwa 0,573 Kinder je Frau

Entscheidung: **vorerst beide behalten.** Auch hier ist WPP hinsichtlich Abdeckung überlegen, die WDI-Reihe enthält aber einzelne methodisch bzw. quellenseitig abweichende Länderwerte. Eine Entfernung erfolgt erst nach Klärung dieser Ausnahmen.
"""

old_ghed = """Entscheidung: **vollständig umgesetzt am 12. September 2026. WHO GHED ist der kanonische Provider für alle drei CHE-Reihen.** Ein WDI-Fallback ist nicht nötig, weil GHED in allen drei Reihen mindestens dieselbe und insgesamt größere Länder-/Jahresabdeckung hat. Die produktive GHED-Veröffentlichung lief als Run `34708549477` mit Snapshot `13bf44dede477b15`; alle drei Release-Dateien sowie Provider- und globales Manifest wurden bytegenau verifiziert. Anschließend werden die drei sichtbaren WDI-Doppelungen `SH.XPD.CHEX.GD.ZS`, `SH.XPD.CHEX.PC.CD` und `SH.XPD.CHEX.PP.CD` aus dem WDI-Provider entfernt.
"""
new_ghed = """Entscheidung: **vollständig umgesetzt am 12. September 2026. WHO GHED ist der kanonische Provider für alle drei CHE-Reihen.** Ein WDI-Fallback ist nicht nötig, weil GHED in allen drei Reihen mindestens dieselbe und insgesamt größere Länder-/Jahresabdeckung hat. Die produktive GHED-Veröffentlichung lief als Run `34708549477` mit Snapshot `13bf44dede477b15`; alle drei Release-Dateien sowie Provider- und globales Manifest wurden bytegenau verifiziert. Anschließend wurden die drei sichtbaren WDI-Doppelungen `SH.XPD.CHEX.GD.ZS`, `SH.XPD.CHEX.PC.CD` und `SH.XPD.CHEX.PP.CD` aus dem WDI-Provider entfernt. Der bereinigte WDI-Produktionslauf `34708827152` veröffentlichte Snapshot `fd62c7271267f842` mit 42 Indikatoren; alle 42 Release-Dateien sowie Provider- und globales Manifest wurden bytegenau verifiziert. Erst danach wurde der vorherige WDI-Snapshot gelöscht.
"""

for old, new, label in [
    (old_life, new_life, "life expectancy"),
    (old_fert, new_fert, "fertility"),
    (old_ghed, new_ghed, "GHED production cleanup"),
]:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} block, found {count}")
    text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
