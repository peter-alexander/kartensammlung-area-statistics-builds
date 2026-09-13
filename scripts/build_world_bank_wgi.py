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
DEFAULT_CONFIG = ROOT / "config" / "world-bank-wgi-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
EXPECTED_SOURCE_CODES = {
	"GOV_WGI_VA_SC",
	"GOV_WGI_PV_SC",
	"GOV_WGI_GE_SC",
	"GOV_WGI_RQ_SC",
	"GOV_WGI_RL_SC",
	"GOV_WGI_CC_SC",
}
EXPECTED_BREAKS = [20, 35, 50, 65, 80, 90]


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build country governance statistics from the World Bank Worldwide Governance Indicators."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=90)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.world-bank-wgi-statistics/v1":
		raise ValueError("Invalid World Bank WGI statistics config.")
	for key in ("apiBase", "sourceUrl", "catalogUrl", "methodologyUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"World Bank WGI {key} must use HTTPS.")
	if payload.get("release") != "2025 Revision":
		raise ValueError("World Bank WGI release must remain the audited 2025 Revision.")
	if payload.get("minYear") != 1996:
		raise ValueError("World Bank WGI minYear must remain 1996.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "world-bank-wgi":
		raise ValueError("World Bank WGI provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"World Bank WGI provider metadata is missing {key}.")
	if provider.get("license") != "CC BY 4.0":
		raise ValueError("World Bank WGI license changed unexpectedly.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 6:
		raise ValueError("World Bank WGI config requires exactly six indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	source_codes: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("World Bank WGI indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"World Bank WGI indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		source_code = str(indicator["sourceIndicator"])
		if indicator_id in ids or slug in slugs or source_code in source_codes:
			raise ValueError(f"Duplicate World Bank WGI indicator metadata: {indicator_id}.")
		ids.add(indicator_id)
		slugs.add(slug)
		source_codes.add(source_code)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or unit.get("id") != "score-0-100":
			raise ValueError(f"World Bank WGI indicator {indicator_id} must use score-0-100.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		classification = indicator["classification"]
		if classification.get("breaks") != EXPECTED_BREAKS:
			raise ValueError(f"World Bank WGI indicator {indicator_id} must use shared fixed breaks {EXPECTED_BREAKS}.")
		value_range = indicator.get("valueRange")
		if value_range != [0, 100]:
			raise ValueError(f"World Bank WGI indicator {indicator_id} must use valueRange [0, 100].")
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear", "minimumObservations", "minimumLatestYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"World Bank WGI indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"World Bank WGI indicator {indicator_id} requires requiredAreas.")

	if source_codes != EXPECTED_SOURCE_CODES:
		raise ValueError(
			f"Unexpected World Bank WGI source indicators: {sorted(source_codes)}; "
			f"expected {sorted(EXPECTED_SOURCE_CODES)}."
		)
	return payload


def fetch_records(api_base: str, path: str, timeout: int) -> list[dict[str, Any]]:
	query = {
		"format": "json",
		"per_page": "20000",
		"page": "1",
	}
	all_records: list[dict[str, Any]] = []
	page = 1
	while True:
		query["page"] = str(page)
		url = f"{api_base.rstrip('/')}/{path}?{urlencode(query)}"
		payload = common.fetch_json(url, timeout)
		if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[0], dict):
			raise RuntimeError(f"Unexpected World Bank WGI API response: {url}")
		metadata = payload[0]
		records = payload[1] or []
		if not isinstance(records, list):
			raise RuntimeError(f"Unexpected World Bank WGI record list: {url}")
		if int(metadata.get("page", page)) != page:
			raise RuntimeError(f"World Bank WGI pagination mismatch for {path}: expected page {page}.")
		all_records.extend(record for record in records if isinstance(record, dict))
		pages = int(metadata.get("pages", 1))
		if pages < 1:
			raise RuntimeError(f"World Bank WGI returned invalid page count for {path}: {pages}")
		if page >= pages:
			break
		page += 1
	return all_records


def load_indicator_values(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_iso3: dict[str, str],
	timeout: int,
) -> tuple[dict[int, dict[str, int | float]], dict[str, Any]]:
	api_base = str(config["apiBase"])
	source_code = str(indicator["sourceIndicator"])
	records = fetch_records(api_base, f"country/all/indicator/{source_code}", timeout)
	if not records:
		raise RuntimeError(f"World Bank WGI returned no records for {source_code}.")

	values_by_year: dict[int, dict[str, int | float]] = {}
	mapped_areas: set[str] = set()
	ignored_codes: set[str] = set()
	forecast_records = 0
	future_records = 0
	null_records = 0
	retained_records = 0
	current_year = datetime.now(timezone.utc).year
	min_year = int(config["minYear"])
	value_min, value_max = (float(value) for value in indicator["valueRange"])

	for record in records:
		record_indicator = record.get("indicator")
		if isinstance(record_indicator, dict):
			record_code = str(record_indicator.get("id") or "").strip()
			if record_code and record_code != source_code:
				raise RuntimeError(
					f"Unexpected indicator code in World Bank WGI response: {record_code}; expected {source_code}."
				)
		value = record.get("value")
		if value is None:
			null_records += 1
			continue
		if str(record.get("obs_status") or "").strip().upper() == "F":
			forecast_records += 1
			continue
		iso3 = str(record.get("countryiso3code") or "").strip().upper()
		if iso3 not in area_by_iso3:
			if iso3:
				ignored_codes.add(iso3)
			continue
		year_text = str(record.get("date") or "").strip()
		if len(year_text) != 4 or not year_text.isdigit():
			continue
		year = int(year_text)
		if year < min_year:
			raise RuntimeError(f"World Bank WGI returned pre-{min_year} observation for {source_code}: {iso3} {year}.")
		if year > current_year:
			future_records += 1
			continue
		number = common.normalize_number(value)
		if not math.isfinite(float(number)) or float(number) < value_min or float(number) > value_max:
			raise RuntimeError(
				f"World Bank WGI value outside configured range for {source_code}: {iso3} {year} {number}."
			)
		area_id = area_by_iso3[iso3]
		year_values = values_by_year.setdefault(year, {})
		if area_id in year_values:
			raise RuntimeError(f"Duplicate World Bank WGI value for {source_code} {area_id} {year}.")
		year_values[area_id] = number
		mapped_areas.add(area_id)
		retained_records += 1

	if not values_by_year:
		raise RuntimeError(f"World Bank WGI returned no mapped observations for {source_code}.")
	if ignored_codes:
		raise RuntimeError(f"Unexpected unmapped World Bank WGI ISO3 codes for {source_code}: {sorted(ignored_codes)}")
	if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"World Bank WGI coverage too small for {source_code}: {len(mapped_areas)} mapped areas."
		)
	if retained_records < int(indicator["minimumObservations"]):
		raise RuntimeError(
			f"World Bank WGI observation count too small for {source_code}: {retained_records}."
		)

	available_years = sorted(values_by_year)
	if available_years[0] != min_year:
		raise RuntimeError(
			f"World Bank WGI history for {source_code} starts at {available_years[0]}, expected {min_year}."
		)
	latest_year = available_years[-1]
	if latest_year < int(indicator["minimumLatestYear"]):
		raise RuntimeError(
			f"World Bank WGI latest year too old for {source_code}: {latest_year}."
		)

	return values_by_year, {
		"sourceRecords": len(records),
		"retainedObservations": retained_records,
		"nullRecords": null_records,
		"forecastRecordsSkipped": forecast_records,
		"futureRecordsSkipped": future_records,
		"mappedAreas": len(mapped_areas),
		"firstYear": available_years[0],
		"latestYear": latest_year,
		"ignoredIso3Codes": sorted(ignored_codes),
	}


def choose_default_year(
	indicator: dict[str, Any],
	values_by_year: dict[int, dict[str, int | float]],
) -> int:
	minimum = int(indicator["minAreasInDefaultYear"])
	required = set(str(area_id) for area_id in indicator["requiredAreas"])
	eligible = [
		year
		for year in sorted(values_by_year)
		if len(values_by_year[year]) >= minimum and required.issubset(values_by_year[year])
	]
	if not eligible:
		raise RuntimeError(
			f"World Bank WGI has no sufficiently covered default year for {indicator['id']} "
			f"with at least {minimum} areas and all required countries."
		)
	return eligible[-1]


def build_indicator_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_year: dict[int, dict[str, int | float]],
	diagnostics: dict[str, Any],
) -> dict[str, Any]:
	provider = config["provider"]
	available_years = sorted(values_by_year)
	mapped_areas = {area_id for mapped in values_by_year.values() for area_id in mapped}
	default_year = choose_default_year(indicator, values_by_year)
	latest_year = available_years[-1]
	api_url = (
		f"{str(config['apiBase']).rstrip('/')}/country/all/indicator/{indicator['sourceIndicator']}"
		"?format=json&per_page=20000"
	)
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
			"release": config["release"],
			"indicator": indicator["sourceIndicator"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourceUrl"],
			"catalogUrl": config["catalogUrl"],
			"methodologyUrl": config["methodologyUrl"],
			"apiUrl": api_url,
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(mapped_areas),
			"latestYear": latest_year,
			"areasInLatestYear": len(values_by_year[latest_year]),
			"areasInDefaultYear": len(values_by_year[default_year]),
			"observations": int(diagnostics["retainedObservations"]),
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
		f"{indicator['id']}: observations={diagnostics['retainedObservations']} "
		f"mapped={len(mapped_areas)} years={available_years[0]}-{latest_year} "
		f"latestCoverage={len(values_by_year[latest_year])} "
		f"defaultYear={default_year} defaultCoverage={len(values_by_year[default_year])}"
	)
	return payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("World Bank WGI is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		print(f"Fetching {indicator['id']} ({indicator['sourceIndicator']})")
		values_by_year, diagnostics = load_indicator_values(config, indicator, area_by_iso3, args.timeout)
		payload = build_indicator_payload(config, indicator, area_by_iso3, values_by_year, diagnostics)
		indicator_payloads.append((indicator, payload, diagnostics))

	hasher = hashlib.sha256()
	for indicator, payload, _diagnostics in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(common.canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	now = datetime.now(timezone.utc)
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []
	dataset_indicators: dict[str, Any] = {}
	for indicator, payload, diagnostics in indicator_payloads:
		filename = f"{indicator['slug']}.json"
		common.write_json(release_dir / filename, payload)
		index_indicators.append({
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
		})
		dataset_indicators[str(indicator["sourceIndicator"])] = diagnostics

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_iso3),
	}
	if registry_source["url"] is None:
		registry_source.pop("url")

	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"dataset": {
			"url": config["sourceUrl"],
			"catalogUrl": config["catalogUrl"],
			"methodologyUrl": config["methodologyUrl"],
			"apiBase": config["apiBase"],
			"release": config["release"],
			"indicators": dataset_indicators,
		},
		"indicators": index_indicators,
		"notes": [
			"Direct World Bank Worldwide Governance Indicators absolute governance scores on the fixed 0–100 scale; higher scores indicate better governance outcomes.",
			"The 2025 WGI methodology revision recalculated the historical series back to 1996 for consistency; older WGI vintages must not be spliced into this release.",
			"WGI are perception-based composite governance indicators. They are useful for broad comparisons and research, but are not definitive institutional rankings.",
			"No fallback, interpolation or extrapolation is used.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built World Bank WGI snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
