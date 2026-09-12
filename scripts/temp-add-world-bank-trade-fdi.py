#!/usr/bin/env python3
from pathlib import Path

PATH = Path("config/world-bank-indicators.json")
text = PATH.read_text(encoding="utf-8")

if '"trade.exports-percent-gdp"' in text:
	raise SystemExit("Trade/FDI batch already present")

anchor = '\n\t]\n}\n'
if anchor not in text:
	raise SystemExit("World Bank config closing anchor not found")

addition = ''',
\t\t{"id":"trade.exports-percent-gdp","slug":"trade-exports-percent-gdp","sourceIndicator":"NE.EXP.GNFS.ZS","title":"Exporte in % des BIP","description":"Exporte von Gütern und Dienstleistungen in Prozent des Bruttoinlandsprodukts.","unit":{"id":"percent-of-gdp","label":"Prozent des BIP","symbol":"%"},"classification":{"type":"fixed","breaks":[15,25,40,60,80,120]},"minAreasWithAnyValue":180,"maxDefaultYearAge":3,"requiredAreas":["country:AUT","country:DEU","country:USA","country:IND"]},
\t\t{"id":"trade.imports-percent-gdp","slug":"trade-imports-percent-gdp","sourceIndicator":"NE.IMP.GNFS.ZS","title":"Importe in % des BIP","description":"Importe von Gütern und Dienstleistungen in Prozent des Bruttoinlandsprodukts.","unit":{"id":"percent-of-gdp","label":"Prozent des BIP","symbol":"%"},"classification":{"type":"fixed","breaks":[15,25,40,60,80,120]},"minAreasWithAnyValue":180,"maxDefaultYearAge":3,"requiredAreas":["country:AUT","country:DEU","country:USA","country:IND"]},
\t\t{"id":"investment.fdi-net-inflows-percent-gdp","slug":"investment-fdi-net-inflows-percent-gdp","sourceIndicator":"BX.KLT.DINV.WD.GD.ZS","title":"Ausländische Direktinvestitionen – Nettozuflüsse","description":"Nettozuflüsse ausländischer Direktinvestitionen in die berichtende Volkswirtschaft in Prozent des BIP; negative Werte bedeuten Netto-Desinvestition.","unit":{"id":"percent-of-gdp","label":"Prozent des BIP","symbol":"%"},"classification":{"type":"fixed","breaks":[-2,0,2,5,10,25]},"minAreasWithAnyValue":170,"maxDefaultYearAge":4,"requiredAreas":["country:AUT","country:DEU","country:USA","country:IND"]},
\t\t{"id":"investment.fdi-net-outflows-percent-gdp","slug":"investment-fdi-net-outflows-percent-gdp","sourceIndicator":"BM.KLT.DINV.WD.GD.ZS","title":"Direktinvestitionen ins Ausland – Nettoabflüsse","description":"Nettoabflüsse von Direktinvestitionen aus der berichtenden Volkswirtschaft in den Rest der Welt in Prozent des BIP; negative Werte bedeuten Netto-Rückflüsse beziehungsweise Desinvestition.","unit":{"id":"percent-of-gdp","label":"Prozent des BIP","symbol":"%"},"classification":{"type":"fixed","breaks":[-2,0,1,3,7,15]},"minAreasWithAnyValue":150,"maxDefaultYearAge":4,"requiredAreas":["country:AUT","country:DEU","country:USA","country:IND"]}'''

PATH.write_text(text.replace(anchor, addition + anchor, 1), encoding="utf-8")
print("Added four World Bank trade/FDI indicators")
