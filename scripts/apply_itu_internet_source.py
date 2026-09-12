#!/usr/bin/env python3
import json
from pathlib import Path


def main() -> None:
	wdi_path = Path("config/world-bank-indicators.json")
	wdi = json.loads(wdi_path.read_text(encoding="utf-8"))
	before = len(wdi["indicators"])
	wdi["indicators"] = [
		item for item in wdi["indicators"]
		if item.get("sourceIndicator") != "IT.NET.USER.ZS"
	]
	if before - len(wdi["indicators"]) != 1:
		raise SystemExit("Expected exactly one WDI IT.NET.USER.ZS row")
	wdi_path.write_text(json.dumps(wdi, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")

	policy_path = Path("docs/statistics-source-policy.md")
	policy = policy_path.read_text(encoding="utf-8")
	marker = "## 7. Release-Policy"
	if policy.count(marker) != 1:
		raise SystemExit("Release-policy marker not found exactly once")
	section = """### ITU DataHub / Internetnutzung

WDI `IT.NET.USER.ZS` (Individuals using the Internet, % of population) nennt die International Telecommunication Union (ITU) und deren World Telecommunication/ICT Indicators bzw. ITU DataHub als fachliche Quelle. Für den direkten Vergleich wird der öffentliche Datensatz **ITU Data Hub** aus dem World Bank Data Catalog verwendet. Dieser Datensatz wird dort als ITU-Datensatz beschrieben, ist öffentlich als normalisierter CSV-Export verfügbar und trägt im Data Catalog die Lizenz CC BY 4.0. Der technische Distributionsweg über den World Bank Data Catalog wird in den Payloads ausdrücklich getrennt von der fachlichen Quelle ITU DataHub ausgewiesen.

Direkte Reihe im Export: `IT_NET_USER`, Gesamtbevölkerung (`SEX=_T`, `AGE=_T`, `URBANISATION=_T`, alle drei `COMP_BREAKDOWN`-Dimensionen `_Z`), Einheit `PT_POP`, jährliche Frequenz.

Numerischer Vergleich mit WDI `IT.NET.USER.ZS`:

- ITU DataHub: 5.089 gemappte Beobachtungen, 226 Gebiete, 2000–2025; 185 Gebiete im Jahr 2024 und 11 im Jahr 2025.
- WDI: 6.224 Beobachtungen, 213 Gebiete, 1990–2025; 182 Gebiete im Jahr 2024 und 10 im Jahr 2025.
- 4.900 gemeinsame Länder-Jahr-Werte; **alle 4.900 sind numerisch identisch** (maximale Differenz rund `8.1e-17` durch Gleitkomma-Repräsentation).
- ITU DataHub enthält 189 zusätzliche Länder-Jahr-Werte. Dazu gehören unter anderem Taiwan (25 Werte 2000–2024), Cookinseln, Niue und weitere Gebiete. 2024 besitzt ITU zusätzlich Saint-Barthélemy, Taiwan und Vatikanstadt; 2025 zusätzlich Saint-Barthélemy.
- WDI enthält 1.324 zusätzliche Länder-Jahr-Werte. **Alle 1.324 liegen ausschließlich vor 2000**; ab 2000 besitzt WDI keinen einzigen zusätzlichen Wert gegenüber dem direkten ITU-Export.
- Der direkte Export wird im World Bank Data Catalog als Public / CC BY 4.0 geführt; die verwendete CSV-Ressource wurde beim Audit zuletzt am 14. März 2026 aktualisiert.

Entscheidung: **ITU DataHub ist kanonisch.** Die direkte ITU-DataHub-Reihe wird ab 2000 verwendet und hat bei jedem gemeinsamen Länder/Jahr Vorrang. WDI `IT.NET.USER.ZS` bleibt ausschließlich als explizit markierter Fallback für Beobachtungen erhalten, die im ITU-Export fehlen; beim Audit sind dies genau die 1.324 Werte der Jahre 1990–1999. Die sichtbare WDI-Doppelung wird entfernt. Dadurch bleibt die längere WDI-Historie erhalten, während zugleich die größere direkte ITU-Gebietsabdeckung genutzt wird.

"""
	policy_path.write_text(policy.replace(marker, section + marker), encoding="utf-8")


if __name__ == "__main__":
	main()
