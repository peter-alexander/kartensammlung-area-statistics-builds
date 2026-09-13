from pathlib import Path

path = Path("docs/statistics-source-policy.md")
text = path.read_text(encoding="utf-8")
text = text.replace("Stand: 12. September 2026", "Stand: 13. September 2026", 1)

marker = "## 6. Nächste Bereinigungsblöcke"
if marker not in text:
	raise SystemExit(f"Marker not found: {marker}")

section = """### WDI versus Tracking SDG 7 / erneuerbare Energie

WDI `EG.FEC.RNEW.ZS` misst den Anteil erneuerbarer Energie am gesamten Endenergieverbrauch und nennt in der aktuellen World-Bank-Metadatenbank den **IEA Energy Statistics Data Browser** als Quelle, zuletzt abgerufen am 25. März 2025. Die WDI-Reihe ist für 1990–2022 veröffentlicht; die World-Bank-Metadaten weisen für genau diese WDI-Reihe **CC BY 4.0** aus.

Für den Direktquellen-Audit wurden zwei aktuelle Originalwege getrennt geprüft:

1. der öffentliche IEA-Stats-Endpunkt `SDG72` (*Renewable share in final energy consumption (SDG 7.2)*),
2. der aktuelle gemeinsame Tracking-SDG-7-Datensatz `SDG 7.2 Renewable Energy Dataset` mit der offiziellen Reihe `EG_FEC_RENEW` für Indikator 7.2.1.

Der allgemeine IEA-Data-Browser-Endpunkt `SDG72` ist **kein geeigneter 1:1-Ersatz** für WDI. Schon bei eindeutig gemappten Ländern treten große Abweichungen auf, beispielsweise Nigeria 2014 mit rund 49,7 % im IEA-Endpunkt gegenüber 79,9 % in WDI. Das ist keine Rundung, sondern ein anderer bzw. älterer Revisions-/Verarbeitungsstand.

Der fachlich maßgeblichere aktuelle Tracking-SDG-7-XLSX wurde am 24. Juni 2026 veröffentlicht. Im Blatt `7.2 Official indicator` enthält er echte `ISO3`-Codes, `SeriesCode=EG_FEC_RENEW`, `Indicator=7.2.1`, `Units=PERCENT`, Herkunft je Beobachtung und die Datenart (`Nature`). Für die Registry ergibt sich:

- aktueller Direktdatensatz: **7.697** numerische Beobachtungen, **231** Länder/Gebiete, 1990–2024,
- WDI: **6.746** Beobachtungen, **212** Länder/Gebiete, 1990–2022,
- **6.746 gemeinsame** Länder-Jahr-Werte,
- **951 zusätzliche Direktwerte**,
- **0 WDI-only-Werte**,
- 2022: 226 direkte Länderwerte gegenüber 71 in WDI,
- 2023: 226 direkte Länderwerte, WDI noch ohne Werte,
- 2024: nur partielle UNSD-Abdeckung; 84 numerische Schätzwerte plus 5 `NA`-Zeilen, ausschließlich aus `Energy Balances, UN Statistics Division (2025)`.

Die aktuelle Direktreihe ist eine gemischte gemeinsame SDG-Reihe: 4.770 gemappte Beobachtungen stammen aus `IEA (2025), World Energy Balances`, 2.927 aus `Energy Balances, UN Statistics Division (2025)`. Alle 7.697 numerischen Direktbeobachtungen sind als `Nature=E` (*Estimated data*) gekennzeichnet.

Der Vergleich bestätigt zugleich erhebliche Revisionen gegenüber dem in WDI verteilten älteren Stand:

- 6.009 der 6.746 gemeinsamen Werte unterscheiden sich um mehr als 0,005 Prozentpunkte,
- 2.001 um mehr als 0,05 Prozentpunkte,
- 1.035 um mehr als 0,5 Prozentpunkte,
- maximale Differenz: Bhutan 2005, direkt 52,19 % gegenüber WDI 88,7 %,
- Nigeria 2014: direkt 49,53 % gegenüber WDI 79,9 %.

Fachlich wäre die aktuelle Tracking-SDG-7-Reihe daher klar aktueller und geografisch vollständiger. **Sie wird dennoch nicht direkt gespiegelt**, weil der Datensatz selbst ausdrücklich festlegt, dass Datei und enthaltene Daten ohne schriftliche Genehmigung von IEA und UNSD weder ganz noch teilweise reproduziert, verbreitet oder übertragen werden dürfen. Für IEA-originäre Werte gelten zusätzlich die IEA-Bedingungen, für UNSD-originäre Werte die UN-Datenbedingungen. Auch die öffentliche UNSD-SDG-API wird nicht als technischer Umweg verwendet, solange keine eigene offene Lizenz nachgewiesen ist, die diese quellenspezifischen Einschränkungen für genau diese Reihe eindeutig aufhebt.

Entscheidung: **WDI bleibt für `EG.FEC.RNEW.ZS` kanonisch und sichtbar.** Hier ist die Distributionsschicht ein echter Mehrwert, weil die World Bank genau diese veröffentlichte WDI-Reihe ausdrücklich unter CC BY 4.0 bereitstellt, während der aktuellere direkte gemeinsame IEA-/UNSD-Datensatz nicht frei redistributierbar ist. Es wird **kein Direktprovider angelegt und keine WDI-Zeile entfernt**. Der Audit wird erneut geöffnet, wenn sich die Lizenzbedingungen der Direktquelle ändern oder WDI einen neueren Revisionsstand übernimmt.

"""

if "### WDI versus Tracking SDG 7 / erneuerbare Energie" not in text:
	text = text.replace(marker, section + marker, 1)

path.write_text(text, encoding="utf-8")
