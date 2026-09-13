#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
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
DEFAULT_CONFIG = ROOT / "config" / "oecd-revenue-statistics-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build country tax-to-GDP statistics from OECD Global Revenue Statistics."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.oecd-revenue-statistics/v1":
		raise ValueError("Invalid OECD revenue statistics config.")
	for key in ("sourceUrl", "apiUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"OECD revenue statistics {key} must use HTTPS.")
	if payload.get("dataflow") != "OECD.CTP.TPS:DSD_REV_COMP_GLOBAL@DF_RSGLOBAL(2.1)":
		raise ValueError("Unexpected OECD Global Revenue Statistics dataflow.")
	if payload.get("minYear") != 1990:
		raise ValueError("OECD revenue statistics minYear must remain 1990.")

	expected_dimensions = {
		"MEASURE": "TAX_REV",
		"SECTOR": "S13",
		"STANDARD_REVENUE": "_T",
		"CTRY_SPECIFIC_REVENUE": "_T",
		"UNIT_MEASURE": "PT_B1GQ",
		"FREQ": "A",
		"REVENUE_CODE": "TOTALTAX",
	}
	if payload.get("dimensions") != expected_dimensions:
		raise ValueError("OECD revenue statistics dimensions changed unexpectedly.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "oecd-revenue-statistics":
		raise ValueError("OECD revenue statistics provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"OECD provider metadata is missing {key}.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 1:
		raise ValueError("OECD revenue statistics config requires exactly one indicator.")
	indicator = indicators[0]
	if not isinstance(indicator, dict):
		raise ValueError("OECD revenue indicator must be an object.")
	for key in ("id", "slug", "sourceIndicator", "title", "description"):
		if not str(indicator.get(key, "")).strip():
			raise ValueError(f"OECD revenue indicator is missing {key}.")
	if indicator["id"] != "fiscal.tax-and-social-contributions-percent-gdp":
		raise ValueError("Unexpected OECD revenue indicator id.")
	unit = indicator.get("unit")
	if not isinstance(unit, dict) or unit.get("id") != "percent-of-gdp":
		raise ValueError("OECD revenue target unit must be percent-of-gdp.")
	common.validate_classification(str(indicator["id"]), indicator.get("classification"))
	value_range = indicator.get("valueRange")
	if (
		not isinstance(value_range, list)
		or len(value_range) != 2
		or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in value_range)
		or float(value_range[0]) >= float(value_range[1])
	):
		raise ValueError("OECD revenue indicator has invalid valueRange.")
	for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
		value = indicator.get(key)
		if not isinstance(value, int) or value <= 0:
			raise ValueError(f"OECD revenue indicator has invalid {key}.")
	required_areas = indicator.get("requiredAreas")
	if not isinstance(required_areas, list) or not required_areas:
		raise ValueError("OECD revenue indicator requires requiredAreas.")
	return payload


def fetch_csv(url: str, timeout: int) -> tuple[bytes, dict[str, str]]:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 3, 10, 20, 40), start=1):
		if delay:
			time.sleep(delay)
		request = Request(
			url,
			headers={
				"Accept": "text/csv",
				"User-Agent": USER_AGENT,
			},
		)
		try:
			with urlopen(request, timeout=timeout) as response:
				raw = response.read()
				headers = {key.lower(): value for key, value in response.headers.items()}
			if not raw:
				raise RuntimeError("OECD SDMX API returned an empty response.")
			return raw, headers
		except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
			last_error = error
			print(f"OECD request failed ({attempt}/5): {url}: {error}")
	if last_error is None:
		raise RuntimeError("OECD request failed without an exception.")
	raise RuntimeError("OECD request failed after 5 attempts.") from last_error


def load_values(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	timeout: int,
) -> tuple[
	dict[int, dict[str, int | float]],
	set[str],
	set[str],
	int,
	int,
	dict[str, str],
]:
	raw, headers = fetch_csv(str(config["apiUrl"]), timeout)
	reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
	fields = set(reader.fieldnames or [])
	required_fields = {
		"DATAFLOW",
		"REF_AREA",
		"MEASURE",
		"SECTOR",
		"STANDARD_REVENUE",
		"CTRY_SPECIFIC_REVENUE",
		"UNIT_MEASURE",
		"FREQ",
		"TIME_PERIOD",
		"OBS_VALUE",
		"OBS_STATUS",
		"UNIT_MULT",
		"REVENUE_CODE",
	}
	missing = sorted(required_fields - fields)
	if missing:
		raise RuntimeError("OECD SDMX response is missing columns: " + ", ".join(missing))

	values: dict[int, dict[str, int | float]] = defaultdict(dict)
	ignored_codes: set[str] = set()
	observation_statuses: set[str] = set()
	min_year = int(config["minYear"])
	current_year = datetime.now(timezone.utc).year
	source_rows = 0
	retained_rows = 0
	value_min, value_max = (float(value) for value in config["indicators"][0]["valueRange"])

	for row in reader:
		source_rows += 1
		if str(row.get("DATAFLOW") or "").strip() != str(config["dataflow"]):
			raise RuntimeError(f"Unexpected OECD DATAFLOW: {row.get('DATAFLOW')!r}")
		for dimension, expected in config["dimensions"].items():
			if str(row.get(dimension) or "").strip() != str(expected):
				raise RuntimeError(
					f"Unexpected OECD dimension {dimension}: {row.get(dimension)!r}; expected {expected!r}."
				)
		if str(row.get("UNIT_MULT") or "").strip() != "0":
			raise RuntimeError(f"Unexpected OECD UNIT_MULT: {row.get('UNIT_MULT')!r}")

		iso3 = str(row.get("REF_AREA") or "").strip().upper()
		year_text = str(row.get("TIME_PERIOD") or "").strip()
		value_text = str(row.get("OBS_VALUE") or "").strip()
		status = str(row.get("OBS_STATUS") or "").strip()
		if status:
			observation_statuses.add(status)
		if not iso3 or not year_text or not value_text:
			continue
		try:
			year = int(year_text)
			value = float(value_text)
		except ValueError as error:
			raise RuntimeError(f"Invalid OECD value/year: {iso3} {year_text} {value_text!r}") from error
		if year < min_year or year > current_year:
			continue
		if not math.isfinite(value) or value < value_min or value > value_max:
			raise RuntimeError(f"OECD tax-to-GDP value outside configured range: {iso3} {year} {value}.")
		area_id = area_by_iso3.get(iso3)
		if area_id is None:
			ignored_codes.add(iso3)
			continue
		if area_id in values[year]:
			raise RuntimeError(f"Duplicate OECD tax-to-GDP value for {area_id} {year}.")
		values[year][area_id] = common.normalize_number(value_text)
		retained_rows += 1

	if not values:
		raise RuntimeError("OECD SDMX API returned no mapped tax-to-GDP observations.")
	return values, ignored_codes, observation_statuses, source_rows, retained_rows, headers


def choose_default_year(
	indicator: dict[str, Any],
	available_years: list[int],
	values: dict[int, dict[str, int | float]],
) -> int:
	minimum = int(indicator["minAreasInDefaultYear"])
	eligible = [year for year in available_years if len(values[year]) >= minimum]
	if not eligible:
		raise RuntimeError(
			f"OECD revenue statistics has no default year with at least {minimum} mapped countries."
		)
	return eligible[-1]


def build_payload(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	values: dict[int, dict[str, int | float]],
	ignored_codes: set[str],
	observation_statuses: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
	indicator = config["indicators"][0]
	provider = config["provider"]
	available_years = sorted(year for year, mapped in values.items() if mapped)
	mapped_areas = {area_id for mapped in values.values() for area_id in mapped}
	if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"OECD revenue coverage too small: {len(mapped_areas)} mapped countries, "
			f"expected at least {indicator['minAreasWithAnyValue']}."
		)
	default_year = choose_default_year(indicator, available_years, values)
	for area_id in indicator["requiredAreas"]:
		if area_id not in values[default_year]:
			raise RuntimeError(f"OECD revenue default year {default_year} is missing required area {area_id}.")

	latest_year = available_years[-1]
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
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourceUrl"],
			"apiUrl": config["apiUrl"],
			"dataflow": config["dataflow"],
			"indicator": indicator["sourceIndicator"],
			"dimensionFilters": config["dimensions"],
			"observationStatuses": sorted(observation_statuses),
			"ignoredAreaCodes": sorted(ignored_codes),
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(mapped_areas),
			"latestYear": latest_year,
			"areasInLatestYear": len(values[latest_year]),
			"areasInDefaultYear": len(values[default_year]),
		},
		"values": {
			str(year): {
				area_id: values[year][area_id]
				for area_id in sorted(values[year])
			}
			for year in available_years
		},
	}
	print(
		f"{indicator['id']}: mapped={len(mapped_areas)} years={available_years[0]}-{latest_year} "
		f"latestCoverage={len(values[latest_year])} defaultYear={default_year} "
		f"defaultCoverage={len(values[default_year])} ignored={sorted(ignored_codes) or '(none)'}"
	)
	return indicator, payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("OECD revenue statistics is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	print(f"Fetching OECD Global Revenue Statistics from {config['apiUrl']}")
	values, ignored_codes, observation_statuses, source_rows, retained_rows, headers = load_values(
		config,
		area_by_iso3,
		args.timeout,
	)
	indicator, payload = build_payload(
		config,
		area_by_iso3,
		values,
		ignored_codes,
		observation_statuses,
	)

	hasher = hashlib.sha256()
	hasher.update(str(indicator["id"]).encode("utf-8"))
	hasher.update(b"\0")
	hasher.update(common.canonical_bytes(payload))
	hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	now = datetime.now(timezone.utc)
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	filename = f"{indicator['slug']}.json"
	common.write_json(release_dir / filename, payload)

	index_indicator = {
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
	}

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_iso3),
	}
	if registry_source["url"] is None:
		registry_source.pop("url")

	dataset = {
		"url": config["sourceUrl"],
		"apiUrl": config["apiUrl"],
		"dataflow": config["dataflow"],
		"sourceRows": source_rows,
		"retainedRows": retained_rows,
		"ignoredAreaCodes": sorted(ignored_codes),
		"observationStatuses": sorted(observation_statuses),
	}
	if headers.get("last-modified"):
		dataset["lastModified"] = headers["last-modified"]
	if headers.get("etag"):
		dataset["etag"] = headers["etag"]

	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"dataset": dataset,
		"indicators": [index_indicator],
		"notes": [
			"Direct OECD Global Revenue Statistics total tax revenue for the general government sector (S13), measured as percent of GDP.",
			"The OECD tax concept includes compulsory social security contributions paid to general government and covers all levels of government.",
			"No World Bank WDI or other provider is used as a fallback because narrower central-government tax series are not conceptually equivalent.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Observation statuses: {sorted(observation_statuses) or '(none)'}")
	print(f"Built OECD revenue statistics snapshot {snapshot}")
	print("Indicators: 1")


if __name__ == "__main__":
	main()
