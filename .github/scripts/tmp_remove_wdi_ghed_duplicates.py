#!/usr/bin/env python3
from pathlib import Path

CONFIG = Path("config/world-bank-indicators.json")
DOCS = Path("docs/statistics-source-policy.md")

ids = {
	"health-expenditure.current-percent-gdp",
	"health-expenditure.current-per-capita-usd",
	"health-expenditure.current-per-capita-ppp",
}
source_codes = {
	"SH.XPD.CHEX.GD.ZS",
	"SH.XPD.CHEX.PC.CD",
	"SH.XPD.CHEX.PP.CD",
}

lines = CONFIG.read_text(encoding="utf-8").splitlines(keepends=True)
kept = []
removed = []
for line in lines:
	if any(f'"id":"{indicator_id}"' in line for indicator_id in ids):
		removed.append(line)
		continue
	kept.append(line)
if len(removed) != 3:
	raise SystemExit(f"Expected to remove exactly 3 WDI GHED duplicate lines, removed {len(removed)}")
for code in source_codes:
	if not any(code in line for line in removed):
		raise SystemExit(f"Expected WDI source code not removed: {code}")
CONFIG.write_text("".join(kept), encoding="utf-8")

text = DOCS.read_text(encoding="utf-8")
old = "Entscheidung: **WHO GHED wird als eigener Provider und kanonische Quelle für alle drei CHE-Reihen integriert.** Ein WDI-Fallback ist nicht nötig, weil GHED in allen drei Reihen mindestens dieselbe und insgesamt größere Länder-/Jahresabdeckung hat. Die drei sichtbaren WDI-Doppelungen werden erst nach erfolgreicher produktiver GHED-Veröffentlichung entfernt."
new = "Entscheidung: **vollständig umgesetzt am 12. September 2026. WHO GHED ist der kanonische Provider für alle drei CHE-Reihen.** Ein WDI-Fallback ist nicht nötig, weil GHED in allen drei Reihen mindestens dieselbe und insgesamt größere Länder-/Jahresabdeckung hat. Die produktive GHED-Veröffentlichung lief als Run `34708549477` mit Snapshot `13bf44dede477b15`; alle drei Release-Dateien sowie Provider- und globales Manifest wurden bytegenau verifiziert. Anschließend werden die drei sichtbaren WDI-Doppelungen `SH.XPD.CHEX.GD.ZS`, `SH.XPD.CHEX.PC.CD` und `SH.XPD.CHEX.PP.CD` aus dem WDI-Provider entfernt."
if text.count(old) != 1:
	raise SystemExit(f"Expected exactly one GHED decision paragraph, found {text.count(old)}")
text = text.replace(old, new, 1)
DOCS.write_text(text, encoding="utf-8")
