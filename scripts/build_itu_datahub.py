#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "itu-datahub-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build normalized country ICT statistics from the ITU DataHub export."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.itu-datahub-statistics/v1":
		raise ValueError("Invalid ITU DataHub statistics config.")
	for key in ("downloadUrl", "catalogUrl", "sourceUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"ITU DataHub {key} must use HTTPS.")
	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "itu-datahub":
		raise ValueError("ITU DataHub provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"ITU DataHub provider metadata is missing {key}.")
	distribution = payload.get("distribution")
	if not isinstance(distribution, dict):
		raise ValueError("ITU DataHub distribution metadata is missing.")
	for key in ("provider", "datasetId", "resourceId"):
		if not str(distribution.get(key, "")).strip():
			raise ValueError(f"ITU DataHub distribution metadata is missing {key}.")
	fallback = payload.get("wdiFallback")
	if not isinstance(fallback, dict) or not str(fallback.get("apiBase", "")).startswith("https://"):
		raise ValueError("ITU DataHub WDI fallback metadata is invalid.")
	if not isinstance(fallback.get("sourceId"), int) or int(fallback["sourceId"]) <= 0:
		raise ValueError("ITU DataHub WDI fallback sourceId is invalid.")
	for key in ("providerId", "providerName"):
		if not str(fallback.get(key, "")).strip():
			raise ValueError(f"ITU DataHub WDI fallback metadata is missing {key}.")
	invariants = payload.get("sourceInvariants")
	if not isinstance(invariants, dict) or not invariants:
		raise ValueError("ITU DataHub source invariants are missing.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("ITU DataHub config requires indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("ITU DataHub indicator entries must be objects.")
		for key in (
			"id", "slug", "sourceIndicator", "sourceIndicatorName", "fallbackWdiIndicator",
			"title", "description",
		):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"ITU DataHub indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate ITU DataHub indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate ITU DataHub indicator slug: {slug}")
		ids.add(indicator_id)
		slugs.add(slug)
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"ITU DataHub indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		filters = indicator.get("filters")
		if not isinstance(filters, dict) or not filters:
			raise ValueError(f"ITU DataHub indicator {indicator_id} has no source filters.")
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear", "minimumLatestYear", "minimumDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"ITU DataHub indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"ITU DataHub indicator {indicator_id} requires at least one required area.")
	return payload


def fetch_csv(url: str, timeout: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 3, 10, 20, 40), start=1):
		if delay:
			time.sleep(delay)
		request = Request(
			url,
			headers={
				"Accept": "text/csv,*/*",
				"User-Agent": USER_AGENT,
			},
		)
		try:
			with urlopen(request, timeout=timeout) as response:
				body = response.read()
				content_type = str(response.headers.get("Content-Type") or "")
				last_modified = str(response.headers.get("Last-Modified") or "").strip() or None
			text = body.decode("utf-8-sig")
			reader = csv.DictReader(io.StringIO(text))
			if not reader.fieldnames:
				raise RuntimeError("ITU DataHub CSV has no header.")
			rows = list(reader)
			if not rows:
				raise RuntimeError("ITU DataHub CSV has no rows.")
			return rows, {
				"bytes": len(body),
				"rows": len(rows),
				"contentType": content_type,
				"lastModified": last_modified,
				"columns": list(reader.fieldnames),
			}
		except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, csv.Error, RuntimeError) as error:
			last_error = error
			print(f"ITU DataHub download failed ({attempt}/5): {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"ITU DataHub download failed without an exception: {url}")
	raise RuntimeError(f"ITU DataHub download failed after 5 attempts: {url}") from last_error


def row_matches(row: dict[str, str], filters: dict[str, Any]) -> bool:
	return all(str(row.get(key, "")).strip() == str(value) for key, value in filters.items())


def validate_value(indicator_id: str, area_id: str, year: int, value: int | float, source: str) -> None:
	if not math.isfinite(float(value)) or float(value) < 0 or float(value) > 100:
		raise RuntimeError(
			f"Invalid {source} percentage for {indicator_id} {area_id} {year}: {value}"
		)


def parse_direct_values(
	config: dict[str, Any],
	indicator: dict[str, Any],
	rows: list[dict[str, str]],
	area_by_iso3: dict[str, str],
	now_year: int,
) -> tuple[dict[int, dict[str, int | float]], dict[str, Any]]:
	required_columns = {
		"INDICATOR", "TIME_PERIOD", "REF_AREA", "OBS_VALUE",
		*indicator["filters"].keys(), *config["sourceInvariants"].keys(),
	}
	missing_columns = sorted(required_columns - set(rows[0]))
	if missing_columns:
		raise RuntimeError(f"ITU DataHub CSV is missing columns: {', '.join(missing_columns)}")

	source_rows = [
		row for row in rows
		if str(row.get("INDICATOR", "")).strip() == str(indicator["sourceIndicator"])
		and row_matches(row, indicator["filters"])
	]
	if not source_rows:
		raise RuntimeError(f"ITU DataHub returned no rows for {indicator['sourceIndicator']}.")

	for field, expected in config["sourceInvariants"].items():
		observed = {str(row.get(field, "")).strip() for row in source_rows}
		if observed != {str(expected)}:
			raise RuntimeError(
				f"Unexpected ITU DataHub {field} values for {indicator['id']}: {sorted(observed)}"
			)

	values_by_year: dict[int, dict[str, int | float]] = {}
	ignored_codes: set[str] = set()
	direct_observations = 0
	for row in source_rows:
		iso3 = str(row.get("REF_AREA", "")).strip().upper()
		if iso3 not in area_by_iso3:
			if iso3:
				ignored_codes.add(iso3)
			continue
		year_text = str(row.get("TIME_PERIOD", "")).strip()
		if len(year_text) != 4 or not year_text.isdigit():
			continue
		year = int(year_text)
		if year > now_year:
			continue
		value_text = str(row.get("OBS_VALUE", "")).strip()
		if not value_text:
			continue
		value = common.normalize_number(value_text)
		area_id = area_by_iso3[iso3]
		validate_value(str(indicator["id"]), area_id, year, value, "ITU DataHub")
		year_values = values_by_year.setdefault(year, {})
		if area_id in year_values:
			raise RuntimeError(f"Duplicate ITU DataHub value for {indicator['id']} {area_id} {year}.")
		year_values[area_id] = value
		direct_observations += 1

	if not values_by_year:
		raise RuntimeError(f"ITU DataHub returned no mapped country values for {indicator['id']}.")
	return values_by_year, {
		"sourceRows": len(source_rows),
		"directObservations": direct_observations,
		"ignoredCodes": sorted(ignored_codes),
		"directStartYear": min(values_by_year),
		"directEndYear": max(values_by_year),
	}


def add_wdi_fallback(
	config: dict[str, Any],
	indicator: dict[str, Any],
	values_by_year: dict[int, dict[str, int | float]],
	area_by_iso3: dict[str, str],
	now_year: int,
	timeout: int,
) -> tuple[dict[int, dict[str, dict[str, Any]]], dict[str, Any]]:
	fallback_config = config["wdiFallback"]
	fallback_code = str(indicator["fallbackWdiIndicator"])
	records = common.fetch_world_bank_records(
		str(fallback_config["apiBase"]).rstrip("/"),
		f"country/all/indicator/{fallback_code}",
		int(fallback_config["sourceId"]),
		timeout,
	)
	metadata: dict[int, dict[str, dict[str, Any]]] = {}
	fallback_count = 0
	fallback_areas: set[str] = set()
	overlap_count = 0
	overlap_differences = 0
	max_overlap_difference = 0.0
	fallback_years: set[int] = set()

	for record in records:
		if record.get("value") is None:
			continue
		if str(record.get("obs_status", "")).strip().upper() == "F":
			continue
		iso3 = str(record.get("countryiso3code", "")).strip().upper()
		if iso3 not in area_by_iso3:
			continue
		year_text = str(record.get("date", "")).strip()
		if len(year_text) != 4 or not year_text.isdigit():
			continue
		year = int(year_text)
		if year > now_year:
			continue
		value = common.normalize_number(record["value"])
		area_id = area_by_iso3[iso3]
		validate_value(str(indicator["id"]), area_id, year, value, "WDI fallback")
		year_values = values_by_year.setdefault(year, {})
		if area_id in year_values:
			overlap_count += 1
			difference = abs(float(year_values[area_id]) - float(value))
			max_overlap_difference = max(max_overlap_difference, difference)
			if difference > 1e-9:
				overlap_differences += 1
			continue
		year_values[area_id] = value
		metadata.setdefault(year, {})[area_id] = {
			"fallback": True,
			"sourceProviderId": str(fallback_config["providerId"]),
			"sourceProviderName": str(fallback_config["providerName"]),
			"sourceIndicator": fallback_code,
			"provenance": "ITU-origin value distributed by World Bank WDI; used only where the ITU DataHub export has no country-year observation",
		}
		fallback_count += 1
		fallback_areas.add(area_id)
		fallback_years.add(year)

	return metadata, {
		"fallbackObservations": fallback_count,
		"fallbackAreas": len(fallback_areas),
		"fallbackYears": sorted(fallback_years),
		"overlapObservations": overlap_count,
		"overlapDifferences": overlap_differences,
		"maxOverlapDifference": max_overlap_difference,
	}


def build_indicator_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	rows: list[dict[str, str]],
	area_by_iso3: dict[str, str],
	now_year: int,
	timeout: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
	values_by_year, direct_stats = parse_direct_values(config, indicator, rows, area_by_iso3, now_year)
	fallback_metadata, fallback_stats = add_wdi_fallback(
		config, indicator, values_by_year, area_by_iso3, now_year, timeout
	)
	available_years = sorted(year for year, values in values_by_year.items() if values)
	areas_with_any_value = set().union(*(set(values_by_year[year]) for year in available_years))
	if len(areas_with_any_value) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"ITU DataHub coverage too small for {indicator['id']}: {len(areas_with_any_value)} areas."
		)
	default_candidates = [
		year for year in available_years
		if len(values_by_year[year]) >= int(indicator["minAreasInDefaultYear"])
	]
	if not default_candidates:
		raise RuntimeError(f"ITU DataHub has no sufficiently covered default year for {indicator['id']}.")
	default_year = default_candidates[-1]
	if available_years[-1] < int(indicator["minimumLatestYear"]):
		raise RuntimeError(
			f"ITU DataHub latest year is too old for {indicator['id']}: {available_years[-1]}."
		)
	if default_year < int(indicator["minimumDefaultYear"]):
		raise RuntimeError(
			f"ITU DataHub default year is too old for {indicator['id']}: {default_year}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in values_by_year[default_year]:
			raise RuntimeError(
				f"Required area {area_id} has no ITU DataHub value for {indicator['id']} in {default_year}."
			)

	provider = config["provider"]
	fallback_config = config["wdiFallback"]
	source = {
		"providerId": provider["id"],
		"providerName": provider["name"],
		"dataset": provider["dataset"],
		"indicator": indicator["sourceIndicator"],
		"indicatorName": indicator["sourceIndicatorName"],
		"provenance": "ITU DataHub observations distributed as a public CSV through the World Bank Data Catalog",
		"license": provider["license"],
		"licenseUrl": provider["licenseUrl"],
		"attribution": provider["attribution"],
		"url": config["sourceUrl"],
		"downloadUrl": config["downloadUrl"],
		"catalogUrl": config["catalogUrl"],
		"distribution": config["distribution"],
		"filters": indicator["filters"],
		"sourceInvariants": config["sourceInvariants"],
		"timeCoverage": {
			"startYear": direct_stats["directStartYear"],
			"endYear": direct_stats["directEndYear"],
		},
		"fallback": {
			"providerId": fallback_config["providerId"],
			"providerName": fallback_config["providerName"],
			"indicator": indicator["fallbackWdiIndicator"],
			"usage": "Only country-year observations missing from the ITU DataHub export",
			"provenance": "ITU-origin series distributed by World Bank WDI",
		},
	}
	payload: dict[str, Any] = {
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
		"source": source,
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": available_years[-1],
			"areasInLatestYear": len(values_by_year[available_years[-1]]),
			"areasInDefaultYear": len(values_by_year[default_year]),
			"observations": sum(len(values) for values in values_by_year.values()),
			"directObservations": direct_stats["directObservations"],
			"fallbackObservations": fallback_stats["fallbackObservations"],
			"fallbackAreas": fallback_stats["fallbackAreas"],
		},
		"values": {
			str(year): {area_id: values_by_year[year][area_id] for area_id in sorted(values_by_year[year])}
			for year in available_years
		},
	}
	if fallback_metadata:
		payload["observationMetadata"] = {
			str(year): {area_id: fallback_metadata[year][area_id] for area_id in sorted(fallback_metadata[year])}
			for year in sorted(fallback_metadata)
		}

	stats = {**direct_stats, **fallback_stats}
	print(
		f"{indicator['id']}: direct={stats['directObservations']} fallback={stats['fallbackObservations']} "
		f"areas={len(areas_with_any_value)} years={available_years[0]}-{available_years[-1]} "
		f"defaultYear={default_year} defaultCoverage={len(values_by_year[default_year])} "
		f"overlap={stats['overlapObservations']} overlapDiffs={stats['overlapDifferences']} "
		f"ignoredCodes={len(stats['ignoredCodes'])}"
	)
	return payload, stats


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("ITU DataHub is missing from statistics-providers.json.")
	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	now = common.utc_now()
	rows, download_metadata = fetch_csv(config["downloadUrl"], args.timeout)
	print(
		f"ITU DataHub CSV: rows={download_metadata['rows']} bytes={download_metadata['bytes']} "
		f"lastModified={download_metadata.get('lastModified')}"
	)

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload, stats = build_indicator_payload(
			config, indicator, rows, area_by_iso3, now.year, args.timeout
		)
		indicator_payloads.append((indicator, payload, stats))

	hasher = hashlib.sha256()
	for indicator, payload, _ in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8") + b"\0" + common.canonical_bytes(payload) + b"\0")
	snapshot = hasher.hexdigest()[:16]
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []
	for indicator, payload, _ in indicator_payloads:
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
			"sourceUrl": config["sourceUrl"],
			"catalogUrl": config["catalogUrl"],
			"downloadUrl": config["downloadUrl"],
			"distribution": config["distribution"],
			"rows": download_metadata["rows"],
			"bytes": download_metadata["bytes"],
			"lastModified": download_metadata.get("lastModified"),
		},
		"indicators": index_indicators,
		"notes": [
			"ITU DataHub observations are canonical from 2000 onward.",
			"The public ITU DataHub CSV is retrieved from the World Bank Data Catalog distribution of the ITU dataset.",
			"World Bank WDI is used only for country-year observations missing from the ITU DataHub export and every fallback is marked in observationMetadata.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))

	print(f"Built ITU DataHub snapshot {snapshot}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
