from pathlib import Path

build_path = Path("scripts/build_who.py")
config_path = Path("config/who-indicators.json")

build = build_path.read_text(encoding="utf-8")
old = '''\tvalue_multiplier = float(indicator.get("valueMultiplier", 1.0))
\trequired_fields = {'''
new = '''\tvalue_multiplier = float(indicator.get("valueMultiplier", 1.0))
\tskip_missing_values = bool(indicator.get("skipMissingValues", False))
\trequired_fields = {'''
assert old in build
build = build.replace(old, new, 1)

old = '''\t\tarea_id = area_by_m49[m49]
\t\tvalue = parse_number(round(float(parse_number(row.get(value_field))) * value_multiplier, 12))
\t\tvalidate_value_range(indicator, area_id, year, value, "value")'''
new = '''\t\tarea_id = area_by_m49[m49]
\t\traw_value = row.get(value_field)
\t\tif raw_value is None or str(raw_value).strip() == "":
\t\t\tif skip_missing_values:
\t\t\t\tcontinue
\t\t\traise ValueError("Missing numeric value.")
\t\tvalue = parse_number(round(float(parse_number(raw_value)) * value_multiplier, 12))
\t\tvalidate_value_range(indicator, area_id, year, value, "value")'''
assert old in build
build = build.replace(old, new, 1)
build_path.write_text(build, encoding="utf-8")

config = config_path.read_text(encoding="utf-8")
needle = '''\t\t\t"confidenceIntervals": false,
\t\t\t"startYear": 2010,
\t\t\t"endYear": 2025,
\t\t\t"expectedReferenceYear": 2025,
\t\t\t"title": "HPV-Impfquote Mädchen (9–14)",'''
replacement = '''\t\t\t"confidenceIntervals": false,
\t\t\t"skipMissingValues": true,
\t\t\t"startYear": 2010,
\t\t\t"endYear": 2025,
\t\t\t"expectedReferenceYear": 2025,
\t\t\t"title": "HPV-Impfquote Mädchen (9–14)",'''
assert needle in config
config = config.replace(needle, replacement, 1)
config_path.write_text(config, encoding="utf-8")
