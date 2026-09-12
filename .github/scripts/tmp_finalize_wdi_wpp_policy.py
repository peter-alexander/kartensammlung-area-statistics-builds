from pathlib import Path

path = Path('docs/statistics-source-policy.md')
text = path.read_text(encoding='utf-8')

old_life = """Entscheidung: **vorerst beide behalten.** UN WPP hat die deutlich bessere Abdeckung, WDI ist aber nicht in allen Ländern lediglich eine identische Kopie. Vor einer Löschung muss geklärt werden, welche nationalen Quellen bzw. Harmonisierungsschritte die deutlichen Ausnahmen verursachen und ob dieser methodische Unterschied für Nutzer relevant ist.
"""
new_life = """Entscheidung: **beide dauerhaft behalten.** Die aktuelle WDI-Metadatenbank nennt ausdrücklich drei Quellengruppen: UN World Population Prospects, nationale Statistikämter und Eurostat. WDI ist damit eine gemischte/harmonisierte Distributionsreihe und nicht bloß eine Kopie der WPP-Modellreihe. Die deutlichen nationalen Ausnahmen sind deshalb ein echter methodischer Mehrwert: WPP liefert die konsistente globale Modellreihe, WDI kann beobachtete bzw. nationale Reihen übernehmen.
"""

old_fert = """Entscheidung: **vorerst beide behalten.** Auch hier ist WPP hinsichtlich Abdeckung überlegen, die WDI-Reihe enthält aber einzelne methodisch bzw. quellenseitig abweichende Länderwerte. Eine Entfernung erfolgt erst nach Klärung dieser Ausnahmen.
"""
new_fert = """Entscheidung: **beide dauerhaft behalten.** Auch die aktuelle WDI-Metadatenbank nennt UN WPP, nationale Statistikämter und Eurostat gemeinsam als Quellen. Zusätzlich beschreibt WDI die Nutzung registrierter Lebendgeburten sowie, je nach Datenlage, Zensus-/Survey-Daten, Extrapolationen und Modelle. Damit bildet WDI bewusst eine andere, gemischte Datenreihe als die reine WPP-Serie ab.
"""

for old, new, label in [(old_life, new_life, 'life expectancy'), (old_fert, new_fert, 'fertility')]:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'Expected one {label} decision block, found {count}')
    text = text.replace(old, new)

path.write_text(text, encoding='utf-8')
