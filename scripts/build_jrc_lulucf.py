#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "jrc-lulucf-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
EXPECTED_COLUMNS = ["ISO3", "Version", "Source", "Gas", "Year", "Category", "CFluxes_yr"]


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build country LULUCF CO2 statistics from the JRC LULUCF Data Hub."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.jrc-lulucf-statistics/v1":
		raise ValueError("Invalid JRC LULUCF statistics config.")
	for key in ("sourceUrl", "downloadUrl", "metadataUrl", "doiUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"JRC LULUCF {key} must use HTTPS.")
	for key in ("recordId", "releaseVersion", "sourceVersion", "sourceFile", "expectedChecksum"):
		if not str(payload.get(key, "")).strip():
			raise ValueError(f"JRC LULUCF config is missing {key}.")
	if payload.get("expectedStartYear") != 2000 or payload.get("expectedLatestYear") != 2023:
		raise ValueError("JRC LULUCF expected source years must be 2000-2023.")
	expected_categories = payload.get("expectedCategories")
	if expected_categories != ["DEFORESTATION", "FOREST", "HWP", "LULUCF", "ORG_SOILS", "OTHER"]:
		raise ValueError("JRC LULUCF expectedCategories changed unexpectedly.")
	expected_submissions = payload.get("expectedSubmissions")
	if expected_submissions != ["2023 (pre-Paris)", "CRT_2024", "CRT_2025"]:
		raise ValueError("JRC LULUCF expectedSubmissions changed unexpectedly.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "jrc-lulucf":
		raise ValueError("JRC LULUCF provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"JRC LULUCF provider metadata is missing {key}.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 3:
		raise ValueError("JRC LULUCF config requires exactly three indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	categories: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("JRC LULUCF indicator entries must be objects.")
		for key in ("id", "slug", "sourceCategory", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"JRC LULUCF indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		category = str(indicator["sourceCategory"]).upper()
		if indicator_id in ids or slug in slugs or category in categories:
			raise ValueError(f"Duplicate JRC LULUCF indicator metadata for {indicator_id}.")
		ids.add(indicator_id)
		slugs.add(slug)
		categories.add(category)
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or unit.get("id") != "mt-co2e":
			raise ValueError(f"JRC LULUCF indicator {indicator_id} must preserve the mt-co2e target unit.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"JRC LULUCF indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"JRC LULUCF indicator {indicator_id} requires requiredAreas.")
	if categories != {"LULUCF", "DEFORESTATION", "FOREST"}:
		raise ValueError(f"Unexpected configured JRC LULUCF categories: {sorted(categories)}")
	return payload


def fetch_bytes(url: str, timeout: int, accept: str) -> bytes:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 3, 10, 20, 40), start=1):
		if delay:
			time.sleep(delay)
		try:
			request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
			with urlopen(request, timeout=timeout) as response:
				return response.read()
		except (HTTPError, URLError, TimeoutError, OSError) as error:
			last_error = error
			print(f"Request failed ({attempt}/5): {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"Request failed without an exception: {url}")
	raise RuntimeError(f"Request failed after 5 attempts: {url}") from last_error


def load_zenodo_metadata(config: dict[str, Any], timeout: int) -> dict[str, Any]:
	raw = fetch_bytes(str(config["metadataUrl"]), timeout, "application/json, */*")
	payload = json.loads(raw.decode("utf-8"))
	metadata = payload.get("metadata") or {}
	if str(payload.get("id")) != str(config["recordId"]):
		raise RuntimeError(f"Unexpected Zenodo record ID: {payload.get('id')!r}.")
	license_id = (metadata.get("license") or {}).get("id")
	if license_id != "cc-by-4.0":
		raise RuntimeError(f"Unexpected JRC LULUCF Zenodo license: {license_id!r}.")
	files = payload.get("files") or []
	file_metadata = next((item for item in files if item.get("key") == config["sourceFile"]), None)
	if file_metadata is None:
		raise RuntimeError(f"Zenodo record is missing {config['sourceFile']!r}.")
	checksum = str(file_metadata.get("checksum") or "")
	if checksum != config["expectedChecksum"]:
		raise RuntimeError(
			f"JRC LULUCF source checksum changed: {checksum!r}, expected {config['expectedChecksum']!r}."
		)
	size = file_metadata.get("size")
	if not isinstance(size, int) or size < 500_000:
		raise RuntimeError(f"JRC LULUCF source size is invalid: {size!r}.")
	return {
		"title": str(metadata.get("title") or ""),
		"publicationDate": str(metadata.get("publication_date") or ""),
		"licenseId": license_id,
		"checksum": checksum,
		"bytes": size,
	}


def load_direct_values(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	timeout: int,
	expected_bytes: int,
) -> tuple[
	dict[str, dict[int, dict[str, int | float]]],
	set[str],
	int,
	int,
	set[str],
	set[str],
	set[str],
	Counter[str],
]:
	raw = fetch_bytes(
		str(config["downloadUrl"]),
		timeout,
		"text/csv, application/octet-stream, */*",
	)
	if len(raw) != expected_bytes:
		raise RuntimeError(
			f"JRC LULUCF downloaded byte count differs from Zenodo metadata: "
			f"{len(raw)} != {expected_bytes}."
		)
	reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
	if reader.fieldnames != EXPECTED_COLUMNS:
		raise RuntimeError(f"JRC LULUCF CSV columns changed: {reader.fieldnames}")

	indicator_by_category = {
		str(indicator["sourceCategory"]).upper(): indicator
		for indicator in config["indicators"]
	}
	values: dict[str, dict[int, dict[str, int | float]]] = {
		str(indicator["id"]): defaultdict(dict)
		for indicator in config["indicators"]
	}
	ignored_iso3: set[str] = set()
	source_years: set[int] = set()
	source_versions: set[str] = set()
	source_submissions: set[str] = set()
	source_categories: set[str] = set()
	source_counts: Counter[str] = Counter()

	for row in reader:
		gas = str(row.get("Gas") or "").strip().upper()
		if gas != "CO2":
			raise RuntimeError(f"Unexpected gas in JRC LULUCF NGHGI source: {gas!r}.")
		iso3 = str(row.get("ISO3") or "").strip().upper()
		version = str(row.get("Version") or "").strip()
		submission = str(row.get("Source") or "").strip()
		category = str(row.get("Category") or "").strip().upper()
		year_text = str(row.get("Year") or "").strip()
		raw_value = str(row.get("CFluxes_yr") or "").strip()
		if version:
			source_versions.add(version)
		if submission:
			source_submissions.add(submission)
			source_counts[submission] += 1
		if category:
			source_categories.add(category)
		if not year_text.isdigit() or len(year_text) != 4:
			raise RuntimeError(f"Invalid JRC LULUCF year: {year_text!r}.")
		year = int(year_text)
		source_years.add(year)
		if not raw_value:
			continue
		try:
			number = float(raw_value)
		except ValueError as error:
			raise RuntimeError(f"Invalid JRC LULUCF value: {raw_value!r}.") from error
		if not math.isfinite(number):
			raise RuntimeError(f"Non-finite JRC LULUCF value: {raw_value!r}.")
		indicator = indicator_by_category.get(category)
		if indicator is None:
			continue
		if iso3 not in area_by_iso3:
			if iso3:
				ignored_iso3.add(iso3)
			continue
		area_id = area_by_iso3[iso3]
		indicator_id = str(indicator["id"])
		year_values = values[indicator_id][year]
		if area_id in year_values:
			raise RuntimeError(f"Duplicate JRC LULUCF value for {indicator_id} {year} {area_id}.")
		year_values[area_id] = common.normalize_number(raw_value)

	if not source_years:
		raise RuntimeError("JRC LULUCF CSV contained no annual rows.")
	source_start = min(source_years)
	source_latest = max(source_years)
	if source_start != int(config["expectedStartYear"]) or source_latest != int(config["expectedLatestYear"]):
		raise RuntimeError(
			f"JRC LULUCF source years changed: {source_start}-{source_latest}, "
			f"expected {config['expectedStartYear']}-{config['expectedLatestYear']}."
		)
	if source_versions != {str(config["sourceVersion"])}:
		raise RuntimeError(f"Unexpected JRC LULUCF source versions: {sorted(source_versions)}.")
	if source_categories != set(config["expectedCategories"]):
		raise RuntimeError(f"Unexpected JRC LULUCF categories: {sorted(source_categories)}.")
	if source_submissions != set(config["expectedSubmissions"]):
		raise RuntimeError(f"Unexpected JRC LULUCF submissions: {sorted(source_submissions)}.")
	return (
		values,
		ignored_iso3,
		source_start,
		source_latest,
		source_versions,
		source_submissions,
		source_categories,
		source_counts,
	)


def choose_default_year(
	indicator: dict[str, Any],
	available_years: list[int],
	year_values: dict[int, dict[str, int | float]],
) -> int:
	minimum = int(indicator["minAreasInDefaultYear"])
	eligible = [year for year in available_years if len(year_values[year]) >= minimum]
	if not eligible:
		raise RuntimeError(
			f"JRC LULUCF has no sufficiently complete default year for {indicator['id']}: "
			f"expected at least {minimum} areas."
		)
	return eligible[-1]


def build_payloads(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_id: dict[str, dict[int, dict[str, int | float]]],
	dataset_metadata: dict[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
	provider = config["provider"]
	result: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		year_values = values_by_id.get(indicator_id, {})
		available_years = sorted(year for year, mapped in year_values.items() if mapped)
		if not available_years:
			raise RuntimeError(f"JRC LULUCF returned no mapped values for {indicator_id}.")
		mapped_areas = {area_id for mapped in year_values.values() for area_id in mapped}
		if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
			raise RuntimeError(
				f"JRC LULUCF coverage too small for {indicator_id}: {len(mapped_areas)} areas, "
				f"expected at least {indicator['minAreasWithAnyValue']}."
			)
		for area_id in indicator["requiredAreas"]:
			if area_id not in mapped_areas:
				raise RuntimeError(f"JRC LULUCF {indicator_id} is missing required area {area_id}.")
		default_year = choose_default_year(indicator, available_years, year_values)
		latest_year = available_years[-1]
		latest_coverage = len(year_values[latest_year])
		default_coverage = len(year_values[default_year])

		indicator_metadata = {
			"id": indicator_id,
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		}
		source_metadata = {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourceUrl"],
			"downloadUrl": config["downloadUrl"],
			"doi": config["doi"],
			"doiUrl": config["doiUrl"],
			"zenodoRecordId": config["recordId"],
			"releaseVersion": config["releaseVersion"],
			"sourceVersion": config["sourceVersion"],
			"sourceFile": config["sourceFile"],
			"sourceChecksum": dataset_metadata["checksum"],
			"indicator": str(indicator["sourceCategory"]).upper(),
			"gas": "CO2",
			"sourceUnit": "Mt CO₂ yr⁻¹",
			"targetUnit": indicator["unit"]["label"],
			"normalization": {
				"valueMultiplier": 1,
				"note": "For CO₂, Mt CO₂ and Mt CO₂-equivalent are numerically identical.",
			},
		}
		payload = {
			"schema": "kartensammlung.statistics-indicator/v1",
			"indicator": indicator_metadata,
			"source": source_metadata,
			"availableYears": available_years,
			"defaultYear": default_year,
			"coverage": {
				"registryAreas": len(area_by_iso3),
				"areasWithAnyValue": len(mapped_areas),
				"latestYear": latest_year,
				"areasInLatestYear": latest_coverage,
				"areasInDefaultYear": default_coverage,
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
			f"{indicator_id}: mapped={len(mapped_areas)} years={available_years[0]}-{latest_year} "
			f"latestCoverage={latest_coverage} defaultYear={default_year} defaultCoverage={default_coverage}"
		)
		result.append((indicator, payload))
	return result


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("JRC LULUCF is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	print(f"Fetching JRC LULUCF Zenodo metadata from {config['metadataUrl']}")
	dataset_metadata = load_zenodo_metadata(config, args.timeout)
	print(f"Fetching JRC LULUCF data from {config['downloadUrl']}")
	(
		values_by_id,
		ignored_iso3,
		source_start,
		source_latest,
		source_versions,
		source_submissions,
		source_categories,
		source_counts,
	) = load_direct_values(config, area_by_iso3, args.timeout, int(dataset_metadata["bytes"]))
	dataset_metadata.update({
		"sourceStartYear": source_start,
		"sourceLatestYear": source_latest,
		"sourceVersions": sorted(source_versions),
		"sourceSubmissions": sorted(source_submissions),
		"sourceCategories": sorted(source_categories),
		"sourceSubmissionRows": dict(sorted(source_counts.items())),
	})
	indicator_payloads = build_payloads(config, area_by_iso3, values_by_id, dataset_metadata)
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
			"sourceIndicator": str(indicator["sourceCategory"]).upper(),
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
			"url": config["sourceUrl"],
			"downloadUrl": config["downloadUrl"],
			"doi": config["doi"],
			"doiUrl": config["doiUrl"],
			"zenodoRecordId": config["recordId"],
			"releaseVersion": config["releaseVersion"],
			"sourceVersion": config["sourceVersion"],
			"sourceFile": config["sourceFile"],
			"licenseId": dataset_metadata["licenseId"],
			"checksum": dataset_metadata["checksum"],
			"bytes": dataset_metadata["bytes"],
			"publicationDate": dataset_metadata["publicationDate"],
			"sourceStartYear": source_start,
			"sourceLatestYear": source_latest,
			"sourceVersions": sorted(source_versions),
			"sourceSubmissions": sorted(source_submissions),
			"sourceCategories": sorted(source_categories),
			"sourceSubmissionRows": dict(sorted(source_counts.items())),
		},
		"indicators": index_indicators,
		"notes": [
			"Direct annual CO₂ fluxes from the European Commission JRC LULUCF Data Hub NGHGI database.",
			"Version 3.1.1 is the current 2025 NGHGI release; the NGHGI CSV itself is unchanged from version 3.1.",
			"NGHGI values are sourced from national greenhouse-gas inventories submitted to the UNFCCC and harmonized into JRC LULUCF classes.",
			"Source values are Mt CO₂ yr⁻¹. For CO₂ only, these values are numerically identical to the retained Mt CO₂e target unit.",
			"No World Bank WDI fallback is mixed into this provider.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Ignored JRC LULUCF ISO3 codes: {sorted(ignored_iso3) or '(none)'}")
	print(f"Built JRC LULUCF snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
