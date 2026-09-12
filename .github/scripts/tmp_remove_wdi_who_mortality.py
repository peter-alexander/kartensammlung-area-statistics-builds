#!/usr/bin/env python3
import json
from pathlib import Path

CONFIG = Path("config/world-bank-indicators.json")
DOCS = Path("docs/statistics-source-policy.md")

remove_ids = {
	"mortality.suicide-per-100000",
	"mortality.suicide-male-per-100000",
	"mortality.suicide-female-per-100000",
	"mortality.ncd-premature-percent",
}

text = CONFIG.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
removed = []
kept = []
for line in lines:
	matched = next((indicator_id for indicator_id in remove_ids if f'"id":"{indicator_id}"' in line), None)
	if matched:
		removed.append(matched)
	else:
		kept.append(line)

if set(removed) != remove_ids or len(removed) != 4:
	raise SystemExit(f"Expected exactly four WHO-origin WDI rows, removed={removed}")

new_text = "".join(kept)
payload = json.loads(new_text)
ids = [item["id"] for item in payload["indicators"]]
if len(ids) != 46:
	raise SystemExit(f"Expected 46 WDI indicators, got {len(ids)}")
if remove_ids & set(ids):
	raise SystemExit(f"WHO-origin WDI duplicates remain: {sorted(remove_ids & set(ids))}")
CONFIG.write_text(new_text, encoding="utf-8")

docs = DOCS.read_text(encoding="utf-8")
old_status = "Status erster Batch: **direkte WHO-Migration umgesetzt; Entfernung der vier WDI-Doppelungen erfolgt erst nach erfolgreicher produktiver WHO-Veröffentlichung.**"
new_status = "Status erster Batch: **vollständig umgesetzt am 12. September 2026.**"
if old_status not in docs:
	raise SystemExit("Expected WHO health batch status not found")
docs = docs.replace(old_status, new_status, 1)

needle = "- jeweils 185 Länder im Standardjahr 2021\n"
addition = (
	"- jeweils 185 Länder im Standardjahr 2021\n"
	"- produktiver WHO-Snapshot: `a33516af1b331847` (Run `34705969833`)\n"
	"- alle sechs WHO-Release-Dateien und beide Manifeste wurden bytegenau verifiziert; erst danach wurde der vorherige WHO-Snapshot entfernt\n"
)
if needle not in docs:
	raise SystemExit("Expected WHO suicide test-build summary not found")
docs = docs.replace(needle, addition, 1)

needle2 = "Testbuild:\n\n- 4.024 direkte WHO-Beobachtungen + 46 WDI-Fallbacks\n- 185 Länder im Standardjahr 2021\n"
addition2 = (
	"Testbuild:\n\n"
	"- 4.024 direkte WHO-Beobachtungen + 46 WDI-Fallbacks\n"
	"- 185 Länder im Standardjahr 2021\n\n"
	"Konsequenz nach erfolgreicher WHO-Produktion: Die vier sichtbaren WDI-Doppelungen `SH.STA.SUIC.P5`, `SH.STA.SUIC.MA.P5`, `SH.STA.SUIC.FE.P5` und `SH.DYN.NCOM.ZS` wurden aus dem WDI-Provider entfernt. Die zusätzliche WDI-Abdeckung bleibt ausschließlich als explizit markierter Fallback innerhalb der kanonischen WHO-Kennzahlen erhalten.\n"
)
if needle2 not in docs:
	raise SystemExit("Expected WHO NCD test-build summary not found")
docs = docs.replace(needle2, addition2, 1)
DOCS.write_text(docs, encoding="utf-8")

print("Removed WDI indicators:", ", ".join(sorted(removed)))
print("Remaining WDI indicators:", len(ids))
