#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "faostat-indicators.json"
BUILDER = ROOT / "scripts" / "build_faostat.py"
WORKFLOW = ROOT / ".github" / "workflows" / "build-faostat-statistics.yml"

NEW_DATASETS = [
	{"id":"production-indices","code":"QI","name":"Production Indices","documentationUrl":"https://www.fao.org/faostat/en/#data/QI","bulkUrl":"https://bulks-faostat.fao.org/production/Production_Indices_E_All_Data_(Normalized).zip","dataFile":"Production_Indices_E_All_Data_(Normalized).csv","flagFile":"Production_Indices_E_Flags.csv","minimumRows":1900000,"sourceLabelFields":["Item","Element"]},
	{"id":"livestock-patterns","code":"EK","name":"Livestock Patterns","documentationUrl":"https://www.fao.org/faostat/en/#data/EK","bulkUrl":"https://bulks-faostat.fao.org/production/Environment_LivestockPatterns_E_All_Data_(Normalized).zip","dataFile":"Environment_LivestockPatterns_E_All_Data_(Normalized).csv","flagFile":"Environment_LivestockPatterns_E_Flags.csv","minimumRows":450000,"sourceLabelFields":["Item","Element"]},
	{"id":"pesticides-use","code":"RP","name":"Pesticides Use","documentationUrl":"https://www.fao.org/faostat/en/#data/RP","bulkUrl":"https://bulks-faostat.fao.org/production/Inputs_Pesticides_Use_E_All_Data_(Normalized).zip","dataFile":"Inputs_Pesticides_Use_E_All_Data_(Normalized).csv","flagFile":"Inputs_Pesticides_Use_E_Flags.csv","minimumRows":100000,"sourceLabelFields":["Item","Element"]},
	{"id":"emissions-indicators","code":"EM","name":"Emissions indicators","documentationUrl":"https://www.fao.org/faostat/en/#data/EM","bulkUrl":"https://bulks-faostat.fao.org/production/Climate_change_Emissions_indicators_E_All_Data_(Normalized).zip","dataFile":"Climate_change_Emissions_indicators_E_All_Data_(Normalized).csv","flagFile":"Climate_change_Emissions_indicators_E_Flags.csv","minimumRows":650000,"sourceLabelFields":["Item","Element"]},
]

NEW_INDICATORS = [
	{"id":"production.agriculture-index","slug":"agriculture-production-index","datasetId":"production-indices","sourceFilters":{"Item Code":"2051","Element Code":"432"},"title":"Landwirtschaftliche Produktion (Index)","description":"Index der gesamten landwirtschaftlichen Produktion; Basis 2014–2016 = 100.","sourceUnit":"","unit":{"id":"index-2014-2016-100","label":"Index (2014–2016 = 100)"},"frequency":"annual","classification":{"type":"fixed","breaks":[80,90,100,110,125,150]},"minAreasWithAnyValue":195,"minAreasInDefaultYear":190,"minimumLatestYear":2024,"minimumDefaultYear":2024,"requiredAreas":["country:AUT","country:DEU","country:USA"],"valueRange":[0,1000]},
	{"id":"production.food-per-capita-index","slug":"food-production-per-capita-index","datasetId":"production-indices","sourceFilters":{"Item Code":"2054","Element Code":"434"},"title":"Nahrungsmittelproduktion je Einwohner (Index)","description":"Index der Nahrungsmittelproduktion je Einwohner; Basis 2014–2016 = 100.","sourceUnit":"","unit":{"id":"index-2014-2016-100","label":"Index (2014–2016 = 100)"},"frequency":"annual","classification":{"type":"fixed","breaks":[75,85,95,105,120,140]},"minAreasWithAnyValue":195,"minAreasInDefaultYear":190,"minimumLatestYear":2024,"minimumDefaultYear":2024,"requiredAreas":["country:AUT","country:DEU","country:USA"],"valueRange":[0,2000]},
	{"id":"livestock.livestock-units-per-agricultural-land","slug":"livestock-units-per-agricultural-land","datasetId":"livestock-patterns","sourceFilters":{"Item Code":"1752","Element Code":"7213"},"title":"Viehdichte","description":"Vieheinheiten der wichtigsten Nutztierarten je Hektar Landwirtschaftsfläche.","sourceUnit":"LSU/ha","unit":{"id":"livestock-units-per-ha","label":"Vieheinheiten je Hektar","symbol":"LSU/ha"},"frequency":"annual","classification":{"type":"fixed","breaks":[0.1,0.25,0.5,1,2,4]},"minAreasWithAnyValue":195,"minAreasInDefaultYear":190,"minimumLatestYear":2023,"minimumDefaultYear":2023,"requiredAreas":["country:AUT","country:DEU","country:USA"],"valueRange":[0,100]},
	{"id":"inputs.pesticides-per-cropland","slug":"pesticides-per-cropland","datasetId":"pesticides-use","sourceFilters":{"Item Code":"1357","Element Code":"5159"},"title":"Pestizideinsatz je Anbaufläche","description":"Gesamter landwirtschaftlicher Pestizideinsatz je Hektar Cropland.","sourceUnit":"kg/ha","unit":{"id":"kg-per-ha","label":"kg je Hektar","symbol":"kg/ha"},"frequency":"annual","classification":{"type":"fixed","breaks":[0.1,0.5,1,2,5,15]},"minAreasWithAnyValue":190,"minAreasInDefaultYear":190,"minimumLatestYear":2024,"minimumDefaultYear":2024,"requiredAreas":["country:AUT","country:DEU","country:USA"],"valueRange":[0,50]},
	{"id":"emissions.agrifood-per-capita","slug":"agrifood-emissions-per-capita","datasetId":"emissions-indicators","sourceFilters":{"Item Code":"6518","Element Code":"7279"},"title":"Agrifood-Emissionen pro Kopf","description":"Treibhausgasemissionen des gesamten Agrar- und Ernährungssystems pro Einwohner, in CO₂-Äquivalenten nach AR5.","sourceUnit":"t CO2eq/cap","unit":{"id":"tonnes-co2e-per-capita","label":"Tonnen CO₂e pro Einwohner","symbol":"t CO₂e/Kopf"},"frequency":"annual","classification":{"type":"fixed","breaks":[0.5,1,1.5,2.5,5,10]},"minAreasWithAnyValue":198,"minAreasInDefaultYear":195,"minimumLatestYear":2023,"minimumDefaultYear":2023,"requiredAreas":["country:AUT","country:DEU","country:USA"],"valueRange":[0,50]},
	{"id":"emissions.agrifood-share-national","slug":"agrifood-emissions-share-national","datasetId":"emissions-indicators","sourceFilters":{"Item Code":"6518","Element Code":"726313"},"title":"Anteil der Agrifood-Emissionen","description":"Anteil der Treibhausgasemissionen des Agrar- und Ernährungssystems an den nationalen Gesamtemissionen einschließlich LULUCF; Werte können durch Netto-Senken negativ oder über 100 % sein.","sourceUnit":"%","unit":{"id":"percent","label":"Prozent","symbol":"%"},"frequency":"annual","minAreasWithAnyValue":198,"minAreasInDefaultYear":195,"minimumLatestYear":2023,"minimumDefaultYear":2023,"requiredAreas":["country:AUT","country:DEU","country:USA"],"valueRange":[-10000,5000]},
	{"id":"emissions.farm-gate-per-production-value","slug":"farm-gate-emissions-per-production-value","datasetId":"emissions-indicators","sourceFilters":{"Item Code":"6996","Element Code":"72791"},"title":"Farm-Gate-Emissionsintensität","description":"Treibhausgasemissionen am Farm Gate je internationalem Dollar landwirtschaftlichen Produktionswerts, in CO₂-Äquivalenten nach AR5.","sourceUnit":"kg CO2eq/Int$","unit":{"id":"kg-co2e-per-intl-dollar","label":"kg CO₂e je internationalem Dollar","symbol":"kg CO₂e/Int$"},"frequency":"annual","classification":{"type":"fixed","breaks":[0.5,1,1.5,2.5,5,10]},"minAreasWithAnyValue":190,"minAreasInDefaultYear":188,"minimumLatestYear":2023,"minimumDefaultYear":2023,"requiredAreas":["country:AUT","country:DEU","country:USA"],"valueRange":[0,100]},
]


def append_objects(raw: str, key: str, objects: list[dict]) -> str:
	marker = f'"{key}": ['
	start = raw.index(marker) + len(marker)
	depth = 1
	in_string = False
	escaped = False
	end = None
	for index in range(start, len(raw)):
		ch = raw[index]
		if in_string:
			if escaped:
				escaped = False
			elif ch == "\\":
				escaped = True
			elif ch == '"':
				in_string = False
			continue
		if ch == '"':
			in_string = True
		elif ch == '[':
			depth += 1
		elif ch == ']':
			depth -= 1
			if depth == 0:
				end = index
				break
	if end is None:
		raise RuntimeError(f"Could not find closing array for {key}")
	items = ",\n".join("\t\t" + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) for obj in objects)
	prefix = raw[:end].rstrip()
	separator = ",\n" if not prefix.endswith("[") else "\n"
	return prefix + separator + items + "\n\t" + raw[end:]


def main() -> None:
	raw = CONFIG.read_text(encoding="utf-8")
	parsed = json.loads(raw)
	existing_datasets = {item["id"] for item in parsed["datasets"]}
	existing_indicators = {item["id"] for item in parsed["indicators"]}
	if existing_datasets.intersection(item["id"] for item in NEW_DATASETS):
		raise SystemExit("Batch 3 dataset already present")
	if existing_indicators.intersection(item["id"] for item in NEW_INDICATORS):
		raise SystemExit("Batch 3 indicator already present")
	raw = append_objects(raw, "datasets", NEW_DATASETS)
	raw = append_objects(raw, "indicators", NEW_INDICATORS)
	updated = json.loads(raw)
	if len(updated["datasets"]) != 9 or len(updated["indicators"]) != 25:
		raise SystemExit(f"Unexpected config sizes: datasets={len(updated['datasets'])} indicators={len(updated['indicators'])}")
	CONFIG.write_text(raw, encoding="utf-8")

	builder = BUILDER.read_text(encoding="utf-8")
	old = 'for key in ("id", "slug", "datasetId", "title", "description", "sourceUnit", "frequency"):\n\t\t\tif not str(indicator.get(key, "")).strip():\n\t\t\t\traise ValueError(f"FAOSTAT indicator entry is missing {key}.")'
	new = 'for key in ("id", "slug", "datasetId", "title", "description", "frequency"):\n\t\t\tif not str(indicator.get(key, "")).strip():\n\t\t\t\traise ValueError(f"FAOSTAT indicator entry is missing {key}.")\n\t\tif "sourceUnit" not in indicator or not isinstance(indicator["sourceUnit"], str):\n\t\t\traise ValueError(f"FAOSTAT indicator {indicator.get(\'id\', \'<unknown>\')} has invalid sourceUnit.")'
	if old not in builder:
		raise SystemExit("Builder validation block not found")
	BUILDER.write_text(builder.replace(old, new, 1), encoding="utf-8")

	workflow = WORKFLOW.read_text(encoding="utf-8")
	workflow = workflow.replace('len(indicators) != 18 or len(configured_indicators) != 18', 'len(indicators) != 25 or len(configured_indicators) != 25')
	workflow = workflow.replace('Expected 18 FAOSTAT indicators', 'Expected 25 FAOSTAT indicators')
	old_set = 'expected_datasets = {"food-security", "healthy-diet", "land-use", "fertilizers-nutrient", "temperature-change"}'
	new_set = 'expected_datasets = {"food-security", "healthy-diet", "land-use", "fertilizers-nutrient", "temperature-change", "production-indices", "livestock-patterns", "pesticides-use", "emissions-indicators"}'
	if old_set not in workflow:
		raise SystemExit("Workflow dataset set not found")
	workflow = workflow.replace(old_set, new_set, 1)
	WORKFLOW.write_text(workflow, encoding="utf-8")

	# Validate generated product files before removing temporary helpers.
	json.loads(CONFIG.read_text(encoding="utf-8"))
	print("Applied FAOSTAT batch 3: 9 datasets, 25 indicators")


if __name__ == "__main__":
	main()
