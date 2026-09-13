#!/usr/bin/env python3
from pathlib import Path

SCRIPT_PATH = Path("scripts/build_world_bank_pip.py")
CONFIG_PATH = Path("config/world-bank-pip-indicators.json")


def replace_once(text: str, old: str, new: str, label: str) -> str:
	count = text.count(old)
	if count != 1:
		raise RuntimeError(f"{label}: expected one match, found {count}")
	return text.replace(old, new, 1)


def patch_builder() -> None:
	script = SCRIPT_PATH.read_text(encoding="utf-8")

	script = replace_once(
		script,
		"def pip_url(config: dict[str, Any], version: str, poverty_line: float) -> str:\n",
		"def pip_url(config: dict[str, Any], version: str, poverty_line: float, fill_gaps: bool = True) -> str:\n",
		"pip_url signature",
	)
	script = replace_once(
		script,
		'\t\t"fill_gaps": "true",\n',
		'\t\t"fill_gaps": "true" if fill_gaps else "false",\n',
		"pip_url fill_gaps",
	)
	script = replace_once(
		script,
		"def read_arrow_rows(data: bytes, source: str) -> list[dict[str, Any]]:\n",
		(
			"def read_arrow_rows(\n"
			"\tdata: bytes,\n"
			"\tsource: str,\n"
			"\tminimum_rows: int = 5000,\n"
			"\trequired_extra: set[str] | None = None,\n"
			") -> list[dict[str, Any]]:\n"
		),
		"read_arrow_rows signature",
	)
	script = replace_once(
		script,
		'\t\t"gini",\n',
		'',
		"remove Gini from common Arrow requirements",
	)
	script = replace_once(
		script,
		'\tmissing = required - set(table.column_names)\n',
		'\trequired.update(required_extra or set())\n\tmissing = required - set(table.column_names)\n',
		"Arrow extra requirements",
	)
	script = replace_once(
		script,
		'\tif len(rows) < 5000:\n\t\traise RuntimeError(f"World Bank PIP Arrow response unexpectedly small: {len(rows)} rows")\n',
		(
			'\tif len(rows) < minimum_rows:\n'
			'\t\traise RuntimeError(\n'
			'\t\t\tf"World Bank PIP Arrow response unexpectedly small: {len(rows)} rows; "\n'
			'\t\t\tf"expected at least {minimum_rows}."\n'
			'\t\t)\n'
		),
		"Arrow row threshold",
	)
	script = replace_once(
		script,
		'\t\tfor field in ("mean", "median", "gini", "reporting_pop", "spl", "spr", "pg"):\n',
		'\t\tfor field in ("mean", "median", "reporting_pop", "spl", "spr", "pg"):\n',
		"annual cross-line fields",
	)
	script = replace_once(
		script,
		'\t\t\t"frequency": "annual",\n',
		'\t\t\t"frequency": payload["frequency"],\n',
		"provider-index frequency",
	)

	validation_anchor = (
		'\t\tif derive and derive != "poor-population-millions":\n'
		'\t\t\traise ValueError(f"Unsupported World Bank PIP derivation for {indicator_id}: {derive}")\n'
	)
	validation_replacement = validation_anchor + (
		'\t\tquery_mode = str(indicator.get("queryMode", "")).strip()\n'
		'\t\tif query_mode not in {"", "survey-latest-through-year"}:\n'
		'\t\t\traise ValueError(f"Unsupported World Bank PIP queryMode for {indicator_id}: {query_mode}")\n'
		'\t\tif query_mode == "survey-latest-through-year":\n'
		'\t\t\tif field != "gini":\n'
		'\t\t\t\traise ValueError(f"World Bank PIP survey-latest-through-year requires gini for {indicator_id}.")\n'
		'\t\t\tif str(indicator.get("frequency", "")).strip() != "latest-observation-through-year":\n'
		'\t\t\t\traise ValueError(f"World Bank PIP Gini frequency is invalid for {indicator_id}.")\n'
	)
	script = replace_once(
		script,
		validation_anchor,
		validation_replacement,
		"queryMode validation",
	)

	release_anchor = "\n\ndef release_date_iso(release_version: str) -> str:\n"
	if script.count(release_anchor) != 1:
		raise RuntimeError("release_date_iso anchor not unique")

	functions = r'''


def collect_gini_survey_rows(
	rows: list[dict[str, Any]],
	canonical_rows: dict[tuple[int, str], dict[str, Any]],
	area_by_iso3: dict[str, str],
	aliases: dict[str, str],
	current_year: int,
) -> tuple[dict[tuple[int, str], dict[str, Any]], set[str]]:
	grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
	unresolved: set[str] = set()
	for row in rows:
		if str(row.get("reporting_level", "")).strip().lower() != "national":
			continue
		gini = finite_number(row.get("gini"))
		if gini is None:
			continue
		if not 0 <= gini <= 1:
			raise RuntimeError(f"World Bank PIP Gini outside 0..1: {gini}")
		source_code = str(row.get("country_code", "")).strip().upper()
		if not source_code or source_code in IGNORED_SOURCE_AREAS:
			continue
		iso3 = mapped_iso3(source_code, aliases)
		area_id = area_by_iso3.get(iso3)
		if not area_id:
			unresolved.add(source_code)
			continue
		try:
			year = int(row.get("reporting_year"))
		except (TypeError, ValueError):
			continue
		if year < 1900 or year > current_year:
			continue
		grouped[(year, area_id)].append(row)

	selected: dict[tuple[int, str], dict[str, Any]] = {}
	duplicate_groups = 0
	for key, candidates in grouped.items():
		canonical = canonical_rows.get(key)
		if len(candidates) == 1:
			row = candidates[0]
			if canonical is not None and row.get("welfare_type") != canonical.get("welfare_type"):
				raise RuntimeError(
					f"World Bank PIP Gini welfare type differs from canonical annual series for {key}: "
					f"{row.get('welfare_type')} != {canonical.get('welfare_type')}"
				)
			selected[key] = row
			continue

		duplicate_groups += 1
		if canonical is None:
			raise RuntimeError(f"World Bank PIP Gini duplicate has no canonical annual row: {key}")
		canonical_welfare = canonical.get("welfare_type")
		matches = [row for row in candidates if row.get("welfare_type") == canonical_welfare]
		if len(matches) != 1:
			raise RuntimeError(
				f"World Bank PIP Gini duplicate cannot be resolved by canonical welfare type for {key}: "
				f"welfare={canonical_welfare!r} matches={len(matches)} candidates={len(candidates)}"
			)
		selected[key] = matches[0]

	print(
		f"PIP Gini canonical surveys: observations={len(selected)} "
		f"countries={len({area_id for _year, area_id in selected})} duplicateGroups={duplicate_groups}"
	)
	return selected, unresolved


def gini_metadata_for_row(row: dict[str, Any], source_year: int, target_year: int) -> dict[str, Any]:
	metadata = metadata_for_row(row)
	metadata["sourceYear"] = source_year
	metadata["dataAgeYears"] = target_year - source_year
	metadata["carriedForward"] = target_year != source_year
	for source_key, target_key in (
		("survey_acronym", "surveyAcronym"),
		("survey_comparability", "surveyComparability"),
		("comparable_spell", "comparableSpell"),
	):
		value = str(row.get(source_key, "")).strip()
		if value:
			metadata[target_key] = value
	survey_year = finite_number(row.get("survey_year"))
	if survey_year is not None:
		metadata["surveyYear"] = normalize_number(survey_year, 4)
	if target_year == source_year:
		metadata["sourceNote"] = f"PIP-Datenjahr {source_year}; Originalwert aus Haushaltserhebung, nicht interpoliert."
	else:
		metadata["sourceNote"] = (
			f"PIP-Datenjahr {source_year}; letzter bis einschließlich {target_year} verfügbarer "
			"Survey-Wert, unverändert fortgeführt und nicht interpoliert."
		)
	return metadata


def build_gini_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	survey_rows: dict[tuple[int, str], dict[str, Any]],
	area_by_iso3: dict[str, str],
	version_info: dict[str, str],
) -> dict[str, Any]:
	by_area: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
	for (source_year, area_id), row in survey_rows.items():
		by_area[area_id].append((source_year, row))
	for observations in by_area.values():
		observations.sort(key=lambda item: item[0])

	if len(by_area) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"World Bank PIP indicator {indicator['id']} maps only {len(by_area)} areas; "
			f"expected at least {indicator['minAreasWithAnyValue']}."
		)
	if not survey_rows:
		raise RuntimeError("World Bank PIP Gini has no canonical survey observations.")

	first_source_year = min(year for year, _area_id in survey_rows)
	last_source_year = max(year for year, _area_id in survey_rows)
	release_year = int(version_info["releaseVersion"][:4])
	if release_year < last_source_year:
		raise RuntimeError(
			f"World Bank PIP Gini release year {release_year} precedes latest source year {last_source_year}."
		)
	available_years = list(range(first_source_year, release_year + 1))
	values_by_year: dict[int, dict[str, int | float]] = defaultdict(dict)
	metadata_by_year: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)

	for target_year in available_years:
		for area_id, observations in by_area.items():
			latest: tuple[int, dict[str, Any]] | None = None
			for source_year, row in observations:
				if source_year > target_year:
					break
				latest = (source_year, row)
			if latest is None:
				continue
			source_year, row = latest
			gini = finite_number(row.get("gini"))
			if gini is None or not 0 <= gini <= 1:
				raise RuntimeError(f"Invalid World Bank PIP Gini for {area_id} {source_year}: {gini}")
			values_by_year[target_year][area_id] = normalize_number(gini * float(indicator.get("scale", 1)))
			metadata_by_year[target_year][area_id] = gini_metadata_for_row(row, source_year, target_year)

	required_areas = [str(area_id) for area_id in indicator["requiredAreas"]]
	missing_required_any = [area_id for area_id in required_areas if area_id not in by_area]
	if missing_required_any:
		raise RuntimeError(f"World Bank PIP indicator {indicator['id']} is missing required areas: {missing_required_any}")

	default_year = available_years[-1]
	default_values = values_by_year[default_year]
	min_default = int(indicator["minAreasInDefaultYear"])
	if len(default_values) < min_default or not all(area_id in default_values for area_id in required_areas):
		raise RuntimeError(
			f"World Bank PIP Gini default cutoff {default_year} has {len(default_values)} areas; "
			f"expected at least {min_default} and all required areas."
		)

	available_years = [year for year in available_years if values_by_year[year]]
	sorted_values = {
		str(year): {area_id: values_by_year[year][area_id] for area_id in sorted(values_by_year[year])}
		for year in available_years
	}
	sorted_metadata = {
		str(year): {area_id: metadata_by_year[year][area_id] for area_id in sorted(metadata_by_year[year])}
		for year in available_years
	}
	provider = config["provider"]
	source = {
		"providerId": provider["id"],
		"providerName": provider["name"],
		"dataset": provider["dataset"],
		"version": version_info["version"],
		"releaseVersion": version_info["releaseVersion"],
		"pppVersion": config["pppVersion"],
		"canonicalWelfareQueryPovertyLine": 3.0,
		"fillGaps": False,
		"reportingLevel": "national",
		"selectionPolicy": (
			"Canonical PIP welfare type is used when multiple income/consumption survey distributions "
			"exist for the same country-year."
		),
		"temporalDisplayPolicy": (
			"Each cutoff year shows the latest canonical survey observation with reporting year less "
			"than or equal to that cutoff; values are carried forward unchanged, never interpolated."
		),
		"sourceYearRange": [first_source_year, last_source_year],
		"license": provider["license"],
		"licenseUrl": provider["licenseUrl"],
		"attribution": provider["attribution"],
		"url": config["sourcePage"],
	}
	payload = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"areaLevel": "country",
		"frequency": str(indicator.get("frequency", "latest-observation-through-year")),
		"indicator": {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		},
		"source": source,
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(by_area),
			"latestYear": available_years[-1],
			"areasInLatestYear": len(values_by_year[available_years[-1]]),
			"areasInDefaultYear": len(default_values),
		},
		"values": sorted_values,
		"observationMetadata": sorted_metadata,
	}
	print(
		f"{indicator['id']}: mapped={len(by_area)} sourceYears={first_source_year}-{last_source_year} "
		f"cutoffs={available_years[0]}-{available_years[-1]} defaultYear={default_year} "
		f"defaultCoverage={len(default_values)}"
	)
	return payload
'''
	script = script.replace(release_anchor, functions + release_anchor, 1)

	main_start_marker = '\tmetadata_by_key = {key: metadata_for_row(row) for key, row in base_rows.items()}\n'
	main_end_marker = '\n\thasher = hashlib.sha256()\n'
	start = script.find(main_start_marker)
	end = script.find(main_end_marker, start)
	if start < 0 or end < 0:
		raise RuntimeError(f"Could not locate main build block: start={start}, end={end}")
	new_main = r'''	metadata_by_key = {key: metadata_for_row(row) for key, row in base_rows.items()}
	gini_survey_rows: dict[tuple[int, str], dict[str, Any]] | None = None
	if any(str(indicator.get("queryMode", "")) == "survey-latest-through-year" for indicator in config["indicators"]):
		gini_url = pip_url(config, version_info["version"], 3.0, fill_gaps=False)
		started = time.monotonic()
		data, content_type = fetch_bytes(gini_url, args.timeout, "application/vnd.apache.arrow.file")
		elapsed = time.monotonic() - started
		if content_type != "application/vnd.apache.arrow.file":
			raise RuntimeError(f"Unexpected World Bank PIP Gini Arrow content type: {content_type}")
		survey_rows = read_arrow_rows(data, gini_url, minimum_rows=2000, required_extra={"gini"})
		gini_survey_rows, unresolved = collect_gini_survey_rows(
			survey_rows,
			base_rows,
			area_by_iso3,
			aliases,
			now.year,
		)
		if unresolved:
			raise RuntimeError(f"Unexpected unmapped World Bank PIP Gini source country codes: {sorted(unresolved)}")
		print(
			f"PIP Gini surveys: downloaded={len(data)} bytes rows={len(survey_rows)} "
			f"canonicalCountryYears={len(gini_survey_rows)} seconds={elapsed:.2f}"
		)

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		if str(indicator.get("queryMode", "")) == "survey-latest-through-year":
			if gini_survey_rows is None:
				raise RuntimeError("World Bank PIP Gini survey rows were not loaded.")
			payload = build_gini_payload(
				config,
				indicator,
				gini_survey_rows,
				area_by_iso3,
				version_info,
			)
		else:
			payload = build_indicator_payload(
				config,
				indicator,
				rows_by_line,
				metadata_by_key,
				area_by_iso3,
				version_info,
			)
		indicator_payloads.append((indicator, payload))
'''
	script = script[:start] + new_main + script[end:]
	SCRIPT_PATH.write_text(script, encoding="utf-8")


def patch_config() -> None:
	config = CONFIG_PATH.read_text(encoding="utf-8")
	start_marker = '\t\t{\n\t\t\t"id": "income-inequality.gini",\n'
	end_marker = '\n\t\t}\n\t]\n}\n'
	start = config.find(start_marker)
	end = config.find(end_marker, start)
	if start < 0 or end < 0:
		raise RuntimeError(f"Could not locate Gini config block: start={start}, end={end}")
	end += len('\n\t\t}')
	new_gini = r'''		{
			"id": "income-inequality.gini",
			"slug": "income-inequality-gini",
			"queryMode": "survey-latest-through-year",
			"frequency": "latest-observation-through-year",
			"povertyLine": 3.0,
			"field": "gini",
			"scale": 100,
			"title": "Gini-Koeffizient",
			"description": "Gini-Koeffizient der von PIP kanonisch verwendeten Einkommens- bzw. Konsumverteilung. 0 bedeutet vollständige Gleichheit, 100 maximale Ungleichheit. Für jeden angezeigten Datenstand wird je Land der letzte bis einschließlich dieses Jahres verfügbare PIP-Survey-Wert unverändert verwendet; PIP-Werte werden weder interpoliert noch extrapoliert. Das zugrunde liegende Datenjahr wird je Land ausgewiesen.",
			"unit": {"id": "gini-0-100", "label": "Gini (0–100)"},
			"classification": {"type": "fixed", "breaks": [20, 25, 30, 35, 40, 45]},
			"minAreasWithAnyValue": 160,
			"minAreasInDefaultYear": 160,
			"requiredAreas": ["country:AUT", "country:DEU", "country:USA", "country:IND"]
		}'''
	CONFIG_PATH.write_text(config[:start] + new_gini + config[end:], encoding="utf-8")


def main() -> None:
	patch_builder()
	patch_config()
	print("Patched PIP Gini as latest canonical survey observation through cutoff year.")


if __name__ == "__main__":
	main()
