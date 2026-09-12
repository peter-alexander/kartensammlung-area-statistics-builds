#!/usr/bin/env python3
import json
from pathlib import Path

config_path = Path("config/world-bank-indicators.json")
text = config_path.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
matches = [line for line in lines if '"id":"unemployment.total-percent"' in line]
if len(matches) != 1:
	raise SystemExit(f"Expected one WDI unemployment row, found {len(matches)}")
text = "".join(line for line in lines if '"id":"unemployment.total-percent"' not in line)
payload = json.loads(text)
if len(payload["indicators"]) != 50:
	raise SystemExit(f"Expected 50 WDI indicators, got {len(payload['indicators'])}")
if any(item["id"] == "unemployment.total-percent" for item in payload["indicators"]):
	raise SystemExit("WDI unemployment indicator still present")
config_path.write_text(text, encoding="utf-8")

policy_path = Path("docs/statistics-source-policy.md")
policy = policy_path.read_text(encoding="utf-8")
old = """Geplanter Ablauf:

1. direkte ILOSTAT-Gesamtarbeitslosenquote integrieren,
2. Jugendarbeitslosigkeit prüfen und gegebenenfalls ebenfalls direkt integrieren,
3. historische und aktuelle Abdeckung mit WDI vergleichen,
4. Werte in den gemeinsamen Jahren numerisch vergleichen,
5. WDI-Arbeitslosenquote entfernen, wenn die direkte ILOSTAT-Reihe gleichwertig oder besser ist.
"""
new = """Status: **umgesetzt am 12. September 2026.**

- Direkte ILOSTAT-Reihe: `UNE_2EAP_SEX_AGE_RT_A`, beide Geschlechter, 15+.
- Zusätzlich wurde die direkte Jugendarbeitslosenquote für 15–24-Jährige aus derselben ILOEST-Reihe integriert.
- Beide direkten Reihen decken 188 Länder über den Gesamtzeitraum und 183 Länder im letzten Nicht-Prognosejahr 2025 ab; ILOEST-Prognosen beginnen 2026.
- WDI `SL.UEM.TOTL.ZS` und die direkte ILOSTAT-Gesamtarbeitslosenquote wurden über 6.496 gemeinsame Länder-Jahr-Werte verglichen: **6.496/6.496 Werte waren exakt identisch**.
- Im Jahr 2025 waren alle 181 gemeinsamen Länderwerte exakt identisch.
- Konsequenz: ILOSTAT ist die kanonische Quelle; die WDI-Doppelung `unemployment.total-percent` wurde entfernt.
"""
if old not in policy:
	raise SystemExit("Expected labour-market policy block not found")
policy_path.write_text(policy.replace(old, new, 1), encoding="utf-8")
