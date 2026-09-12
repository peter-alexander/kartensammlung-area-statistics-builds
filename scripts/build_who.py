#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pycountry

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "who-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized country statistics from WHO World Health Data Hub CSV files.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=60)
	return parser.parse_args()


def validate_year(value: Any, label: str) -> int:
	if not isinstance(value, int) or not 1900 <= value <= 2200:
		raise ValueError(f"{label} is invalid.")
	return value


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.who-statistics/v1":
		raise ValueError("Invalid WHO statistics config.")
	provider = payload.get("provider")
	if not isinstance(provider, dict):
		raise ValueError("WHO provider metadata is required.")
	for key in ("id", "name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"WHO provider metadata is missing {key}.")
	if provider.get("id") != "who":
		raise ValueError("WHO provider id must be 'who'.")
	if "expectedReferenceYear" in payload:
		validate_year(payload["expectedReferenceYear"], "WHO expectedReferenceYear")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("WHO config requires indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("WHO indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "sourceUuid", "sourceUrl", "downloadUrl", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"WHO indicator entry is missing {key}.")
		if not str(indicator["sourceUrl"]).startswith("https://") or not str(indicator["downloadUrl"]).startswith("https://"):
			raise ValueError(f"WHO indicator {indicator['id']} source URLs must use HTTPS.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		if indicator_id in ids or slug in slugs:
			raise ValueError(f"Duplicate WHO indicator metadata: {indicator_id}.")
		ids.add(indicator_id)
		slugs.add(slug)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"WHO indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		if not isinstance(indicator.get("minAreasWithAnyValue"), int) or int(indicator["minAreasWithAnyValue"]) <= 0:
			raise ValueError(f"WHO indicator {indicator_id} has invalid minAreasWithAnyValue.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"WHO indicator {indicator_id} requires requiredAreas.")

		dimension_filters = indicator.get("dimensionFilters", {})
		if not isinstance(dimension_filters, dict) or any(not str(key).strip() or not str(value).strip() for key, value in dimension_filters.items()):
			raise ValueError(f"WHO indicator {indicator_id} has invalid dimensionFilters.")
		confidence_intervals = indicator.get("confidenceIntervals", True)
		if not isinstance(confidence_intervals, bool):
			raise ValueError(f"WHO indicator {indicator_id} has invalid confidenceIntervals flag.")
		for field_name in ("valueField", "lowerField", "upperField", "fallbackWdiIndicator"):
			if field_name in indicator and not str(indicator[field_name]).strip():
				raise ValueError(f"WHO indicator {indicator_id} has invalid {field_name}.")
		if "startYear" in indicator or "endYear" in indicator:
			start_year = validate_year(indicator.get("startYear"), f"WHO indicator {indicator_id} startYear")
			end_year = validate_year(indicator.get("endYear"), f"WHO indicator {indicator_id} endYear")
			if start_year > end_year:
				raise ValueError(f"WHO indicator {indicator_id} startYear exceeds endYear.")
		if "expectedReferenceYear" in indicator:
			validate_year(indicator["expectedReferenceYear"], f"WHO indicator {indicator_id} expectedReferenceYear")
		value_range = indicator.get("valueRange")
		if value_range is not None:
			if not isinstance(value_range, list) or len(value_range) != 2:
				raise ValueError(f"WHO indicator {indicator_id} has invalid valueRange.")
			low, high = value_range
			if not isinstance(low, (int, float)) or not isinstance(high, (int, float)) or not math.isfinite(float(low)) or not math.isfinite(float(high)) or float(low) >= float(high):
				raise ValueError(f"WHO indicator {indicator_id} has invalid valueRange.")
	return payload


def normalize_m49(value: Any) -> str:
	text = str(value if value is not None else "").strip()
	if not text:
		return ""
	try:
		number = int(float(text))
	except ValueError:
		return ""
	return str(number)


def load_registry_by_m49(source: str, timeout: int) -> tuple[dict[str, str], dict[str, Any]]:
	area_by_iso3, payload = common.load_registry(source, timeout)
	area_by_m49: dict[str, str] = {}
	for country in pycountry.countries:
		iso3 = str(getattr(country, "alpha_3", "")).strip().upper()
		m49 = normalize_m49(getattr(country, "numeric", ""))
		if not iso3 or not m49 or iso3 not in area_by_iso3:
			continue
		if m49 in area_by_m49:
			raise ValueError(f"Duplicate M49 code from ISO-3166 mapping: {m49}")
		area_by_m49[m49] = area_by_iso3[iso3]
	if len(area_by_m49) < 245:
		raise RuntimeError(f"ISO-3166/M49 mapping unexpectedly small: {len(area_by_m49)} country areas.")
	for required in ("40", "276", "840", "356"):
		if required not in area_by_m49:
			raise RuntimeError(f"M49 sanity check failed: {required} is missing.")
	return area_by_m49, payload


def fetch_bytes(url: str, timeout: int, accept: str) -> bytes:
	delays = (0, 5, 15, 30)
	last_error: Exception | None = None
	for attempt, delay in enumerate(delays, start=1):
		if delay:
			time.sleep(delay)
		request = Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
		try:
			with urlopen(request, timeout=timeout) as response:
				return response.read()
		except (HTTPError, URLError, TimeoutError) as error:
			last_error = error
			print(f"Request failed ({attempt}/{len(delays)}): {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"Request failed without exception: {url}")
	raise RuntimeError(f"Request failed after {len(delays)} attempts: {url}") from last_error


def fetch_csv(url: str, timeout: int, cache: dict[str, tuple[list[dict[str, str]], int]]) -> tuple[list[dict[str, str]], int]:
	if url in cache:
		return cache[url]
	try:
		data = fetch_bytes(url, timeout, "text/csv,*/*")
		text = data.decode("utf-8-sig")
		rows = list(csv.DictReader(io.StringIO(text)))
	except (UnicodeDecodeError, csv.Error) as error:
		raise RuntimeError(f"WHO CSV could not be parsed: {url}") from error
	if not rows:
		raise RuntimeError(f"WHO CSV is empty: {url}")
	cache[url] = (rows, len(data))
	return cache[url]


def fetch_wdi(
	indicator_code: str,
	start_year: int,
	end_year: int,
	area_by_m49: dict[str, str],
	timeout: int,
	cache: dict[tuple[str, int, int], dict[tuple[str, int], int | float]],
) -> dict[tuple[str, int], int | float]:
	cache_key = (indicator_code, start_year, end_year)
	if cache_key in cache:
		return cache[cache_key]
	url = (
		f"https://api.worldbank.org/v2/country/all/indicator/{indicator_code}"
		f"?format=json&per_page=20000&date={start_year}:{end_year}"
	)
	try:
		payload = json.loads(fetch_bytes(url, timeout, "application/json,*/*").decode("utf-8"))
	except (UnicodeDecodeError, json.JSONDecodeError) as error:
		raise RuntimeError(f"World Bank WDI fallback could not be parsed for {indicator_code}.") from error
	if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], dict) or not isinstance(payload[1], list):
		raise RuntimeError(f"Unexpected World Bank WDI fallback response for {indicator_code}.")
	if int(payload[0].get("pages", 1)) != 1:
		raise RuntimeError(f"World Bank WDI fallback unexpectedly paginated for {indicator_code}.")

	values: dict[tuple[str, int], int | float] = {}
	for row in payload[1]:
		if not isinstance(row, dict) or row.get("value") is None:
			continue
		iso3 = str(row.get("countryiso3code") or "").strip().upper()
		country = pycountry.countries.get(alpha_3=iso3)
		if country is None:
			continue
		m49 = normalize_m49(getattr(country, "numeric", ""))
		if m49 not in area_by_m49:
			continue
		year_text = str(row.get("date") or "").strip()
		if not year_text.isdigit():
			continue
		year = int(year_text)
		if not start_year <= year <= end_year:
			continue
		value = parse_number(row["value"])
		values[(area_by_m49[m49], year)] = value
	cache[cache_key] = values
	print(f"WDI fallback {indicator_code}: mapped observations={len(values)}")
	return values


def parse_number(value: Any) -> int | float:
	if value is None or str(value).strip() == "":
		raise ValueError("Missing numeric value.")
	number = float(str(value).strip())
	if not math.isfinite(number):
		raise ValueError("Numeric value is not finite.")
	if number.is_integer():
		return int(number)
	return number


def indicator_year_window(config: dict[str, Any], indicator: dict[str, Any]) -> tuple[int, int]:
	if "startYear" in indicator or "endYear" in indicator:
		return int(indicator["startYear"]), int(indicator["endYear"])
	reference_year = indicator.get("expectedReferenceYear", config.get("expectedReferenceYear"))
	if not isinstance(reference_year, int):
		raise ValueError(f"WHO indicator {indicator['id']} has no year selection.")
	return reference_year, reference_year


def validate_value_range(indicator: dict[str, Any], area_id: str, year: int, value: int | float, label: str) -> None:
	value_range = indicator.get("valueRange")
	if value_range is None:
		return
	low, high = (float(value_range[0]), float(value_range[1]))
	if not low <= float(value) <= high:
		raise RuntimeError(
			f"WHO {label} out of range for {indicator['id']} {area_id} {year}: "
			f"{value} not in [{low}, {high}]"
		)


def normalize_indicator(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_m49: dict[str, str],
	timeout: int,
	csv_cache: dict[str, tuple[list[dict[str, str]], int]],
	wdi_cache: dict[tuple[str, int, int], dict[tuple[str, int], int | float]],
) -> dict[str, Any]:
	rows, byte_count = fetch_csv(str(indicator["downloadUrl"]), max(timeout, 90), csv_cache)
	print(f"WHO {indicator['sourceIndicator']}: downloaded={byte_count} bytes rows={len(rows)}")
	value_field = str(indicator.get("valueField", "RATE_PER_100_N"))
	has_confidence_intervals = bool(indicator.get("confidenceIntervals", True))
	lower_field = str(indicator.get("lowerField", "RATE_PER_100_NL")) if has_confidence_intervals else None
	upper_field = str(indicator.get("upperField", "RATE_PER_100_NU")) if has_confidence_intervals else None
	dimension_filters = {str(key): str(value) for key, value in indicator.get("dimensionFilters", {}).items()}
	required_fields = {
		"IND_CODE", "IND_UUID", "DIM_TIME", "DIM_TIME_TYPE", "DIM_GEO_CODE_M49",
		"DIM_GEO_CODE_TYPE", "DIM_PUBLISH_STATE_CODE", "IND_NAME", "GEO_NAME_SHORT",
		value_field, *dimension_filters.keys(),
	}
	if has_confidence_intervals:
		required_fields.update({str(lower_field), str(upper_field)})
	missing_fields = required_fields - set(rows[0])
	if missing_fields:
		raise RuntimeError(f"WHO CSV schema changed for {indicator['id']}: missing {sorted(missing_fields)}")

	start_year, end_year = indicator_year_window(config, indicator)
	values_by_year: dict[int, dict[str, int | float]] = {}
	intervals_by_year: dict[int, dict[str, dict[str, int | float]]] = {}
	ignored_m49: set[str] = set()
	direct_years: set[int] = set()
	direct_observations = 0
	for row in rows:
		if str(row.get("IND_CODE", "")).strip() != str(indicator["sourceIndicator"]):
			raise RuntimeError(f"WHO indicator code mismatch in {indicator['id']}.")
		if str(row.get("IND_UUID", "")).strip() != str(indicator["sourceUuid"]):
			raise RuntimeError(f"WHO indicator UUID mismatch in {indicator['id']}.")
		if str(row.get("DIM_TIME_TYPE", "")).strip() != "YEAR":
			continue
		if str(row.get("DIM_GEO_CODE_TYPE", "")).strip() != "COUNTRY":
			continue
		if str(row.get("DIM_PUBLISH_STATE_CODE", "")).strip() != "PUBLISHED":
			continue
		if any(str(row.get(field, "")).strip() != expected for field, expected in dimension_filters.items()):
			continue
		year_text = str(row.get("DIM_TIME", "")).strip()
		if not year_text.isdigit():
			continue
		year = int(year_text)
		if not start_year <= year <= end_year:
			continue
		m49 = normalize_m49(row.get("DIM_GEO_CODE_M49"))
		if m49 not in area_by_m49:
			if m49:
				ignored_m49.add(m49)
			continue
		area_id = area_by_m49[m49]
		value = parse_number(row.get(value_field))
		validate_value_range(indicator, area_id, year, value, "value")
		interval = None
		if has_confidence_intervals:
			lower = parse_number(row.get(str(lower_field)))
			upper = parse_number(row.get(str(upper_field)))
			validate_value_range(indicator, area_id, year, lower, "confidence lower bound")
			validate_value_range(indicator, area_id, year, upper, "confidence upper bound")
			if not float(lower) <= float(value) <= float(upper):
				raise RuntimeError(
					f"WHO confidence interval is invalid for {indicator['id']} {area_id} {year}: "
					f"{lower}, {value}, {upper}"
				)
			interval = {"lower": lower, "upper": upper}
		year_values = values_by_year.setdefault(year, {})
		if area_id in year_values:
			raise RuntimeError(f"Duplicate WHO country value for {indicator['id']} {area_id} {year}.")
		year_values[area_id] = value
		if interval is not None:
			intervals_by_year.setdefault(year, {})[area_id] = interval
		direct_years.add(year)
		direct_observations += 1

	fallback_metadata: dict[int, dict[str, dict[str, Any]]] = {}
	fallback_count = 0
	fallback_countries: set[str] = set()
	fallback_code = str(indicator.get("fallbackWdiIndicator", "")).strip()
	if fallback_code:
		fallback_values = fetch_wdi(fallback_code, start_year, end_year, area_by_m49, timeout, wdi_cache)
		for (area_id, year), value in sorted(fallback_values.items()):
			year_values = values_by_year.setdefault(year, {})
			if area_id in year_values:
				continue
			validate_value_range(indicator, area_id, year, value, "WDI fallback value")
			year_values[area_id] = value
			fallback_metadata.setdefault(year, {})[area_id] = {
				"fallback": True,
				"sourceProviderId": "world-bank",
				"sourceProviderName": "World Bank WDI",
				"sourceIndicator": fallback_code,
				"provenance": "WHO-origin value distributed by World Bank WDI",
			}
			fallback_count += 1
			fallback_countries.add(area_id)

	available_years = sorted(year for year, values in values_by_year.items() if values)
	if not available_years:
		raise RuntimeError(f"WHO indicator {indicator['id']} has no mapped values in {start_year}-{end_year}.")
	minimum = int(indicator["minAreasWithAnyValue"])
	areas_with_any_value = set().union(*(set(values_by_year[year]) for year in available_years))
	if len(areas_with_any_value) < minimum:
		raise RuntimeError(
			f"WHO coverage too small for {indicator['id']}: {len(areas_with_any_value)} areas, "
			f"expected at least {minimum}."
		)
	broad_years = [year for year in available_years if len(values_by_year[year]) >= minimum]
	default_year = max(broad_years or available_years)
	for area_id in indicator["requiredAreas"]:
		if area_id not in values_by_year[default_year]:
			raise RuntimeError(f"Required area {area_id} has no WHO value for {indicator['id']} in {default_year}.")

	frequency = "annual" if len(available_years) > 1 else "reference-year"
	indicator_metadata = {
		"id": indicator["id"],
		"title": indicator["title"],
		"description": indicator["description"],
		"areaLevel": "country",
		"frequency": frequency,
		"unit": indicator["unit"],
		"classification": indicator["classification"],
		"confidenceIntervals": (
			{"available": True, "lowerField": lower_field, "upperField": upper_field}
			if has_confidence_intervals else {"available": False}
		),
	}
	provider = config["provider"]
	source: dict[str, Any] = {
		"providerId": provider["id"],
		"providerName": provider["name"],
		"dataset": provider["dataset"],
		"indicator": indicator["sourceIndicator"],
		"indicatorUuid": indicator["sourceUuid"],
		"indicatorName": next((str(row.get("IND_NAME", "")).strip() for row in rows if str(row.get("IND_NAME", "")).strip()), None),
		"provenance": str(indicator.get("provenance", "WHO official estimate")),
		"license": provider["license"],
		"licenseUrl": provider["licenseUrl"],
		"attribution": provider["attribution"],
		"url": indicator["sourceUrl"],
		"downloadUrl": indicator["downloadUrl"],
		"valueField": value_field,
	}
	if dimension_filters:
		source["dimensionFilters"] = dimension_filters
	direct_available_years = sorted(direct_years)
	if len(direct_available_years) == 1:
		source["referenceYear"] = direct_available_years[0]
	elif direct_available_years:
		source["timeCoverage"] = {"startYear": direct_available_years[0], "endYear": direct_available_years[-1]}
	if fallback_code:
		source["fallback"] = {
			"providerId": "world-bank",
			"providerName": "World Bank WDI",
			"indicator": fallback_code,
			"usage": "Only country-year observations missing from the direct WHO dataset",
			"provenance": "WHO-origin series distributed by World Bank WDI",
		}

	payload: dict[str, Any] = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": indicator_metadata,
		"source": source,
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_m49),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": available_years[-1],
			"areasInLatestYear": len(values_by_year[available_years[-1]]),
			"areasInDefaultYear": len(values_by_year[default_year]),
			"directObservations": direct_observations,
			"fallbackObservations": fallback_count,
			"fallbackAreas": len(fallback_countries),
		},
		"values": {
			str(year): {area_id: values_by_year[year][area_id] for area_id in sorted(values_by_year[year])}
			for year in available_years
		},
		"confidenceIntervals": {
			"values": {
				str(year): {area_id: intervals_by_year[year][area_id] for area_id in sorted(intervals_by_year[year])}
				for year in sorted(intervals_by_year)
				if intervals_by_year[year]
			},
		},
	}
	if fallback_metadata:
		payload["observationMetadata"] = {
			str(year): {area_id: fallback_metadata[year][area_id] for area_id in sorted(fallback_metadata[year])}
			for year in sorted(fallback_metadata)
		}
	print(
		f"{indicator['id']}: direct={direct_observations} fallback={fallback_count} "
		f"areas={len(areas_with_any_value)} years={available_years[0]}-{available_years[-1]} "
		f"defaultYear={default_year} defaultCoverage={len(values_by_year[default_year])} "
		f"ignoredM49={sorted(ignored_m49) or '(none)'}"
	)
	return payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("WHO is missing from statistics-providers.json.")
	area_by_m49, registry_payload = load_registry_by_m49(args.registry, args.timeout)
	now = datetime.now(timezone.utc)
	csv_cache: dict[str, tuple[list[dict[str, str]], int]] = {}
	wdi_cache: dict[tuple[str, int, int], dict[tuple[str, int], int | float]] = {}
	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload = normalize_indicator(config, indicator, area_by_m49, args.timeout, csv_cache, wdi_cache)
		indicator_payloads.append((indicator, payload))

	hasher = hashlib.sha256()
	for indicator, payload in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8") + b"\0" + common.canonical_bytes(payload) + b"\0")
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
			"frequency": payload["indicator"]["frequency"],
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"sourceIndicator": indicator["sourceIndicator"],
			"sourceUuid": indicator["sourceUuid"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
			"confidenceIntervals": bool(payload["indicator"]["confidenceIntervals"]["available"]),
		})

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_m49),
	}
	if registry_source["url"] is None:
		registry_source.pop("url")
	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"indicators": index_indicators,
		"notes": [
			"Direct WHO World Health Data Hub observations are canonical.",
			"Confidence intervals from WHO are preserved in each indicator payload where available.",
			"Configured World Bank WDI fallbacks are used only for country-year gaps in WHO-origin series and are marked in observationMetadata.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built WHO snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
