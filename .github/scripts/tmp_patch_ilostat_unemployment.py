#!/usr/bin/env python3
from pathlib import Path
import json
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text(encoding="utf-8")
marker = '"id": "labour.employment-population-15plus-percent"'
pos = text.index(marker)
start = text.rfind("\t\t{", 0, pos)
if start < 0:
	raise SystemExit("Could not find employment-population object start")

depth = 0
in_string = False
escaped = False
end = None
for index in range(start, len(text)):
	char = text[index]
	if in_string:
		if escaped:
			escaped = False
		elif char == "\\":
			escaped = True
		elif char == '"':
			in_string = False
		continue
	if char == '"':
		in_string = True
	elif char == "{":
		depth += 1
	elif char == "}":
		depth -= 1
		if depth == 0:
			end = index + 1
			break
if end is None:
	raise SystemExit("Could not find employment-population object end")

addition = r''',
		{
			"id": "labour.unemployment-15plus-percent",
			"slug": "labour-unemployment-15plus-percent",
			"sourceDataset": "UNE_2EAP_SEX_AGE_RT_A",
			"filters": {"sex": "SEX_T", "classif1": "AGE_YTHADULT_YGE15"},
			"title": "Arbeitslosenquote (15+)",
			"description": "Anteil der Arbeitslosen an der Erwerbsbevölkerung ab 15 Jahren, beide Geschlechter; ILO-modellierte Schätzung.",
			"unit": {"id": "percent", "label": "Prozent", "symbol": "%"},
			"classification": {"type": "fixed", "breaks": [3, 5, 7, 10, 15, 25]},
			"minAreasWithAnyValue": 185,
			"minAreasInDefaultYear": 180,
			"requiredAreas": ["country:AUT", "country:DEU", "country:USA", "country:IND"]
		},
		{
			"id": "labour.unemployment-youth-15-24-percent",
			"slug": "labour-unemployment-youth-15-24-percent",
			"sourceDataset": "UNE_2EAP_SEX_AGE_RT_A",
			"filters": {"sex": "SEX_T", "classif1": "AGE_YTHADULT_Y15-24"},
			"title": "Jugendarbeitslosenquote (15–24)",
			"description": "Anteil der Arbeitslosen an der Erwerbsbevölkerung im Alter von 15 bis 24 Jahren, beide Geschlechter; ILO-modellierte Schätzung.",
			"unit": {"id": "percent", "label": "Prozent", "symbol": "%"},
			"classification": {"type": "fixed", "breaks": [5, 10, 15, 20, 30, 50]},
			"minAreasWithAnyValue": 185,
			"minAreasInDefaultYear": 180,
			"requiredAreas": ["country:AUT", "country:DEU", "country:USA", "country:IND"]
		}'''

patched = text[:end] + addition + text[end:]
payload = json.loads(patched)
ids = [item["id"] for item in payload["indicators"]]
assert len(ids) == 16
assert ids.count("labour.unemployment-15plus-percent") == 1
assert ids.count("labour.unemployment-youth-15-24-percent") == 1
target.write_text(patched, encoding="utf-8")
