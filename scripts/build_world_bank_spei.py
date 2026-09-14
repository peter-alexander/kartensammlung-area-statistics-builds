#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "world-bank-spei-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
EXPECTED_SOURCE_INDICATOR = "EN.CLC.SPEI.XD"
EXPECTED_BREAKS = [-2, -1.5, -1, 1, 1.5, 2]
EXPECTED_HISTORICAL_EXCEPTIONS = {"1961": ["VUT"]}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build annual country drought statistics from the World Bank 12-month SPEI series."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def validate_iso3_list(name: str, value: Any) -> list[str]:
	if not isinstance(value, list) or any(not isinstance(item, str) or len(item) != 3 for item in value):
		raise ValueError(f"{name} must be a list of ISO3 codes.")
	normalized = [item.upper() for item in value]
	if normalized != sorted(set(normalized)):
		raise ValueError(f"{name} must be sorted and unique.")
	return normalized


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.world-bank-spei-statistics/v1":
		raise ValueError("Invalid World Bank SPEI statistics config.")
	for key in ("apiBase", "sourceUrl", "metadataUrl", "sourceDatabaseUrl", "licenseUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"World Bank SPEI {key} must use HTTPS.")
	if payload.get("startYear") != 1960:
		raise ValueError("World Bank SPEI startYear must remain the audited 1960.")
	if not isinstance(payload.get("minimumLatestYear"), int) or int(payload["minimumLatestYear"]) < 2023:
		raise ValueError("World Bank SPEI minimumLatestYear must be at least 2023.")
	if payload.get("expectedAreas") != 189:
		raise ValueError("World Bank SPEI expectedAreas must remain the audited 189.")

	missing = validate_iso3_list("expectedMissingIso3", payload.get("expectedMissingIso3"))
	if len(missing) != 61 or 250 - len(missing) != int(payload["expectedAreas"]):
		raise ValueError("World Bank SPEI expectedMissingIso3 must describe exactly 61 of 250 registry areas.")

	historical_exceptions = payload.get("expectedAdditionalMissingByYear")
	if historical_exceptions != EXPECTED_HISTORICAL_EXCEPTIONS:
		raise ValueError(
			"World Bank SPEI expectedAdditionalMissingByYear must remain the audited {'1961': ['VUT']} exception."
		)
	for year_text, codes in historical_exceptions.items():
		if len(year_text) != 4 or not year_text.isdigit():
			raise ValueError(f"Invalid World Bank SPEI historical exception year: {year_text!r}")
		validate_iso3_list(f"expectedAdditionalMissingByYear.{year_text}", codes)
		if any(code in missing for code in codes):
			raise ValueError(f"Historical exception {year_text} duplicates a permanently missing area.")

	required_areas = payload.get("requiredAreas")
	if not isinstance(required_areas, list) or not required_areas:
		raise ValueError("World Bank SPEI requiredAreas is missing.")
	if any(not isinstance(item, str) or not item.startswith("country:") for item in required_areas):
		raise ValueError("World Bank SPEI requiredAreas contains an invalid area id.")
	if "country:XKX" in required_areas:
		raise ValueError("Kosovo must not be required because the audited SPEI source does not cover XKX.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "world-bank-spei":
		raise ValueError("World Bank SPEI provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"World Bank SPEI provider metadata is missing {key}.")
	if provider.get("license") != "CC BY 4.0":
		raise ValueError("World Bank SPEI license changed unexpectedly from the audited DataBank metadata.")

	indicator = payload.get("indicator")
	if not isinstance(indicator, dict):
		raise ValueError("World Bank SPEI indicator metadata is missing.")
	for key in ("id", "slug", "sourceIndicator", "title", "description"):
		if not str(indicator.get(key, "")).strip():
			raise ValueError(f"World Bank SPEI indicator metadata is missing {key}.")
	if indicator.get("sourceIndicator") != EXPECTED_SOURCE_INDICATOR:
		raise ValueError(f"World Bank SPEI sourceIndicator must remain {EXPECTED_SOURCE_INDICATOR}.")
	unit = indicator.get("unit")
	if not isinstance(unit, dict) or unit.get("id") != "standardized-index":
		raise ValueError("World Bank SPEI must use the standardized-index unit.")
	common.validate_classification(str(indicator["id"]), indicator.get("classification"))
	if indicator["classification"].get("breaks") != EXPECTED_BREAKS:
		raise ValueError(f"World Bank SPEI classification must remain {EXPECTED_BREAKS}.")
	if indicator.get("valueRange") != [-10, 10]:
		raise ValueError("World Bank SPEI valueRange must remain [-10, 10].")

	audit_2023 = payload.get("audit2023")
	if not isinstance(audit_2023, dict) or set(audit_2023) != set(required_areas):
		raise ValueError("World Bank SPEI audit2023 must contain exactly all required areas.")
	return payload


def fetch_records(config: dict[str, Any], timeout: int) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
	current_year = datetime.now(timezone.utc).year
	indicator = config["indicator"]
	query = {
		"format": "json",
		"per_page": "20000",
		"page": "1",
		"date": f"{config['startYear']}:{current_year}",
	}
	url = (
		f"{str(config['apiBase']).rstrip('/')}/country/all/indicator/{indicator['sourceIndicator']}"
		f"?{urlencode(query)}"
	)
	payload = common.fetch_json(url, timeout)
	if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[0], dict):
		raise RuntimeError(f"Unexpected World Bank SPEI API response: {url}")
	metadata = payload[0]
	records = payload[1] or []
	if not isinstance(records, list):
		raise RuntimeError("World Bank SPEI API returned an invalid record list.")
	pages = int(metadata.get("pages", 1))
	if pages != 1:
		raise RuntimeError(f"World Bank SPEI API unexpectedly requires {pages} pages with per_page=20000.")
	return [record for record in records if isinstance(record, dict)], metadata, url


def expected_missing_for_year(config: dict[str, Any], year: int) -> list[str]:
	missing = set(str(code) for code in config["expectedMissingIso3"])
	missing.update(str(code) for code in config["expectedAdditionalMissingByYear"].get(str(year), []))
	return sorted(missing)


def load_values(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	timeout: int,
) -> tuple[dict[int, dict[str, int | float]], dict[str, Any]]:
	records, metadata, api_url = fetch_records(config, timeout)
	if not records:
		raise RuntimeError("World Bank SPEI API returned no records.")

	indicator = config["indicator"]
	value_min, value_max = (float(item) for item in indicator["valueRange"])
	start_year = int(config["startYear"])
	minimum_latest_year = int(config["minimumLatestYear"])
	current_year = datetime.now(timezone.utc).year
	values_by_year: dict[int, dict[str, int | float]] = {}
	ignored_iso3: set[str] = set()
	null_records = 0
	aggregate_or_blank_records = 0
	future_records = 0
	retained_source_observations = 0

	for record in records:
		record_indicator = record.get("indicator")
		if isinstance(record_indicator, dict):
			record_code = str(record_indicator.get("id") or "").strip()
			if record_code and record_code != EXPECTED_SOURCE_INDICATOR:
				raise RuntimeError(
					f"Unexpected World Bank SPEI indicator code {record_code!r}; expected {EXPECTED_SOURCE_INDICATOR}."
				)
		value = record.get("value")
		if value is None:
			null_records += 1
			continue
		year_text = str(record.get("date") or "").strip()
		if len(year_text) != 4 or not year_text.isdigit():
			continue
		year = int(year_text)
		if year < start_year:
			raise RuntimeError(f"World Bank SPEI returned a pre-{start_year} value: {year}.")
		if year > current_year:
			future_records += 1
			continue

		iso3 = str(record.get("countryiso3code") or "").strip().upper()
		if len(iso3) != 3:
			aggregate_or_blank_records += 1
			continue
		area_id = area_by_iso3.get(iso3)
		if area_id is None:
			ignored_iso3.add(iso3)
			continue
		number = common.normalize_number(value)
		if not math.isfinite(float(number)) or float(number) < value_min or float(number) > value_max:
			raise RuntimeError(f"World Bank SPEI value outside {value_min}..{value_max}: {iso3} {year} {number}.")
		year_values = values_by_year.setdefault(year, {})
		if area_id in year_values:
			raise RuntimeError(f"Duplicate World Bank SPEI value for {area_id} {year}.")
		year_values[area_id] = number
		retained_source_observations += 1

	if ignored_iso3:
		raise RuntimeError(f"Unexpected unmapped World Bank SPEI ISO3 codes: {sorted(ignored_iso3)}")
	if not values_by_year:
		raise RuntimeError("World Bank SPEI returned no mapped observations.")

	expected_areas = int(config["expectedAreas"])
	expected_missing = list(config["expectedMissingIso3"])
	mapped_areas = {area_id for year_values in values_by_year.values() for area_id in year_values}
	missing_any = sorted(iso3 for iso3, area_id in area_by_iso3.items() if area_id not in mapped_areas)
	if len(mapped_areas) != expected_areas or missing_any != expected_missing:
		raise RuntimeError(
			f"World Bank SPEI all-years coverage changed: mapped={len(mapped_areas)}, missing={missing_any}."
		)

	source_years = sorted(values_by_year)
	if source_years[0] != start_year:
		raise RuntimeError(f"World Bank SPEI starts at {source_years[0]}, expected {start_year}.")
	if source_years != list(range(start_year, source_years[-1] + 1)):
		raise RuntimeError("World Bank SPEI source years are not contiguous.")
	if source_years[-1] < minimum_latest_year:
		raise RuntimeError(
			f"World Bank SPEI latest source year {source_years[-1]} is older than required {minimum_latest_year}."
		)

	required = set(str(area_id) for area_id in config["requiredAreas"])
	published_years: list[int] = []
	incomplete_trailing_years: list[int] = []
	for year in source_years:
		year_values = values_by_year[year]
		missing_year = sorted(iso3 for iso3, area_id in area_by_iso3.items() if area_id not in year_values)
		if year <= minimum_latest_year:
			expected_missing_year = expected_missing_for_year(config, year)
			expected_count = len(area_by_iso3) - len(expected_missing_year)
			if len(year_values) != expected_count or missing_year != expected_missing_year:
				raise RuntimeError(
					f"World Bank SPEI audited year {year} has changed coverage: "
					f"{len(year_values)} areas, missing={missing_year}; "
					f"expected {expected_count}, missing={expected_missing_year}."
				)
			if not required.issubset(year_values):
				raise RuntimeError(f"World Bank SPEI audited year {year} is missing a required regression area.")
			published_years.append(year)
			continue

		complete_new_year = (
			len(year_values) == expected_areas
			and missing_year == expected_missing
			and required.issubset(year_values)
		)
		if complete_new_year:
			if incomplete_trailing_years:
				raise RuntimeError(
					f"World Bank SPEI has a complete year {year} after incomplete trailing years "
					f"{incomplete_trailing_years}."
				)
			published_years.append(year)
		else:
			if not set(year_values).issubset(mapped_areas):
				raise RuntimeError(f"World Bank SPEI trailing year {year} contains an unexpected area.")
			incomplete_trailing_years.append(year)

	if not published_years:
		raise RuntimeError("World Bank SPEI has no publishable years.")
	default_year = published_years[-1]
	if published_years != list(range(start_year, default_year + 1)):
		raise RuntimeError("World Bank SPEI publishable years are not contiguous.")
	published_values = {year: values_by_year[year] for year in published_years}

	if 2023 in published_values:
		for area_id, expected_value in config["audit2023"].items():
			actual = float(published_values[2023][area_id])
			if abs(actual - float(expected_value)) > 1e-10:
				raise RuntimeError(
					f"World Bank SPEI 2023 regression changed for {area_id}: {actual} != {expected_value}."
				)

	published_observations = sum(len(year_values) for year_values in published_values.values())
	return published_values, {
		"apiUrl": api_url,
		"sourceRecords": len(records),
		"apiTotal": int(metadata.get("total", len(records))),
		"nullRecords": null_records,
		"aggregateOrBlankRecords": aggregate_or_blank_records,
		"futureRecordsSkipped": future_records,
		"retainedSourceObservations": retained_source_observations,
		"publishedObservations": published_observations,
		"mappedAreas": len(mapped_areas),
		"sourceFirstYear": source_years[0],
		"sourceLatestYear": source_years[-1],
		"publishedLatestYear": default_year,
		"excludedTrailingYears": incomplete_trailing_years,
		"expectedMissingIso3": expected_missing,
		"expectedAdditionalMissingByYear": config["expectedAdditionalMissingByYear"],
	}


def build_payload(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_year: dict[int, dict[str, int | float]],
	diagnostics: dict[str, Any],
) -> dict[str, Any]:
	provider = config["provider"]
	indicator = config["indicator"]
	available_years = sorted(values_by_year)
	mapped_areas = {area_id for year_values in values_by_year.values() for area_id in year_values}
	default_year = available_years[-1]
	payload = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		},
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"indicator": indicator["sourceIndicator"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourceUrl"],
			"metadataUrl": config["metadataUrl"],
			"sourceDatabaseUrl": config["sourceDatabaseUrl"],
			"apiUrl": diagnostics["apiUrl"],
			"timeScaleMonths": 12,
			"aggregationMethod": "Average",
			"sourceLatestYear": diagnostics["sourceLatestYear"],
			"excludedTrailingYears": diagnostics["excludedTrailingYears"],
			"expectedMissingIso3": diagnostics["expectedMissingIso3"],
			"expectedAdditionalMissingByYear": diagnostics["expectedAdditionalMissingByYear"],
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(mapped_areas),
			"latestYear": default_year,
			"areasInLatestYear": len(values_by_year[default_year]),
			"areasInDefaultYear": len(values_by_year[default_year]),
			"observations": diagnostics["publishedObservations"],
		},
		"values": {
			str(year): {
				area_id: values_by_year[year][area_id]
				for area_id in sorted(values_by_year[year])
			}
			for year in available_years
		},
	}
	print(
		f"{indicator['id']}: published={available_years[0]}-{default_year} "
		f"sourceLatest={diagnostics['sourceLatestYear']} "
		f"excludedTrailing={diagnostics['excludedTrailingYears']} "
		f"latestCoverage={len(values_by_year[default_year])}/{len(area_by_iso3)} "
		f"observations={diagnostics['publishedObservations']}"
	)
	return payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("World Bank SPEI is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	if len(area_by_iso3) != 250:
		raise RuntimeError(f"World Bank SPEI requires the audited 250-area registry, got {len(area_by_iso3)}.")
	print(f"Fetching World Bank SPEI {config['indicator']['sourceIndicator']}")
	values_by_year, diagnostics = load_values(config, area_by_iso3, args.timeout)
	payload = build_payload(config, area_by_iso3, values_by_year, diagnostics)

	hasher = hashlib.sha256()
	hasher.update(str(config["indicator"]["id"]).encode("utf-8"))
	hasher.update(b"\0")
	hasher.update(common.canonical_bytes(payload))
	hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	now = datetime.now(timezone.utc)
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	filename = f"{config['indicator']['slug']}.json"
	common.write_json(release_dir / filename, payload)

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_iso3),
	}
	if registry_source["url"] is None:
		registry_source.pop("url")

	indicator = config["indicator"]
	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"dataset": {
			"url": config["sourceUrl"],
			"metadataUrl": config["metadataUrl"],
			"sourceDatabaseUrl": config["sourceDatabaseUrl"],
			"apiBase": config["apiBase"],
			"sourceIndicator": indicator["sourceIndicator"],
			"sourceRecords": diagnostics["sourceRecords"],
			"apiTotal": diagnostics["apiTotal"],
			"sourceFirstYear": diagnostics["sourceFirstYear"],
			"sourceLatestYear": diagnostics["sourceLatestYear"],
			"publishedLatestYear": diagnostics["publishedLatestYear"],
			"excludedTrailingYears": diagnostics["excludedTrailingYears"],
			"mappedAreas": diagnostics["mappedAreas"],
			"expectedMissingIso3": diagnostics["expectedMissingIso3"],
			"expectedAdditionalMissingByYear": diagnostics["expectedAdditionalMissingByYear"],
			"publishedObservations": diagnostics["publishedObservations"],
			"retainedSourceObservations": diagnostics["retainedSourceObservations"],
			"nullRecords": diagnostics["nullRecords"],
			"aggregateOrBlankRecords": diagnostics["aggregateOrBlankRecords"],
			"futureRecordsSkipped": diagnostics["futureRecordsSkipped"],
		},
		"indicators": [{
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"sourceIndicator": indicator["sourceIndicator"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		}],
		"notes": [
			"Direct World Bank annual country series EN.CLC.SPEI.XD; no interpolation, extrapolation or cross-provider fallback is used.",
			"The World Bank DataBank metadata describes this as the 12-month SPEI time-scale with annual periodicity and Average aggregation; the underlying source is the Global SPEI database (SPEIbase).",
			"Negative SPEI values indicate drier conditions and positive values wetter conditions relative to local normal conditions; values are standardized and therefore comparable through time and space.",
			"The audited historical series has 189 registry areas in every year except 1961, when Vanuatu is absent and coverage is 188; this single source gap is preserved as missing, not interpolated.",
			"Incomplete trailing source years are retained only in source diagnostics and are not published until they reach the normal audited 189-area coverage.",
			"The exact World Bank DataBank metadata currently states CC BY 4.0. The separate Sovereign ESG web interface has displayed different license text; the DataBank metadata URL is retained explicitly so this can be re-audited if World Bank licensing metadata changes.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built World Bank SPEI snapshot {snapshot}")
	print("Indicators: 1")


if __name__ == "__main__":
	main()
