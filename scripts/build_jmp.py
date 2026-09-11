#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
from typing import Any

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "jmp-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
EXPECTED_SERIES_DIMENSIONS = ["REF_AREA", "INDICATOR", "SERVICE_TYPE", "WEALTH_QUINTILE", "RESIDENCE"]
EXPECTED_OBSERVATION_DIMENSIONS = ["TIME_PERIOD"]


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build country statistics from WHO/UNICEF JMP household WASH SDMX data.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.jmp-statistics/v1":
		raise ValueError("Invalid JMP statistics config.")
	api_url = str(payload.get("apiUrl", "")).strip()
	if not api_url.startswith("https://"):
		raise ValueError("JMP apiUrl must use HTTPS.")
	provider = payload.get("provider")
	if not isinstance(provider, dict):
		raise ValueError("JMP provider metadata is required.")
	for key in ("id", "name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"JMP provider metadata is missing {key}.")
	if provider.get("id") != "jmp":
		raise ValueError("JMP provider id must be 'jmp'.")
	dataflow = payload.get("dataflow")
	if not isinstance(dataflow, dict):
		raise ValueError("JMP dataflow metadata is required.")
	for key in ("agency", "id", "version"):
		if not str(dataflow.get(key, "")).strip():
			raise ValueError(f"JMP dataflow metadata is missing {key}.")
	expected_start = payload.get("expectedStartYear")
	minimum_latest = payload.get("minimumLatestYear")
	if not isinstance(expected_start, int) or not 1900 <= expected_start <= 2200:
		raise ValueError("JMP expectedStartYear is invalid.")
	if not isinstance(minimum_latest, int) or minimum_latest < expected_start:
		raise ValueError("JMP minimumLatestYear is invalid.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("JMP config requires indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	source_indicators: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("JMP indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "serviceType", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"JMP indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		source_indicator = str(indicator["sourceIndicator"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate JMP indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate JMP indicator slug: {slug}")
		if source_indicator in source_indicators:
			raise ValueError(f"Duplicate JMP source indicator: {source_indicator}")
		ids.add(indicator_id)
		slugs.add(slug)
		source_indicators.add(source_indicator)
		if indicator["serviceType"] not in ("WAT", "SAN", "HYG"):
			raise ValueError(f"JMP indicator {indicator_id} has invalid serviceType.")
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or unit.get("id") != "percent" or unit.get("label") != "%":
			raise ValueError(f"JMP indicator {indicator_id} must use percent units.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInLatestYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"JMP indicator {indicator_id} has invalid {key}.")
	return payload


def structure_values(dimensions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
	result: dict[str, list[dict[str, Any]]] = {}
	for dimension in dimensions:
		dimension_id = str(dimension.get("id", "")).strip()
		values = dimension.get("values")
		if not dimension_id or not isinstance(values, list):
			raise RuntimeError("Unexpected JMP SDMX dimension structure.")
		result[dimension_id] = values
	return result


def value_ids(values: dict[str, list[dict[str, Any]]], dimension_id: str) -> list[str]:
	return [str(item.get("id", "")).strip() for item in values[dimension_id]]


def value_names(values: dict[str, list[dict[str, Any]]], dimension_id: str) -> dict[str, str]:
	return {
		str(item.get("id", "")).strip(): str(item.get("name", "")).strip()
		for item in values[dimension_id]
	}


def parse_percentage(raw: Any) -> int | float:
	value = common.normalize_number(raw)
	number = float(value)
	if number < -0.000001 or number > 100.000001:
		raise RuntimeError(f"JMP percentage outside 0-100 range: {value}")
	number = min(100.0, max(0.0, number))
	if number.is_integer():
		return int(number)
	return number


def build_payloads(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	api_payload: Any,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
	if not isinstance(api_payload, dict):
		raise RuntimeError("Unexpected JMP SDMX response.")
	root = api_payload.get("data", api_payload)
	if not isinstance(root, dict):
		raise RuntimeError("Unexpected JMP SDMX data envelope.")
	structure = root.get("structure")
	datasets = root.get("dataSets")
	if not isinstance(structure, dict) or not isinstance(datasets, list) or len(datasets) != 1:
		raise RuntimeError("Unexpected JMP SDMX response structure.")
	dimensions = structure.get("dimensions")
	if not isinstance(dimensions, dict):
		raise RuntimeError("JMP SDMX dimensions are missing.")
	series_dimensions = dimensions.get("series")
	observation_dimensions = dimensions.get("observation")
	if not isinstance(series_dimensions, list) or not isinstance(observation_dimensions, list):
		raise RuntimeError("JMP SDMX dimensions are invalid.")
	series_ids = [str(item.get("id", "")).strip() for item in series_dimensions]
	observation_ids = [str(item.get("id", "")).strip() for item in observation_dimensions]
	if series_ids != EXPECTED_SERIES_DIMENSIONS:
		raise RuntimeError(f"JMP series dimensions changed: {series_ids}")
	if observation_ids != EXPECTED_OBSERVATION_DIMENSIONS:
		raise RuntimeError(f"JMP observation dimensions changed: {observation_ids}")

	all_dimensions = series_dimensions + observation_dimensions
	values = structure_values(all_dimensions)
	ids_by_dimension = {dimension_id: value_ids(values, dimension_id) for dimension_id in values}
	indicator_names = value_names(values, "INDICATOR")
	time_values = ids_by_dimension["TIME_PERIOD"]
	if str(config["expectedStartYear"]) not in time_values:
		raise RuntimeError(f"JMP expected start year {config['expectedStartYear']} is missing.")
	if not time_values or not all(item.isdigit() and len(item) == 4 for item in time_values):
		raise RuntimeError("JMP TIME_PERIOD values are not annual years.")
	latest_source_year = max(int(item) for item in time_values)
	if latest_source_year < int(config["minimumLatestYear"]):
		raise RuntimeError(
			f"JMP source is unexpectedly old: latest year {latest_source_year}, "
			f"expected at least {config['minimumLatestYear']}."
		)

	indicator_by_source = {str(item["sourceIndicator"]): item for item in config["indicators"]}
	missing_source_indicators = sorted(set(indicator_by_source) - set(ids_by_dimension["INDICATOR"]))
	if missing_source_indicators:
		raise RuntimeError(f"JMP source indicators are missing: {missing_source_indicators}")

	values_by_indicator: dict[str, dict[int, dict[str, int | float]]] = {
		source_indicator: defaultdict(dict)
		for source_indicator in indicator_by_source
	}
	areas_with_any_value: dict[str, set[str]] = {
		source_indicator: set()
		for source_indicator in indicator_by_source
	}
	ignored_reference_areas: set[str] = set()
	series = datasets[0].get("series")
	if not isinstance(series, dict):
		raise RuntimeError("JMP SDMX series are missing.")

	for series_key, series_payload in series.items():
		if not isinstance(series_key, str) or not isinstance(series_payload, dict):
			continue
		parts = series_key.split(":")
		if len(parts) != len(series_dimensions):
			raise RuntimeError(f"Unexpected JMP series key: {series_key}")
		try:
			indices = [int(part) for part in parts]
		except ValueError as error:
			raise RuntimeError(f"Invalid JMP series key: {series_key}") from error
		series_values: dict[str, str] = {}
		for position, value_index in enumerate(indices):
			dimension_id = series_ids[position]
			try:
				series_values[dimension_id] = ids_by_dimension[dimension_id][value_index]
			except IndexError as error:
				raise RuntimeError(f"JMP series index outside codelist: {series_key}") from error

		source_indicator = series_values["INDICATOR"]
		indicator = indicator_by_source.get(source_indicator)
		if indicator is None:
			continue
		if series_values["SERVICE_TYPE"] != str(indicator["serviceType"]):
			continue
		if series_values["WEALTH_QUINTILE"] != "_T" or series_values["RESIDENCE"] != "_T":
			continue
		iso3 = series_values["REF_AREA"].upper()
		if iso3 not in area_by_iso3:
			if len(iso3) == 3 and iso3.isalpha():
				ignored_reference_areas.add(iso3)
			continue
		area_id = area_by_iso3[iso3]
		observations = series_payload.get("observations")
		if not isinstance(observations, dict):
			continue
		for time_index_text, observation in observations.items():
			if not isinstance(observation, list) or not observation or observation[0] in (None, ""):
				continue
			try:
				time_index = int(time_index_text)
				year = int(time_values[time_index])
			except (ValueError, IndexError) as error:
				raise RuntimeError(f"Invalid JMP observation time index: {time_index_text}") from error
			value = parse_percentage(observation[0])
			year_values = values_by_indicator[source_indicator][year]
			if area_id in year_values:
				raise RuntimeError(
					f"Duplicate JMP value for {indicator['id']} {year} {area_id}."
				)
			year_values[area_id] = value
			areas_with_any_value[source_indicator].add(area_id)

	provider = config["provider"]
	dataflow = config["dataflow"]
	result: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		source_indicator = str(indicator["sourceIndicator"])
		year_values = values_by_indicator[source_indicator]
		available_years = sorted(year for year, mapped in year_values.items() if mapped)
		if not available_years:
			raise RuntimeError(f"JMP returned no mapped values for {indicator['id']}.")
		if available_years[0] > int(config["expectedStartYear"]):
			raise RuntimeError(
				f"JMP history for {indicator['id']} starts too late: {available_years[0]}."
			)
		latest_year = available_years[-1]
		if latest_year < int(config["minimumLatestYear"]):
			raise RuntimeError(
				f"JMP latest year for {indicator['id']} is too old: {latest_year}."
			)
		mapped_areas = areas_with_any_value[source_indicator]
		if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
			raise RuntimeError(
				f"JMP coverage too small for {indicator['id']}: {len(mapped_areas)} areas, "
				f"expected at least {indicator['minAreasWithAnyValue']}."
			)
		latest_coverage = len(year_values[latest_year])
		if latest_coverage < int(indicator["minAreasInLatestYear"]):
			raise RuntimeError(
				f"JMP latest-year coverage too small for {indicator['id']}: {latest_coverage} areas, "
				f"expected at least {indicator['minAreasInLatestYear']}."
			)

		indicator_metadata = {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		}
		payload = {
			"schema": "kartensammlung.statistics-indicator/v1",
			"indicator": indicator_metadata,
			"source": {
				"providerId": provider["id"],
				"providerName": provider["name"],
				"dataset": provider["dataset"],
				"dataflowAgency": dataflow["agency"],
				"dataflowId": dataflow["id"],
				"dataflowVersion": dataflow["version"],
				"indicator": source_indicator,
				"indicatorName": indicator_names.get(source_indicator),
				"serviceType": indicator["serviceType"],
				"residence": "_T",
				"wealthQuintile": "_T",
				"license": provider["license"],
				"licenseUrl": provider["licenseUrl"],
				"attribution": provider["attribution"],
				"url": "https://data.unicef.org/topic/water-and-sanitation/",
				"apiUrl": config["apiUrl"],
			},
			"availableYears": available_years,
			"defaultYear": latest_year,
			"coverage": {
				"registryAreas": len(area_by_iso3),
				"areasWithAnyValue": len(mapped_areas),
				"latestYear": latest_year,
				"areasInLatestYear": latest_coverage,
				"areasInDefaultYear": latest_coverage,
			},
			"values": {
				str(year): {
					area_id: year_values[year][area_id]
					for area_id in sorted(year_values[year])
				}
				for year in available_years
			},
		}
		print(
			f"{indicator['id']}: mapped={len(mapped_areas)} "
			f"years={available_years[0]}-{latest_year} "
			f"defaultYear={latest_year} defaultCoverage={latest_coverage}"
		)
		result.append((indicator, payload))

	print(f"Ignored three-letter reference areas: {sorted(ignored_reference_areas) or '(none)'}")
	return result


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("JMP is missing from statistics-providers.json.")
	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	print(f"Fetching JMP dataflow {config['dataflow']['id']} from UNICEF SDMX")
	api_payload = common.fetch_json(str(config["apiUrl"]), args.timeout)
	indicator_payloads = build_payloads(config, area_by_iso3, api_payload)
	now = datetime.now(timezone.utc)

	hasher = hashlib.sha256()
	for indicator, payload in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(common.canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []
	for indicator, payload in indicator_payloads:
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
			"agency": config["dataflow"]["agency"],
			"id": config["dataflow"]["id"],
			"version": config["dataflow"]["version"],
			"apiUrl": config["apiUrl"],
			"residence": "Total",
			"wealthQuintile": "Total",
		},
		"indicators": index_indicators,
		"notes": [
			"Household WASH estimates from the WHO/UNICEF Joint Monitoring Programme (JMP).",
			"This provider currently publishes national total-population estimates; urban/rural series are intentionally excluded from this first block.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built JMP snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
