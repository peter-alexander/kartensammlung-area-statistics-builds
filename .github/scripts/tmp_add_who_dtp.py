#!/usr/bin/env python3
from pathlib import Path

CONFIG = Path("config/who-indicators.json")
BUILDER = Path("scripts/build_who.py")
WORKFLOW = Path(".github/workflows/build-who-statistics.yml")
DOCS = Path("docs/statistics-source-policy.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
	count = text.count(old)
	if count != 1:
		raise SystemExit(f"{label}: expected exactly one match, found {count}")
	return text.replace(old, new, 1)


config = CONFIG.read_text(encoding="utf-8")
if '"id": "immunization.dpt-percent"' in config:
	raise SystemExit("WHO DTP indicator already exists")
dtp = '''\t\t{
\t\t\t"id": "immunization.dpt-percent",
\t\t\t"slug": "immunization-dpt-percent",
\t\t\t"sourceIndicator": "WHS4_100",
\t\t\t"sourceUuid": "F8E084C",
\t\t\t"sourceUrl": "https://data.who.int/indicators/i/48D7D19/F8E084C",
\t\t\t"downloadUrl": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/F8E084C_ALL_LATEST.csv",
\t\t\t"valueField": "RATE_PER_100_N",
\t\t\t"confidenceIntervals": false,
\t\t\t"startYear": 1980,
\t\t\t"endYear": 2024,
\t\t\t"fallbackWdiIndicator": "SH.IMM.IDPT",
\t\t\t"title": "DPT-Impfquote",
\t\t\t"description": "Anteil der Einjährigen, die drei Dosen eines Diphtherie-, Tetanus- und Pertussis-haltigen Impfstoffs (DTP3) erhalten haben; offizielle WHO/UNICEF-Schätzung. Direkte WHO-Werte ab 2000 sind kanonisch; die identische WHO-originäre WDI-Reihe ergänzt ausschließlich frühere Jahre und Länder-/Jahrlücken und wird als Fallback markiert.",
\t\t\t"unit": {"id": "percent", "label": "Prozent", "symbol": "%"},
\t\t\t"classification": {"type": "fixed", "breaks": [50, 70, 80, 90, 95, 99]},
\t\t\t"valueRange": [0, 100],
\t\t\t"minAreasWithAnyValue": 180,
\t\t\t"requiredAreas": ["country:AUT", "country:DEU", "country:USA", "country:IND"]
\t\t}
'''
config = replace_once(config, '\t\t}\n\t]\n}\n', '\t\t},\n' + dtp + '\t]\n}\n', "append DTP config")
CONFIG.write_text(config, encoding="utf-8")

builder = BUILDER.read_text(encoding="utf-8")
old = '''\t\tdimension_filters = indicator.get("dimensionFilters", {})
\t\tif not isinstance(dimension_filters, dict) or any(not str(key).strip() or not str(value).strip() for key, value in dimension_filters.items()):
\t\t\traise ValueError(f"WHO indicator {indicator_id} has invalid dimensionFilters.")
\t\tfor field_name in ("valueField", "lowerField", "upperField", "fallbackWdiIndicator"):
'''
new = '''\t\tdimension_filters = indicator.get("dimensionFilters", {})
\t\tif not isinstance(dimension_filters, dict) or any(not str(key).strip() or not str(value).strip() for key, value in dimension_filters.items()):
\t\t\traise ValueError(f"WHO indicator {indicator_id} has invalid dimensionFilters.")
\t\tconfidence_intervals = indicator.get("confidenceIntervals", True)
\t\tif not isinstance(confidence_intervals, bool):
\t\t\traise ValueError(f"WHO indicator {indicator_id} has invalid confidenceIntervals flag.")
\t\tfor field_name in ("valueField", "lowerField", "upperField", "fallbackWdiIndicator"):
'''
builder = replace_once(builder, old, new, "validate confidence flag")

old = '''\tvalue_field = str(indicator.get("valueField", "RATE_PER_100_N"))
\tlower_field = str(indicator.get("lowerField", "RATE_PER_100_NL"))
\tupper_field = str(indicator.get("upperField", "RATE_PER_100_NU"))
\tdimension_filters = {str(key): str(value) for key, value in indicator.get("dimensionFilters", {}).items()}
\trequired_fields = {
\t\t"IND_CODE", "IND_UUID", "DIM_TIME", "DIM_TIME_TYPE", "DIM_GEO_CODE_M49",
\t\t"DIM_GEO_CODE_TYPE", "DIM_PUBLISH_STATE_CODE", "IND_NAME", "GEO_NAME_SHORT",
\t\tvalue_field, lower_field, upper_field, *dimension_filters.keys(),
\t}
'''
new = '''\tvalue_field = str(indicator.get("valueField", "RATE_PER_100_N"))
\thas_confidence_intervals = bool(indicator.get("confidenceIntervals", True))
\tlower_field = str(indicator.get("lowerField", "RATE_PER_100_NL")) if has_confidence_intervals else None
\tupper_field = str(indicator.get("upperField", "RATE_PER_100_NU")) if has_confidence_intervals else None
\tdimension_filters = {str(key): str(value) for key, value in indicator.get("dimensionFilters", {}).items()}
\trequired_fields = {
\t\t"IND_CODE", "IND_UUID", "DIM_TIME", "DIM_TIME_TYPE", "DIM_GEO_CODE_M49",
\t\t"DIM_GEO_CODE_TYPE", "DIM_PUBLISH_STATE_CODE", "IND_NAME", "GEO_NAME_SHORT",
\t\tvalue_field, *dimension_filters.keys(),
\t}
\tif has_confidence_intervals:
\t\trequired_fields.update({str(lower_field), str(upper_field)})
'''
builder = replace_once(builder, old, new, "optional confidence fields")

old = '''\tvalues_by_year: dict[int, dict[str, int | float]] = {}
\tintervals_by_year: dict[int, dict[str, dict[str, int | float]]] = {}
\tignored_m49: set[str] = set()
\tdirect_observations = 0
'''
new = '''\tvalues_by_year: dict[int, dict[str, int | float]] = {}
\tintervals_by_year: dict[int, dict[str, dict[str, int | float]]] = {}
\tignored_m49: set[str] = set()
\tdirect_years: set[int] = set()
\tdirect_observations = 0
'''
builder = replace_once(builder, old, new, "track direct years")

old = '''\t\tvalue = parse_number(row.get(value_field))
\t\tlower = parse_number(row.get(lower_field))
\t\tupper = parse_number(row.get(upper_field))
\t\tvalidate_value_range(indicator, area_id, year, value, "value")
\t\tvalidate_value_range(indicator, area_id, year, lower, "confidence lower bound")
\t\tvalidate_value_range(indicator, area_id, year, upper, "confidence upper bound")
\t\tif not float(lower) <= float(value) <= float(upper):
\t\t\traise RuntimeError(
\t\t\t\tf"WHO confidence interval is invalid for {indicator['id']} {area_id} {year}: "
\t\t\t\tf"{lower}, {value}, {upper}"
\t\t\t)
\t\tyear_values = values_by_year.setdefault(year, {})
\t\tif area_id in year_values:
\t\t\traise RuntimeError(f"Duplicate WHO country value for {indicator['id']} {area_id} {year}.")
\t\tyear_values[area_id] = value
\t\tintervals_by_year.setdefault(year, {})[area_id] = {"lower": lower, "upper": upper}
\t\tdirect_observations += 1
'''
new = '''\t\tvalue = parse_number(row.get(value_field))
\t\tvalidate_value_range(indicator, area_id, year, value, "value")
\t\tinterval = None
\t\tif has_confidence_intervals:
\t\t\tlower = parse_number(row.get(str(lower_field)))
\t\t\tupper = parse_number(row.get(str(upper_field)))
\t\t\tvalidate_value_range(indicator, area_id, year, lower, "confidence lower bound")
\t\t\tvalidate_value_range(indicator, area_id, year, upper, "confidence upper bound")
\t\t\tif not float(lower) <= float(value) <= float(upper):
\t\t\t\traise RuntimeError(
\t\t\t\t\tf"WHO confidence interval is invalid for {indicator['id']} {area_id} {year}: "
\t\t\t\t\tf"{lower}, {value}, {upper}"
\t\t\t\t)
\t\t\tinterval = {"lower": lower, "upper": upper}
\t\tyear_values = values_by_year.setdefault(year, {})
\t\tif area_id in year_values:
\t\t\traise RuntimeError(f"Duplicate WHO country value for {indicator['id']} {area_id} {year}.")
\t\tyear_values[area_id] = value
\t\tif interval is not None:
\t\t\tintervals_by_year.setdefault(year, {})[area_id] = interval
\t\tdirect_years.add(year)
\t\tdirect_observations += 1
'''
builder = replace_once(builder, old, new, "parse optional confidence intervals")

old = '''\t\t"classification": indicator["classification"],
\t\t"confidenceIntervals": {
\t\t\t"available": True,
\t\t\t"lowerField": lower_field,
\t\t\t"upperField": upper_field,
\t\t},
\t}
'''
new = '''\t\t"classification": indicator["classification"],
\t\t"confidenceIntervals": (
\t\t\t{"available": True, "lowerField": lower_field, "upperField": upper_field}
\t\t\tif has_confidence_intervals else {"available": False}
\t\t),
\t}
'''
builder = replace_once(builder, old, new, "indicator confidence metadata")

old = '''\tif len(available_years) == 1:
\t\tsource["referenceYear"] = available_years[0]
\telse:
\t\tsource["timeCoverage"] = {"startYear": available_years[0], "endYear": available_years[-1]}
'''
new = '''\tdirect_available_years = sorted(direct_years)
\tif len(direct_available_years) == 1:
\t\tsource["referenceYear"] = direct_available_years[0]
\telif direct_available_years:
\t\tsource["timeCoverage"] = {"startYear": direct_available_years[0], "endYear": direct_available_years[-1]}
'''
builder = replace_once(builder, old, new, "direct source time coverage")

old = '''\t\t\t"coverage": payload["coverage"],
\t\t\t"confidenceIntervals": True,
\t\t})
'''
new = '''\t\t\t"coverage": payload["coverage"],
\t\t\t"confidenceIntervals": bool(payload["indicator"]["confidenceIntervals"]["available"]),
\t\t})
'''
builder = replace_once(builder, old, new, "index confidence flag")
BUILDER.write_text(builder, encoding="utf-8")

workflow = WORKFLOW.read_text(encoding="utf-8")
workflow = replace_once(workflow, 'assert len(provider["indicators"]) == 6, len(provider["indicators"])', 'assert len(provider["indicators"]) == 7, len(provider["indicators"])', "WHO indicator count")
marker = '''          for indicator_id in annual_ids:
          \titem = by_id[indicator_id]
          \tassert item["frequency"] == "annual", (indicator_id, item["frequency"])
          \tassert item["availableYears"] == list(range(2000, 2022)), (indicator_id, item["availableYears"])
          \tassert item["defaultYear"] == 2021, (indicator_id, item["defaultYear"])
          \tassert item["coverage"]["areasInDefaultYear"] >= 185, (indicator_id, item["coverage"])
          \tassert item["coverage"]["fallbackObservations"] > 0, (indicator_id, item["coverage"])
          \tpayload = json.loads(Path("dist/statistics/who", item["path"]).read_text(encoding="utf-8"))
          \tassert payload["source"]["providerId"] == "who"
          \tassert payload["source"]["fallback"]["providerId"] == "world-bank"
          \tassert payload.get("observationMetadata"), indicator_id
          \tassert payload["confidenceIntervals"]["values"], indicator_id
'''
addition = marker + '''          dtp = by_id["immunization.dpt-percent"]
          assert dtp["frequency"] == "annual"
          assert dtp["availableYears"] == list(range(1980, 2025)), dtp["availableYears"]
          assert dtp["defaultYear"] == 2024, dtp["defaultYear"]
          assert dtp["coverage"]["areasInDefaultYear"] >= 192, dtp["coverage"]
          assert dtp["coverage"]["directObservations"] >= 4750, dtp["coverage"]
          assert dtp["coverage"]["fallbackObservations"] >= 3000, dtp["coverage"]
          assert dtp["confidenceIntervals"] is False
          dtp_payload = json.loads(Path("dist/statistics/who", dtp["path"]).read_text(encoding="utf-8"))
          assert dtp_payload["source"]["providerId"] == "who"
          assert dtp_payload["source"]["fallback"]["indicator"] == "SH.IMM.IDPT"
          assert dtp_payload["source"]["timeCoverage"] == {"startYear": 2000, "endYear": 2024}
          assert dtp_payload["indicator"]["confidenceIntervals"] == {"available": False}
          assert dtp_payload.get("observationMetadata")
'''
workflow = replace_once(workflow, marker, addition, "DTP workflow validation")
WORKFLOW.write_text(workflow, encoding="utf-8")

docs = DOCS.read_text(encoding="utf-8")
marker = "#### Nächste WHO-Prüfungen\n"
section = '''#### DTP3-Impfquote

Direkte WHO-Quelle: World Health Data Hub, `WHS4_100`, UUID `F8E084C`. Die Direktdatei enthält jährliche WHO/UNICEF-Schätzungen für 2000–2024; WDI `SH.IMM.IDPT` reicht zusätzlich bis 1980 zurück.

- 4.756 gemeinsame Länder-Jahr-Werte wurden verglichen.
- **4.756/4.756 Werte sind exakt identisch.**
- WHO direkt deckt im Jahr 2024 193 Länder ab, WDI 192.
- WDI liefert vor allem die Historie 1980–1999 sowie einzelne Länder-/Jahrlücken; WHO direkt enthält zusätzlich Cookinseln und Niue.

Entscheidung: **WHO ist kanonisch.** Die direkte WHO-Reihe wird für 2000–2024 verwendet; WDI ergänzt ausschließlich frühere Jahre und Lücken als explizit markierter Fallback. Die sichtbare WDI-Doppelung wird erst nach erfolgreicher WHO-Produktion entfernt.

'''
if marker not in docs:
	raise SystemExit("DTP docs insertion marker missing")
docs = docs.replace(marker, section + marker, 1)
docs = docs.replace("- DPT-Impfquote,\n", "", 1)
DOCS.write_text(docs, encoding="utf-8")
