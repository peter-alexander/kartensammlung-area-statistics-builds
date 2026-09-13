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


def validate_value_range(indicator_id: str, value_range: Any) -> None:
	if (
		not isinstance(value_range, list)
		or len(value_range) != 2
		or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in value_range)
		or not all(math.isfinite(float(value)) for value in value_range)
		or float(value_range[0]) >= float(value_range[1])
	):
		raise ValueError(f"OECD revenue indicator {indicator_id} has invalid valueRange.")


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
		"CTRY_SPECIFIC_REVENUE": "_T",
		"UNIT_MEASURE": "PT_B1GQ",
		"FREQ": "A",
	}
	if payload.get("dimensions") != expected_dimensions:
		raise ValueError("OECD revenue statistics common dimensions changed unexpectedly.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "oecd-revenue-statistics":
		raise ValueError("OECD revenue statistics provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"OECD provider metadata is missing {key}.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("OECD revenue statistics config requires indicators.")
	expected_pairs = {
		"fiscal.tax-and-social-contributions-percent-gdp": ("_T", "TOTALTAX"),
		"fiscal.personal-income-taxes-percent-gdp": ("T_1100", "1100"),
		"fiscal.corporate-income-taxes-percent-gdp": ("T_1200", "1200"),
		"fiscal.social-security-contributions-percent-gdp": ("T_2000", "2000"),
		"fiscal.property-taxes-percent-gdp": ("T_4000", "4000"),
		"fiscal.vat-percent-gdp": ("T_5111", "5111"),
	}
	if len(indicators) != len(expected_pairs):
		raise ValueError(f"OECD revenue statistics config requires exactly {len(expected_pairs)} indicators.")

	ids: set[str] = set()
	slugs: set[str] = set()
	pairs: set[tuple[str, str]] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("OECD revenue indicator must be an object.")
		for key in (
			"id",
			"slug",
			"sourceIndicator",
			"standardRevenue",
			"revenueCode",
			"title",
			"description",
		):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"OECD revenue indicator is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		pair = (str(indicator["standardRevenue"]), str(indicator["revenueCode"]))
		if indicator_id in ids:
			raise ValueError(f"Duplicate OECD revenue indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate OECD revenue indicator slug: {slug}")
		if pair in pairs:
			raise ValueError(f"Duplicate OECD revenue category pair: {pair}")
		if indicator_id not in expected_pairs or pair != expected_pairs[indicator_id]:
			raise ValueError(f"Unexpected OECD revenue category mapping for {indicator_id}: {pair}")
		ids.add(indicator_id)
		slugs.add(slug)
		pairs.add(pair)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or unit.get("id") != "percent-of-gdp":
			raise ValueError(f"OECD revenue target unit must be percent-of-gdp for {indicator_id}.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		validate_value_range(indicator_id, indicator.get("valueRange"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"OECD revenue indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"OECD revenue indicator {indicator_id} requires requiredAreas.")
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
	dict[str, dict[int, dict[str, int | float]]],
	dict[str, set[str]],
	dict[str, set[str]],
	dict[str, int],
	dict[str, int],
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

	indicators = config["indicators"]
	by_pair = {
		(str(indicator["standardRevenue"]), str(indicator["revenueCode"])): indicator
		for indicator in indicators
	}
	values_by_indicator: dict[str, dict[int, dict[str, int | float]]] = {
		str(indicator["id"]): defaultdict(dict)
		for indicator in indicators
	}
	ignored_codes: dict[str, set[str]] = {
		str(indicator["id"]): set()
		for indicator in indicators
	}
	observation_statuses: dict[str, set[str]] = {
		str(indicator["id"]): set()
		for indicator in indicators
	}
	source_rows = {str(indicator["id"]): 0 for indicator in indicators}
	retained_rows = {str(indicator["id"]): 0 for indicator in indicators}
	min_year = int(config["minYear"])
	current_year = datetime.now(timezone.utc).year

	for row in reader:
		if str(row.get("DATAFLOW") or "").strip() != str(config["dataflow"]):
			raise RuntimeError(f"Unexpected OECD DATAFLOW: {row.get('DATAFLOW')!r}")
		for dimension, expected in config["dimensions"].items():
			if str(row.get(dimension) or "").strip() != str(expected):
				raise RuntimeError(
					f"Unexpected OECD dimension {dimension}: {row.get(dimension)!r}; expected {expected!r}."
				)
		if str(row.get("UNIT_MULT") or "").strip() != "0":
			raise RuntimeError(f"Unexpected OECD UNIT_MULT: {row.get('UNIT_MULT')!r}")

		pair = (
			str(row.get("STANDARD_REVENUE") or "").strip(),
			str(row.get("REVENUE_CODE") or "").strip(),
		)
		indicator = by_pair.get(pair)
		if indicator is None:
			raise RuntimeError(f"Unexpected OECD revenue category in combined response: {pair}")
		indicator_id = str(indicator["id"])
		source_rows[indicator_id] += 1

		iso3 = str(row.get("REF_AREA") or "").strip().upper()
		year_text = str(row.get("TIME_PERIOD") or "").strip()
		value_text = str(row.get("OBS_VALUE") or "").strip()
		status = str(row.get("OBS_STATUS") or "").strip()
		if status:
			observation_statuses[indicator_id].add(status)
		if not iso3 or not year_text or not value_text:
			continue
		try:
			year = int(year_text)
			value = float(value_text)
		except ValueError as error:
			raise RuntimeError(f"Invalid OECD value/year: {indicator_id} {iso3} {year_text} {value_text!r}") from error
		if year < min_year or year > current_year:
			continue
		value_min, value_max = (float(item) for item in indicator["valueRange"])
		if not math.isfinite(value) or value < value_min or value > value_max:
			raise RuntimeError(
				f"OECD value outside configured range: {indicator_id} {iso3} {year} {value}."
			)
		area_id = area_by_iso3.get(iso3)
		if area_id is None:
			ignored_codes[indicator_id].add(iso3)
			continue
		values = values_by_indicator[indicator_id]
		if area_id in values[year]:
			raise RuntimeError(f"Duplicate OECD value for {indicator_id} {area_id} {year}.")
		values[year][area_id] = common.normalize_number(value_text)
		retained_rows[indicator_id] += 1

	for indicator in indicators:
		indicator_id = str(indicator["id"])
		if not values_by_indicator[indicator_id]:
			raise RuntimeError(f"OECD SDMX API returned no mapped observations for {indicator_id}.")
		if not observation_statuses[indicator_id]:
			raise RuntimeError(f"OECD SDMX API returned no observation status for {indicator_id}.")
	return (
		values_by_indicator,
		ignored_codes,
		observation_statuses,
		source_rows,
		retained_rows,
		headers,
	)


def choose_default_year(
	indicator: dict[str, Any],
	available_years: list[int],
	values: dict[int, dict[str, int | float]],
) -> int:
	minimum = int(indicator["minAreasInDefaultYear"])
	eligible = [year for year in available_years if len(values[year]) >= minimum]
	if not eligible:
		raise RuntimeError(
			f"OECD revenue statistics {indicator['id']} has no default year with at least {minimum} mapped countries."
		)
	return eligible[-1]


def build_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_iso3: dict[str, str],
	values: dict[int, dict[str, int | float]],
	ignored_codes: set[str],
	observation_statuses: set[str],
	source_rows: int,
	retained_rows: int,
) -> dict[str, Any]:
	provider = config["provider"]
	available_years = sorted(year for year, mapped in values.items() if mapped)
	mapped_areas = {area_id for mapped in values.values() for area_id in mapped}
	if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"OECD revenue coverage too small for {indicator['id']}: {len(mapped_areas)} mapped countries, "
			f"expected at least {indicator['minAreasWithAnyValue']}."
		)
	default_year = choose_default_year(indicator, available_years, values)
	for area_id in indicator["requiredAreas"]:
		if area_id not in values[default_year]:
			raise RuntimeError(
				f"OECD revenue {indicator['id']} default year {default_year} is missing required area {area_id}."
			)

	latest_year = available_years[-1]
	dimension_filters = dict(config["dimensions"])
	dimension_filters["STANDARD_REVENUE"] = indicator["standardRevenue"]
	dimension_filters["REVENUE_CODE"] = indicator["revenueCode"]
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
			"dimensionFilters": dimension_filters,
			"observationStatuses": sorted(observation_statuses),
			"ignoredAreaCodes": sorted(ignored_codes),
			"sourceRows": source_rows,
			"retainedRows": retained_rows,
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(mapped_areas),
			"latestYear": latest_year,
			"areasInLatestYear": len(values[latest_year]),
			"areasInDefaultYear": len(values[default_year]),
			"observations": retained_rows,
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
		f"{indicator['id']}: observations={retained_rows} mapped={len(mapped_areas)} "
		f"years={available_years[0]}-{latest_year} latestCoverage={len(values[latest_year])} "
		f"defaultYear={default_year} defaultCoverage={len(values[default_year])} "
		f"ignored={sorted(ignored_codes) or '(none)'}"
	)
	return payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("OECD revenue statistics is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	print(f"Fetching OECD Global Revenue Statistics from {config['apiUrl']}")
	(
		values_by_indicator,
		ignored_codes_by_indicator,
		observation_statuses_by_indicator,
		source_rows_by_indicator,
		retained_rows_by_indicator,
		headers,
	) = load_values(config, area_by_iso3, args.timeout)

	payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		payload = build_payload(
			config,
			indicator,
			area_by_iso3,
			values_by_indicator[indicator_id],
			ignored_codes_by_indicator[indicator_id],
			observation_statuses_by_indicator[indicator_id],
			source_rows_by_indicator[indicator_id],
			retained_rows_by_indicator[indicator_id],
		)
		payloads.append((indicator, payload))

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
				"sourceIndicator": indicator["sourceIndicator"],
				"path": f"releases/{snapshot}/{filename}",
				"availableYears": payload["availableYears"],
				"defaultYear": payload["defaultYear"],
				"coverage": payload["coverage"],
			}
		)

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_iso3),
	}
	if registry_source["url"] is None:
		registry_source.pop("url")

	all_ignored_codes = sorted(
		{
			code
			for codes in ignored_codes_by_indicator.values()
			for code in codes
		}
	)
	all_statuses = sorted(
		{
			status
			for statuses in observation_statuses_by_indicator.values()
			for status in statuses
		}
	)
	dataset = {
		"url": config["sourceUrl"],
		"apiUrl": config["apiUrl"],
		"dataflow": config["dataflow"],
		"sourceRows": sum(source_rows_by_indicator.values()),
		"retainedRows": sum(retained_rows_by_indicator.values()),
		"ignoredAreaCodes": all_ignored_codes,
		"observationStatuses": all_statuses,
		"indicatorRows": {
			indicator_id: {
				"sourceRows": source_rows_by_indicator[indicator_id],
				"retainedRows": retained_rows_by_indicator[indicator_id],
			}
			for indicator_id in sorted(source_rows_by_indicator)
		},
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
		"indicators": index_indicators,
		"notes": [
			"Direct OECD Global Revenue Statistics for the general government sector (S13), measured as percent of GDP.",
			"The provider includes the total tax-and-contribution burden plus selected harmonized tax-structure categories: personal income, corporate income, social security contributions, property and VAT.",
			"Real zero values are retained as observations and are never converted to missing values.",
			"The OECD tax concept includes compulsory social security contributions paid to general government and covers all levels of government.",
			"No World Bank WDI or other provider is used as a fallback because narrower central-government tax series are not conceptually equivalent.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Observation statuses: {all_statuses or '(none)'}")
	print(f"Built OECD revenue statistics snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
