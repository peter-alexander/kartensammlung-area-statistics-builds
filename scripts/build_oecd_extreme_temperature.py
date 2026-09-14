#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "oecd-extreme-temperature-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
EXPECTED_DATAFLOW = "OECD.ENV.EPI:DSD_ECH@EXT_TEMP_H(2.0)"
EXPECTED_UNIT = "D_Y"
EXPECTED_DURATION = "_Z"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build country heat and thermal-stress statistics from OECD Historical exposure to extreme temperature."
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
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.oecd-extreme-temperature-statistics/v1":
		raise ValueError("Invalid OECD extreme-temperature statistics config.")
	for key in ("sourceUrl", "apiBaseUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"OECD extreme-temperature {key} must use HTTPS.")
	if payload.get("dataflow") != EXPECTED_DATAFLOW:
		raise ValueError("Unexpected OECD extreme-temperature dataflow.")
	minimum_latest_year = payload.get("minimumLatestYear")
	if not isinstance(minimum_latest_year, int) or minimum_latest_year < 2024:
		raise ValueError("minimumLatestYear must be at least 2024.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "oecd-extreme-temperature":
		raise ValueError("OECD extreme-temperature provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"OECD extreme-temperature provider metadata is missing {key}.")
	if payload.get("areaAliases") != {"XKX": "XKV"}:
		raise ValueError("OECD extreme-temperature areaAliases must remain XKX -> XKV.")
	if not isinstance(payload.get("requiredAreas"), list) or not payload["requiredAreas"]:
		raise ValueError("OECD extreme-temperature requiredAreas is missing.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 4:
		raise ValueError("OECD extreme-temperature config requires exactly four indicators.")
	expected = {
		"oecd-extreme-temperature.population-weighted-hot-days-35c": ("HD_PW_EXP", "H_35", 1979),
		"oecd-extreme-temperature.strong-heat-stress-days": ("UTCI_PW_EXP", "H_32", 1981),
		"oecd-extreme-temperature.very-strong-heat-stress-days": ("UTCI_PW_EXP", "H_38", 1981),
		"oecd-extreme-temperature.extreme-heat-stress-days": ("UTCI_PW_EXP", "H_46", 1981),
	}
	ids: set[str] = set()
	slugs: set[str] = set()
	pairs: set[tuple[str, str]] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("OECD extreme-temperature indicator must be an object.")
		for key in ("id", "slug", "measure", "threshold", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"OECD extreme-temperature indicator is missing {key}.")
		indicator_id = str(indicator["id"])
		pair = (str(indicator["measure"]), str(indicator["threshold"]))
		triple = (pair[0], pair[1], indicator.get("startYear"))
		if expected.get(indicator_id) != triple:
			raise ValueError(f"Unexpected OECD extreme-temperature mapping for {indicator_id}: {triple}")
		if indicator_id in ids or str(indicator["slug"]) in slugs or pair in pairs:
			raise ValueError(f"Duplicate OECD extreme-temperature indicator: {indicator_id}")
		ids.add(indicator_id)
		slugs.add(str(indicator["slug"]))
		pairs.add(pair)
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or unit.get("id") != "days-per-year":
			raise ValueError(f"OECD extreme-temperature unit must be days-per-year for {indicator_id}.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		sanity_range = indicator.get("sanityRange")
		if (
			not isinstance(sanity_range, list)
			or len(sanity_range) != 2
			or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in sanity_range)
			or float(sanity_range[0]) >= float(sanity_range[1])
		):
			raise ValueError(f"Invalid sanityRange for {indicator_id}.")
		for key in ("expectedAreasWithAnyValue", "expectedAreasIn2024"):
			if not isinstance(indicator.get(key), int) or int(indicator[key]) <= 0:
				raise ValueError(f"Invalid {key} for {indicator_id}.")
		missing_any = validate_iso3_list(
			f"{indicator_id}.expectedMissingAnyIso3",
			indicator.get("expectedMissingAnyIso3"),
		)
		missing_2024 = validate_iso3_list(
			f"{indicator_id}.expectedMissing2024Iso3",
			indicator.get("expectedMissing2024Iso3"),
		)
		if 250 - len(missing_any) != int(indicator["expectedAreasWithAnyValue"]):
			raise ValueError(f"Coverage/missing-any mismatch for {indicator_id}.")
		if 250 - len(missing_2024) != int(indicator["expectedAreasIn2024"]):
			raise ValueError(f"Coverage/missing-2024 mismatch for {indicator_id}.")
	return payload


def fetch_csv(url: str, timeout: int) -> tuple[bytes, dict[str, str]]:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 3, 10, 20, 40), start=1):
		if delay:
			time.sleep(delay)
		request = Request(url, headers={"Accept": "text/csv", "User-Agent": USER_AGENT})
		try:
			with urlopen(request, timeout=timeout) as response:
				raw = response.read()
				headers = {key.lower(): value for key, value in response.headers.items()}
			if not raw:
				raise RuntimeError("OECD SDMX API returned an empty response.")
			return raw, headers
		except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
			last_error = error
			print(f"OECD request failed ({attempt}/5): {error}")
	if last_error is None:
		raise RuntimeError("OECD request failed without an exception.")
	raise RuntimeError("OECD request failed after 5 attempts.") from last_error


def source_code_map(config: dict[str, Any], area_by_iso3: dict[str, str]) -> dict[str, str]:
	mapping: dict[str, str] = {}
	for iso3, area_id in sorted(area_by_iso3.items()):
		source_code = str(config["areaAliases"].get(iso3, iso3)).upper()
		if source_code in mapping:
			raise RuntimeError(f"Duplicate OECD source area code after aliases: {source_code}")
		mapping[source_code] = area_id
	if len(mapping) != 250:
		raise RuntimeError(f"OECD source area mapping has {len(mapping)} areas, expected 250.")
	return mapping


def query_url(api_base: str, source_codes: list[str], measure: str, thresholds: list[str], start_year: int) -> str:
	areas = "+".join(source_codes)
	threshold_part = "+".join(thresholds)
	key = f"{areas}.A.{measure}...{threshold_part}......"
	return f"{api_base}/{key}?startPeriod={start_year}&dimensionAtObservation=AllDimensions"


def parse_response(
	raw: bytes,
	url: str,
	source_to_area: dict[str, str],
	expected_measure: str,
	expected_thresholds: set[str],
	minimum_year: int,
) -> tuple[dict[str, dict[int, dict[str, int | float]]], set[str], int]:
	reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
	fields = set(reader.fieldnames or [])
	required = {
		"DATAFLOW",
		"REF_AREA",
		"FREQ",
		"MEASURE",
		"UNIT_MEASURE",
		"DURATION",
		"TEMP_THRESHOLD",
		"TIME_PERIOD",
		"OBS_VALUE",
	}
	missing = sorted(required - fields)
	if missing:
		raise RuntimeError("OECD SDMX response is missing columns: " + ", ".join(missing))

	values: dict[str, dict[int, dict[str, int | float]]] = {
		threshold: defaultdict(dict)
		for threshold in expected_thresholds
	}
	statuses: set[str] = set()
	row_count = 0
	current_year = datetime.now(timezone.utc).year
	for row in reader:
		row_count += 1
		if str(row.get("DATAFLOW") or "").strip() != EXPECTED_DATAFLOW:
			raise RuntimeError(f"Unexpected OECD DATAFLOW: {row.get('DATAFLOW')!r}")
		if str(row.get("FREQ") or "").strip() != "A":
			raise RuntimeError(f"Unexpected OECD FREQ: {row.get('FREQ')!r}")
		if str(row.get("MEASURE") or "").strip() != expected_measure:
			raise RuntimeError(f"Unexpected OECD MEASURE: {row.get('MEASURE')!r}")
		if str(row.get("UNIT_MEASURE") or "").strip() != EXPECTED_UNIT:
			raise RuntimeError(f"Unexpected OECD UNIT_MEASURE: {row.get('UNIT_MEASURE')!r}")
		if str(row.get("DURATION") or "").strip() != EXPECTED_DURATION:
			raise RuntimeError(f"Unexpected OECD DURATION: {row.get('DURATION')!r}")
		threshold = str(row.get("TEMP_THRESHOLD") or "").strip()
		if threshold not in expected_thresholds:
			raise RuntimeError(f"Unexpected OECD TEMP_THRESHOLD: {threshold!r}")
		if "UNIT_MULT" in fields and str(row.get("UNIT_MULT") or "").strip() not in ("", "0"):
			raise RuntimeError(f"Unexpected OECD UNIT_MULT: {row.get('UNIT_MULT')!r}")
		status = str(row.get("OBS_STATUS") or "").strip()
		if status:
			statuses.add(status)

		source_code = str(row.get("REF_AREA") or "").strip().upper()
		area_id = source_to_area.get(source_code)
		if area_id is None:
			raise RuntimeError(f"OECD response contains an unrequested area code: {source_code!r}")
		year_text = str(row.get("TIME_PERIOD") or "").strip()
		value_text = str(row.get("OBS_VALUE") or "").strip()
		if not year_text or not value_text:
			continue
		try:
			year = int(year_text)
			value = float(value_text)
		except ValueError as error:
			raise RuntimeError(f"Invalid OECD observation: {source_code} {year_text} {value_text!r}") from error
		if year < minimum_year or year > current_year:
			raise RuntimeError(f"Unexpected OECD year {year} in {url}")
		if not math.isfinite(value) or value < 0 or value > 366:
			raise RuntimeError(f"OECD heat-day value outside 0..366: {source_code} {year} {value}")
		if area_id in values[threshold][year]:
			raise RuntimeError(f"Duplicate OECD value for {threshold} {area_id} {year}.")
		values[threshold][year][area_id] = common.normalize_number(value_text)
	return values, statuses, row_count


def choose_published_years(
	indicator: dict[str, Any],
	area_by_iso3: dict[str, str],
	values: dict[int, dict[str, int | float]],
	minimum_latest_year: int,
) -> tuple[list[int], list[int], int]:
	source_years = sorted(year for year, mapped in values.items() if mapped)
	if not source_years or source_years[0] != int(indicator["startYear"]):
		raise RuntimeError(f"Unexpected first year for {indicator['id']}: {source_years[:1]}")
	if source_years != list(range(source_years[0], source_years[-1] + 1)):
		raise RuntimeError(f"OECD {indicator['id']} has gaps in source years.")
	if source_years[-1] < minimum_latest_year:
		raise RuntimeError(
			f"OECD {indicator['id']} latest source year {source_years[-1]} is older than {minimum_latest_year}."
		)

	mapped_areas = {area_id for year_values in values.values() for area_id in year_values}
	missing_any = sorted(
		iso3 for iso3, area_id in area_by_iso3.items()
		if area_id not in mapped_areas
	)
	if len(mapped_areas) != int(indicator["expectedAreasWithAnyValue"]):
		raise RuntimeError(f"Unexpected all-years coverage for {indicator['id']}: {len(mapped_areas)}")
	if missing_any != indicator["expectedMissingAnyIso3"]:
		raise RuntimeError(f"Unexpected all-years missing areas for {indicator['id']}: {missing_any}")

	if 2024 not in values:
		raise RuntimeError(f"OECD {indicator['id']} is missing audited year 2024.")
	missing_2024 = sorted(
		iso3 for iso3, area_id in area_by_iso3.items()
		if area_id not in values[2024]
	)
	if len(values[2024]) != int(indicator["expectedAreasIn2024"]):
		raise RuntimeError(f"Unexpected 2024 coverage for {indicator['id']}: {len(values[2024])}")
	if missing_2024 != indicator["expectedMissing2024Iso3"]:
		raise RuntimeError(f"Unexpected 2024 missing areas for {indicator['id']}: {missing_2024}")

	minimum_coverage = int(indicator["expectedAreasIn2024"])
	eligible = [year for year in source_years if len(values[year]) >= minimum_coverage]
	if not eligible:
		raise RuntimeError(f"OECD {indicator['id']} has no publishable year with audited coverage.")
	published_through = eligible[-1]
	if published_through < minimum_latest_year:
		raise RuntimeError(
			f"OECD {indicator['id']} latest publishable year {published_through} is older than {minimum_latest_year}."
		)
	published_years = [year for year in source_years if year <= published_through]
	excluded_trailing_years = [year for year in source_years if year > published_through]
	return source_years, published_years, published_through


def build_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_iso3: dict[str, str],
	values: dict[int, dict[str, int | float]],
	statuses: set[str],
	source_rows: int,
	api_url: str,
) -> dict[str, Any]:
	source_years, published_years, default_year = choose_published_years(
		indicator,
		area_by_iso3,
		values,
		int(config["minimumLatestYear"]),
	)
	value_min, value_max = (float(item) for item in indicator["sanityRange"])
	for year, year_values in values.items():
		for area_id, raw_value in year_values.items():
			value = float(raw_value)
			if not math.isfinite(value) or value < value_min or value > value_max:
				raise RuntimeError(f"Value outside sanity range: {indicator['id']} {area_id} {year} {value}")
	for area_id in config["requiredAreas"]:
		if area_id not in values[default_year]:
			raise RuntimeError(f"OECD {indicator['id']} default year {default_year} is missing {area_id}.")

	published_areas = {
		area_id
		for year in published_years
		for area_id in values[year]
	}
	excluded_trailing_years = [year for year in source_years if year > default_year]
	provider = config["provider"]
	return {
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
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourceUrl"],
			"apiUrl": api_url,
			"dataflow": config["dataflow"],
			"measure": indicator["measure"],
			"threshold": indicator["threshold"],
			"dimensionFilters": {
				"FREQ": "A",
				"MEASURE": indicator["measure"],
				"UNIT_MEASURE": EXPECTED_UNIT,
				"DURATION": EXPECTED_DURATION,
				"TEMP_THRESHOLD": indicator["threshold"],
			},
			"observationStatuses": sorted(statuses),
			"sourceRows": source_rows,
			"sourceAvailableYears": source_years,
			"sourceLatestYear": source_years[-1],
			"excludedTrailingYears": excluded_trailing_years,
			"mapping": {"XKV": "XKX"},
		},
		"availableYears": published_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(published_areas),
			"latestYear": default_year,
			"areasInLatestYear": len(values[default_year]),
			"areasInDefaultYear": len(values[default_year]),
			"observations": sum(len(values[year]) for year in published_years),
		},
		"values": {
			str(year): {
				area_id: values[year][area_id]
				for area_id in sorted(values[year])
			}
			for year in published_years
		},
	}


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("OECD extreme-temperature provider is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	source_to_area = source_code_map(config, area_by_iso3)
	source_codes = sorted(source_to_area)
	groups = [
		("HD_PW_EXP", ["H_35"], 1979),
		("UTCI_PW_EXP", ["H_32", "H_38", "H_46"], 1981),
	]
	values_by_pair: dict[tuple[str, str], dict[int, dict[str, int | float]]] = {}
	statuses_by_measure: dict[str, set[str]] = {}
	rows_by_measure: dict[str, int] = {}
	request_metadata: dict[str, dict[str, Any]] = {}
	url_by_measure: dict[str, str] = {}
	for measure, thresholds, start_year in groups:
		url = query_url(str(config["apiBaseUrl"]), source_codes, measure, thresholds, start_year)
		print(f"Fetching OECD {measure}: {url}")
		raw, headers = fetch_csv(url, args.timeout)
		parsed, statuses, row_count = parse_response(
			raw,
			url,
			source_to_area,
			measure,
			set(thresholds),
			start_year,
		)
		for threshold, values in parsed.items():
			values_by_pair[(measure, threshold)] = values
		statuses_by_measure[measure] = statuses
		rows_by_measure[measure] = row_count
		url_by_measure[measure] = url
		metadata: dict[str, Any] = {
			"bytes": len(raw),
			"sha256": hashlib.sha256(raw).hexdigest(),
		}
		if headers.get("last-modified"):
			metadata["lastModified"] = headers["last-modified"]
		if headers.get("etag"):
			metadata["etag"] = headers["etag"]
		request_metadata[measure] = metadata

	payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		pair = (str(indicator["measure"]), str(indicator["threshold"]))
		values = values_by_pair.get(pair)
		if values is None:
			raise RuntimeError(f"Missing parsed OECD series for {pair}.")
		payload = build_payload(
			config,
			indicator,
			area_by_iso3,
			values,
			statuses_by_measure[pair[0]],
			rows_by_measure[pair[0]],
			url_by_measure[pair[0]],
		)
		payloads.append((indicator, payload))
		coverage = payload["coverage"]
		print(
			f"{indicator['id']}: published={payload['availableYears'][0]}-{payload['availableYears'][-1]} "
			f"sourceLatest={payload['source']['sourceLatestYear']} excludedTrailing={payload['source']['excludedTrailingYears']} "
			f"areas={coverage['areasWithAnyValue']} defaultCoverage={coverage['areasInDefaultYear']} "
			f"observations={coverage['observations']}"
		)

	hasher = hashlib.sha256()
	for indicator, payload in payloads:
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(common.canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	now = datetime.now(timezone.utc)
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []
	for indicator, payload in payloads:
		filename = f"{indicator['slug']}.json"
		common.write_json(release_dir / filename, payload)
		index_indicators.append(
			{
				"id": indicator["id"],
				"title": indicator["title"],
				"description": indicator["description"],
				"areaLevel": "country",
				"frequency": "annual",
				"unit": indicator["unit"],
				"classification": indicator["classification"],
				"sourceMeasure": indicator["measure"],
				"sourceThreshold": indicator["threshold"],
				"path": f"releases/{snapshot}/{filename}",
				"availableYears": payload["availableYears"],
				"defaultYear": payload["defaultYear"],
				"coverage": payload["coverage"],
			}
		)

	registry_source: dict[str, Any] = {
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
			"url": config["sourceUrl"],
			"apiBaseUrl": config["apiBaseUrl"],
			"dataflow": config["dataflow"],
			"minimumLatestYear": config["minimumLatestYear"],
			"areaMapping": {"XKV": "XKX"},
			"requests": request_metadata,
			"sourceRows": rows_by_measure,
		},
		"indicators": index_indicators,
		"notes": [
			"Direct OECD Historical exposure to extreme temperature country series; no interpolation, extrapolation or cross-provider fallback is used.",
			"Hot days use the OECD definition of daily maximum temperature above 35 °C and are population-weighted across the country.",
			"UTCI heat-stress days combine air temperature, humidity, wind and radiation; the published thresholds are above 32 °C (strong), 38 °C (very strong) and 46 °C (extreme) UTCI.",
			"Population weighting describes average population exposure rather than an unweighted land-area mean; decimal day values are expected.",
			"Trailing source years with less coverage than audited 2024 are recorded in source metadata but excluded from published availableYears until coverage is sufficient.",
			"The explicit XKV source code is mapped to registry XKX (Kosovo); no fuzzy country-name mapping is used.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built OECD extreme-temperature snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
