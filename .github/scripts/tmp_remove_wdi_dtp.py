#!/usr/bin/env python3
import json
from pathlib import Path

CONFIG = Path("config/world-bank-indicators.json")
DOCS = Path("docs/statistics-source-policy.md")

indicator_id = "immunization.dpt-percent"
source_code = "SH.IMM.IDPT"

text = CONFIG.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
removed = [line for line in lines if f'"id":"{indicator_id}"' in line]
if len(removed) != 1 or f'"sourceIndicator":"{source_code}"' not in removed[0]:
	raise SystemExit(f"Expected exactly one {indicator_id}/{source_code} row, found {len(removed)}")

new_text = "".join(line for line in lines if line not in removed)
payload = json.loads(new_text)
ids = [item["id"] for item in payload["indicators"]]
if len(ids) != 45:
	raise SystemExit(f"Expected 45 WDI indicators after DTP cleanup, got {len(ids)}")
if indicator_id in ids:
	raise SystemExit("DTP duplicate still present in WDI config")
CONFIG.write_text(new_text, encoding="utf-8")

docs = DOCS.read_text(encoding="utf-8")
old = "Entscheidung: **WHO ist kanonisch.** Die direkte WHO-Reihe wird für 2000–2024 verwendet; WDI ergänzt ausschließlich frühere Jahre und Lücken als explizit markierter Fallback. Die sichtbare WDI-Doppelung wird erst nach erfolgreicher WHO-Produktion entfernt."
new = (
	"Entscheidung: **WHO ist kanonisch.** Die direkte WHO-Reihe wird für 2000–2024 verwendet; WDI ergänzt ausschließlich frühere Jahre und Lücken als explizit markierter Fallback. "
	"Die produktive WHO-Veröffentlichung wurde unter Snapshot `94452f4dbc452a01` (Run `34707302423`) erfolgreich abgeschlossen: alle sieben WHO-Release-Dateien und beide Manifeste wurden bytegenau verifiziert, danach wurde der vorherige WHO-Snapshot entfernt. "
	"Anschließend wurde die sichtbare WDI-Doppelung `SH.IMM.IDPT` aus dem WDI-Provider entfernt; die historische Abdeckung 1980–1999 und einzelne Länder-/Jahrlücken bleiben innerhalb der kanonischen WHO-Reihe als explizit markierte WDI-Fallbacks erhalten."
)
if old not in docs:
	raise SystemExit("Expected DTP migration status text not found")
docs = docs.replace(old, new, 1)
DOCS.write_text(docs, encoding="utf-8")

print(f"Removed WDI indicator: {indicator_id} / {source_code}")
print(f"Remaining WDI indicators: {len(ids)}")
