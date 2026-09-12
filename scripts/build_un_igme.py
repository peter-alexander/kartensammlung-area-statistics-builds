#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pycountry

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "un-igme-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build normalized country child-mortality statistics directly from UN IGME via UNICEF SDMX."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def fetch_json(url: str, timeout: int) -> Any:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 3, 10, 20, 40), start=1):
		if delay:
			time.sleep(delay)
		request = Request(
			url,
			headers={
				"Accept": "application/json",
				"User-Agent": USER_AGENT,
			},
		)
		try:
			with urlopen(request, timeout=timeout) as response:
				return json.load(response)
		except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
			last_error = error
			print(f"Request failed ({attempt}/5): {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"Request failed without an exception: {url}")
	raise RuntimeError(f"Request failed after 5 attempts: {url}") from last_error


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.un-igme-statistics/v1":
		raise ValueError("Invalid UN IGME statistics config.")
	for key in ("apiBase", "sourcePage", "apiDocumentation"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"UN IGME {key} must use HTTPS.")
	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "un-igme":
		raise ValueError("UN IGME provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"UN IGME provider metadata is missing {key}.")
	minimum_latest_year = payload.get("minimumLatestYear")
	if not isinstance(minimum_latest_year, int) or minimum_latest_year < 2024:
		raise ValueError("UN IGME minimumLatestYear is invalid.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("UN IGME config requires indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	source_codes: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("UN IGME indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "sourceIndicatorName", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"UN IGME indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		source_code = str(indicator["sourceIndicator"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate UN IGME indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate UN IGME indicator slug: {slug}")
		if source_code in source_codes:
			raise ValueError(f"Duplicate UN IGME source indicator: {source_code}")
		ids.add(indicator_id)
		slugs.add(slug)
		source_codes.add(source_code)
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"UN IGME indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"UN IGME indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"UN IGME indicator {indicator_id} requires at least one required area.")
	return payload


def query_url(config: dict[str, Any]) -> str:
	codes = "+".join(str(indicator["sourceIndicator"]) for indicator in config["indicators"])
	return f"{str(config['apiBase']).rstrip('/')}/.{codes}._T?format=sdmx-json"


def dimension_values(structure: dict[str, Any], level: str, dimension_id: str) -> list[dict[str, Any]]:
	for dimension in structure.get("dimensions", {}).get(level, []):
		if dimension.get("id") == dimension_id:
			return list(dimension.get("values") or [])
	raise RuntimeError(f"UN IGME response is missing {level} dimension {dimension_id}.")


def observation_attribute(
	structure: dict[str, Any],
	attribute_id: str,
) -> tuple[int, list[dict[str, Any]]]:
	for index, attribute in enumerate(structure.get("attributes", {}).get("observation", [])):
		if attribute.get("id") == attribute_id:
			return index + 1, list(attribute.get("values") or [])
	raise RuntimeError(f"UN IGME response is missing observation attribute {attribute_id}.")


def decode_attribute_id(
	observation: list[Any],
	position: int,
	values: list[dict[str, Any]],
) -> str | None:
	if position >= len(observation) or observation[position] is None:
		return None
	index = int(observation[position])
	if not 0 <= index < len(values):
		raise RuntimeError(f"UN IGME attribute index is out of range: {index}/{len(values)}")
	return str(values[index].get("id") or "").strip() or None


def decode_attribute_number(
	observation: list[Any],
	position: int,
	values: list[dict[str, Any]],
) -> int | float | None:
	value = decode_attribute_id(observation, position, values)
	if value is None:
		return None
	return common.normalize_number(value)


def is_country_code(code: str) -> bool:
	return code == "XKX" or pycountry.countries.get(alpha_3=code) is not None


def parse_source(
	config: dict[str, Any],
	payload: Any,
	area_by_iso3: dict[str, str],
) -> tuple[
	dict[str, dict[int, dict[str, int | float]]],
	dict[str, dict[int, dict[str, dict[str, int | float]]]],
	dict[str, Any],
]:
	if not isinstance(payload, dict):
		raise RuntimeError("Unexpected UNICEF SDMX response.")
	data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
	structure = data.get("structure") if isinstance(data, dict) else None
	data_sets = data.get("dataSets") if isinstance(data, dict) else None
	if not isinstance(structure, dict) or not isinstance(data_sets, list) or len(data_sets) != 1:
		raise RuntimeError("Unexpected UNICEF SDMX data/structure shape.")

	series_dimensions = structure.get("dimensions", {}).get("series", [])
	series_dimension_ids = [str(item.get("id") or "") for item in series_dimensions]
	if series_dimension_ids != ["REF_AREA", "INDICATOR", "SEX"]:
		raise RuntimeError(f"Unexpected UN IGME series dimensions: {series_dimension_ids}")
	observation_dimensions = structure.get("dimensions", {}).get("observation", [])
	if [str(item.get("id") or "") for item in observation_dimensions] != ["TIME_PERIOD"]:
		raise RuntimeError("Unexpected UN IGME observation dimensions.")

	areas = dimension_values(structure, "series", "REF_AREA")
	indicators = dimension_values(structure, "series", "INDICATOR")
	sexes = dimension_values(structure, "series", "SEX")
	times = dimension_values(structure, "observation", "TIME_PERIOD")

	attribute_specs: dict[str, tuple[int, list[dict[str, Any]]]] = {}
	for attribute_id in ("UNIT_MEASURE", "OBS_STATUS", "LOWER_BOUND", "UPPER_BOUND", "DATA_SOURCE", "AGE"):
		attribute_specs[attribute_id] = observation_attribute(structure, attribute_id)

	configured_codes = {str(indicator["sourceIndicator"]) for indicator in config["indicators"]}
	values: dict[str, dict[int, dict[str, int | float]]] = {
		code: defaultdict(dict) for code in configured_codes
	}
	intervals: dict[str, dict[int, dict[str, dict[str, int | float]]]] = {
		code: defaultdict(dict) for code in configured_codes
	}
	unresolved_countries: set[str] = set()
	observed_units: set[str] = set()
	observed_statuses: set[str] = set()
	observed_sources: set[str] = set()
	observed_ages: set[str] = set()

	series = data_sets[0].get("series")
	if not isinstance(series, dict) or not series:
		raise RuntimeError("UN IGME response contains no series.")
	for series_key, series_payload in series.items():
		indices = [int(item) for item in str(series_key).split(":")]
		if len(indices) != 3:
			raise RuntimeError(f"Unexpected UN IGME series key: {series_key}")
		iso3 = str(areas[indices[0]].get("id") or "").strip().upper()
		source_indicator = str(indicators[indices[1]].get("id") or "").strip()
		sex = str(sexes[indices[2]].get("id") or "").strip()
		if source_indicator not in configured_codes or sex != "_T":
			continue
		if iso3 not in area_by_iso3:
			if is_country_code(iso3):
				unresolved_countries.add(iso3)
			continue
		area_id = area_by_iso3[iso3]
		observations = series_payload.get("observations") if isinstance(series_payload, dict) else None
		if not isinstance(observations, dict):
			continue
		for observation_key, observation_raw in observations.items():
			if not isinstance(observation_raw, list) or not observation_raw:
				continue
			time_index = int(observation_key)
			if not 0 <= time_index < len(times):
				raise RuntimeError(f"UN IGME time index is out of range: {time_index}/{len(times)}")
			year_text = str(times[time_index].get("id") or times[time_index].get("name") or "").strip()
			if not year_text.isdigit():
				continue
			year = int(year_text)
			value = common.normalize_number(observation_raw[0])
			if not math.isfinite(float(value)) or float(value) < 0:
				raise RuntimeError(f"Invalid UN IGME value: {source_indicator} {iso3} {year}: {value}")

			unit = decode_attribute_id(observation_raw, *attribute_specs["UNIT_MEASURE"])
			status = decode_attribute_id(observation_raw, *attribute_specs["OBS_STATUS"])
			data_source = decode_attribute_id(observation_raw, *attribute_specs["DATA_SOURCE"])
			age = decode_attribute_id(observation_raw, *attribute_specs["AGE"])
			if unit:
				observed_units.add(unit)
			if status:
				observed_statuses.add(status)
			if data_source:
				observed_sources.add(data_source)
			if age:
				observed_ages.add(age)

			lower = decode_attribute_number(observation_raw, *attribute_specs["LOWER_BOUND"])
			upper = decode_attribute_number(observation_raw, *attribute_specs["UPPER_BOUND"])
			if lower is None or upper is None:
				raise RuntimeError(f"UN IGME confidence interval is missing: {source_indicator} {iso3} {year}")
			if not float(lower) <= float(value) <= float(upper):
				raise RuntimeError(
					f"Invalid UN IGME confidence interval: {source_indicator} {iso3} {year}: "
					f"{lower}, {value}, {upper}"
				)
			if area_id in values[source_indicator][year]:
				raise RuntimeError(f"Duplicate UN IGME value: {source_indicator} {area_id} {year}")
			values[source_indicator][year][area_id] = value
			intervals[source_indicator][year][area_id] = {"lower": lower, "upper": upper}

	if unresolved_countries:
		raise RuntimeError(f"UN IGME country codes missing from area registry: {', '.join(sorted(unresolved_countries))}")
	if observed_units != {"D_PER_1000_B"}:
		raise RuntimeError(f"Unexpected UN IGME unit codes: {sorted(observed_units)}")
	if observed_statuses != {"A"}:
		raise RuntimeError(f"Unexpected UN IGME observation status codes: {sorted(observed_statuses)}")
	if observed_sources != {"UN_IGME"}:
		raise RuntimeError(f"Unexpected UN IGME data-source codes: {sorted(observed_sources)}")
	if observed_ages != {"_T"}:
		raise RuntimeError(f"Unexpected UN IGME age codes: {sorted(observed_ages)}")

	metadata = {
		"reportingBegin": data_sets[0].get("reportingBegin"),
		"reportingEnd": data_sets[0].get("reportingEnd"),
		"unitMeasure": "D_PER_1000_B",
		"observationStatus": "A",
		"dataSource": "UN_IGME",
		"sex": "_T",
		"age": "_T",
	}
	return (
		{code: dict(years) for code, years in values.items()},
		{code: dict(years) for code, years in intervals.items()},
		metadata,
	)


def build_indicator_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	values_by_year: dict[int, dict[str, int | float]],
	intervals_by_year: dict[int, dict[str, dict[str, int | float]]],
	area_by_iso3: dict[str, str],
	api_url: str,
	source_metadata: dict[str, Any],
) -> dict[str, Any]:
	if not values_by_year:
		raise RuntimeError(f"UN IGME returned no mapped values for {indicator['id']}.")
	available_years = sorted(year for year, values in values_by_year.items() if values)
	areas_with_any_value = set().union(*(set(values_by_year[year]) for year in available_years))
	if len(areas_with_any_value) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"UN IGME coverage too small for {indicator['id']}: {len(areas_with_any_value)} areas."
		)
	minimum_default = int(indicator["minAreasInDefaultYear"])
	default_candidates = [year for year in available_years if len(values_by_year[year]) >= minimum_default]
	if not default_candidates:
		raise RuntimeError(f"UN IGME has no sufficiently covered default year for {indicator['id']}.")
	default_year = default_candidates[-1]
	if default_year < int(config["minimumLatestYear"]):
		raise RuntimeError(
			f"UN IGME default year is unexpectedly old for {indicator['id']}: {default_year}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in values_by_year[default_year]:
			raise RuntimeError(f"Required area {area_id} has no UN IGME value for {indicator['id']} in {default_year}.")

	interval_count = sum(len(values) for values in intervals_by_year.values())
	value_count = sum(len(values) for values in values_by_year.values())
	if interval_count != value_count:
		raise RuntimeError(
			f"UN IGME interval coverage mismatch for {indicator['id']}: {interval_count}/{value_count}."
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
			"confidenceIntervals": {
				"available": True,
				"level": 0.90,
				"lowerField": "LOWER_BOUND",
				"upperField": "UPPER_BOUND",
			},
		},
		"source": {
			"providerId": config["provider"]["id"],
			"providerName": config["provider"]["name"],
			"dataset": config["provider"]["dataset"],
			"indicator": indicator["sourceIndicator"],
			"indicatorName": indicator["sourceIndicatorName"],
			"provenance": "Direct UN IGME estimate distributed through the UNICEF Data Warehouse",
			"license": config["provider"]["license"],
			"licenseUrl": config["provider"]["licenseUrl"],
			"attribution": config["provider"]["attribution"],
			"url": config["sourcePage"],
			"apiDocumentation": config["apiDocumentation"],
			"apiUrl": api_url,
			"filters": {"SEX": "_T"},
			"unitMeasure": source_metadata["unitMeasure"],
			"dataSource": source_metadata["dataSource"],
			"reportingBegin": source_metadata.get("reportingBegin"),
			"reportingEnd": source_metadata.get("reportingEnd"),
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": available_years[-1],
			"areasInLatestYear": len(values_by_year[available_years[-1]]),
			"areasInDefaultYear": len(values_by_year[default_year]),
			"observations": value_count,
			"confidenceIntervalObservations": interval_count,
		},
		"values": {
			str(year): {area_id: values_by_year[year][area_id] for area_id in sorted(values_by_year[year])}
			for year in available_years
		},
		"confidenceIntervals": {
			"level": 0.90,
			"values": {
				str(year): {area_id: intervals_by_year[year][area_id] for area_id in sorted(intervals_by_year[year])}
				for year in available_years
			},
		},
	}
	print(
		f"{indicator['id']}: observations={value_count} intervals={interval_count} "
		f"areas={len(areas_with_any_value)} years={available_years[0]}-{available_years[-1]} "
		f"defaultYear={default_year} defaultCoverage={len(values_by_year[default_year])}"
	)
	return payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("UN IGME is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	api_url = query_url(config)
	print(f"Fetching UN IGME: {api_url}")
	source_payload = fetch_json(api_url, args.timeout)
	values_by_indicator, intervals_by_indicator, source_metadata = parse_source(
		config, source_payload, area_by_iso3
	)
	now = common.utc_now()

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		source_code = str(indicator["sourceIndicator"])
		payload = build_indicator_payload(
			config,
			indicator,
			values_by_indicator[source_code],
			intervals_by_indicator[source_code],
			area_by_iso3,
			api_url,
			source_metadata,
		)
		indicator_payloads.append((indicator, payload))

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
			"confidenceIntervals": True,
		})

	registry_source = {
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_iso3),
	}
	if args.registry.startswith(("https://", "http://")):
		registry_source["url"] = args.registry

	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"dataset": {
			"sourcePage": config["sourcePage"],
			"apiDocumentation": config["apiDocumentation"],
			"apiUrl": api_url,
			"dataSource": source_metadata["dataSource"],
			"reportingBegin": source_metadata.get("reportingBegin"),
			"reportingEnd": source_metadata.get("reportingEnd"),
			"confidenceIntervalLevel": 0.90,
		},
		"indicators": index_indicators,
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))

	print(f"Built UN IGME snapshot {snapshot}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
