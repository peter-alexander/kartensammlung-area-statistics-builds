#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_world_bank import (
	build_global_index,
	canonical_bytes,
	load_registry,
	read_json_path,
	validate_classification,
	validate_provider_catalog,
	write_json,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "dlr-snowpack-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_INPUT_DIR = ROOT / "raw" / "dlr-snowpack"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = ROOT / "raw" / "dlr-snowpack-geometry" / "area-registry-countries.json"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build normalized country statistics from DLR Global SnowPack yearly SCD extractions."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
	return parser.parse_args()


def utc_now() -> datetime:
	return datetime.now(timezone.utc)


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.dlr-snowpack-statistics/v1":
		raise ValueError("Invalid DLR SnowPack statistics config.")
	provider = payload.get("provider")
	indicator = payload.get("indicator")
	if not isinstance(provider, dict):
		raise ValueError("DLR SnowPack provider metadata is required.")
	for key in ("id", "name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"DLR SnowPack provider metadata is missing {key}.")
	if not isinstance(indicator, dict):
		raise ValueError("DLR SnowPack indicator metadata is required.")
	for key in ("id", "slug", "sourceVariable", "title", "description"):
		if not str(indicator.get(key, "")).strip():
			raise ValueError(f"DLR SnowPack indicator metadata is missing {key}.")
	unit = indicator.get("unit")
	if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
		raise ValueError("DLR SnowPack indicator has invalid unit metadata.")
	validate_classification(str(indicator["id"]), indicator.get("classification"))
	for key in ("sourcePage", "datasetOverview", "downloadBase"):
		value = str(payload.get(key, "")).strip()
		if not value.startswith("https://"):
			raise ValueError(f"DLR SnowPack {key} must be an HTTPS URL.")
	for key in ("startYear", "minimumLatestYear", "productVersion"):
		if not isinstance(payload.get(key), int):
			raise ValueError(f"DLR SnowPack {key} must be an integer.")
	required = payload.get("requiredAreas")
	if not isinstance(required, list) or not required:
		raise ValueError("DLR SnowPack config requires requiredAreas.")
	return payload


def load_year_payloads(input_dir: Path) -> dict[int, dict[str, Any]]:
	by_year: dict[int, dict[str, Any]] = {}
	for path in sorted(input_dir.rglob("*.json")):
		payload = read_json_path(path)
		if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.dlr-snowpack-year/v1":
			continue
		year = payload.get("year")
		if not isinstance(year, int):
			raise ValueError(f"DLR SnowPack extraction has invalid year: {path}")
		if year in by_year:
			raise RuntimeError(f"Duplicate DLR SnowPack extraction for {year}: {path}")
		by_year[year] = payload
	if not by_year:
		raise RuntimeError(f"No DLR SnowPack yearly extraction JSON found in {input_dir}.")
	return by_year


def validate_year_series(
	config: dict[str, Any],
	by_year: dict[int, dict[str, Any]],
	area_by_iso3: dict[str, str],
	registry_payload: dict[str, Any],
) -> tuple[list[int], str, list[dict[str, Any]]]:
	start_year = int(config["startYear"])
	latest_year = max(by_year)
	minimum_latest_year = int(config["minimumLatestYear"])
	if latest_year < minimum_latest_year:
		raise RuntimeError(
			f"DLR SnowPack latest year is too old: {latest_year}; expected at least {minimum_latest_year}."
		)
	expected_years = list(range(start_year, latest_year + 1))
	actual_years = sorted(by_year)
	if actual_years != expected_years:
		raise RuntimeError(f"DLR SnowPack year coverage is not contiguous: {actual_years}")

	registry_source = registry_payload.get("source")
	if not isinstance(registry_source, dict):
		raise RuntimeError("Country registry is missing source metadata.")
	overture_release = str(registry_source.get("release", "")).strip()
	if not overture_release:
		raise RuntimeError("Country registry is missing its Overture release.")

	expected_iso3 = set(area_by_iso3)
	expected_download_base = str(config["downloadBase"]).rstrip("/")
	source_files: list[dict[str, Any]] = []
	for year in expected_years:
		payload = by_year[year]
		if payload.get("countryCount") != len(area_by_iso3):
			raise RuntimeError(
				f"{year}: expected {len(area_by_iso3)} country values, got {payload.get('countryCount')}."
			)
		geometry = payload.get("geometry")
		if not isinstance(geometry, dict) or geometry.get("overtureRelease") != overture_release:
			raise RuntimeError(
				f"{year}: extraction geometry release does not match registry release {overture_release}."
			)
		source = payload.get("source")
		if not isinstance(source, dict):
			raise RuntimeError(f"{year}: source metadata is missing.")
		expected_url = f"{expected_download_base}/{year}/{year}_SCD_full_wgs84.tif"
		if source.get("url") != expected_url:
			raise RuntimeError(f"{year}: unexpected source URL: {source.get('url')!r}")
		sha256 = str(source.get("sha256", "")).strip().lower()
		if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
			raise RuntimeError(f"{year}: invalid source SHA256: {sha256!r}")
		bytes_value = source.get("bytes")
		if not isinstance(bytes_value, int) or bytes_value <= 0:
			raise RuntimeError(f"{year}: invalid source byte size: {bytes_value!r}")
		values = payload.get("values")
		if not isinstance(values, dict) or set(values) != expected_iso3:
			raise RuntimeError(f"{year}: country ISO3 set differs from registry.")
		for iso3, entry in values.items():
			if not isinstance(entry, dict):
				raise RuntimeError(f"{year} {iso3}: invalid extraction entry.")
			for key in ("weightedMeanDays", "minimumDays", "maximumDays", "coveredCellEquivalent"):
				value = entry.get(key)
				if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
					raise RuntimeError(f"{year} {iso3}: invalid {key}: {value!r}")
			if not 0.0 <= float(entry["weightedMeanDays"]) <= 366.001:
				raise RuntimeError(f"{year} {iso3}: weighted mean outside 0..366.")
			if not 0.0 <= float(entry["minimumDays"]) <= 366.001:
				raise RuntimeError(f"{year} {iso3}: minimum outside 0..366.")
			if not 0.0 <= float(entry["maximumDays"]) <= 366.001:
				raise RuntimeError(f"{year} {iso3}: maximum outside 0..366.")
			if float(entry["coveredCellEquivalent"]) <= 0:
				raise RuntimeError(f"{year} {iso3}: non-positive raster coverage.")
		source_files.append({
			"year": year,
			"url": expected_url,
			"bytes": bytes_value,
			"sha256": sha256,
		})
	return expected_years, overture_release, source_files


def build_indicator_payload(
	config: dict[str, Any],
	by_year: dict[int, dict[str, Any]],
	years: list[int],
	area_by_iso3: dict[str, str],
	source_files: list[dict[str, Any]],
	overture_release: str,
) -> dict[str, Any]:
	provider = config["provider"]
	indicator = config["indicator"]
	values: dict[str, dict[str, float]] = {}
	for year in years:
		year_values: dict[str, float] = {}
		for iso3, entry in by_year[year]["values"].items():
			area_id = area_by_iso3[iso3]
			year_values[area_id] = round(float(entry["weightedMeanDays"]), 6)
		values[str(year)] = {area_id: year_values[area_id] for area_id in sorted(year_values)}

	for area_id in config["requiredAreas"]:
		for year in years:
			if area_id not in values[str(year)]:
				raise RuntimeError(f"Required area {area_id} is missing in {year}.")

	indicator_metadata = {
		"id": indicator["id"],
		"title": indicator["title"],
		"description": indicator["description"],
		"areaLevel": "country",
		"frequency": "annual",
		"unit": indicator["unit"],
		"classification": indicator["classification"],
	}
	return {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": indicator_metadata,
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"datasetVersion": int(config["productVersion"]),
			"indicator": indicator["sourceVariable"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourcePage"],
			"datasetOverview": config["datasetOverview"],
			"sourceFiles": source_files,
			"aggregation": {
				"sourceGrid": "native DLR Global SnowPack WGS84 grid, 86400 × 43200 cells",
				"sourceResolution": "1/240 degree (~500 m nominal)",
				"countryGeometry": "Overture Maps land polygons",
				"overtureRelease": overture_release,
				"coverage": "exact fractional source-cell coverage",
				"areaWeighting": "WGS84 geodesic source-cell area by latitude row",
				"sourceOverviews": "not used",
				"zeroPolicy": "0 is retained as a valid snow-cover duration value",
			},
			"periodDefinition": {
				"type": "hemisphere-dependent snow year",
				"northernHemisphere": "1 September of the previous year through 31 August of the labelled year",
				"southernHemisphere": "1 March of the previous year through 28/29 February of the labelled year",
				"note": "The DLR yearly SCD product is not a calendar-year statistic.",
			},
		},
		"availableYears": years,
		"defaultYear": years[-1],
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(area_by_iso3),
			"latestYear": years[-1],
			"areasInLatestYear": len(values[str(years[-1])]),
			"areasInDefaultYear": len(values[str(years[-1])]),
		},
		"values": values,
	}


def main() -> int:
	args = parse_args()
	config = validate_config(read_json_path(args.config))
	provider_catalog = validate_provider_catalog(read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = load_registry(args.registry, 60)
	if len(area_by_iso3) != 250:
		raise RuntimeError(f"DLR SnowPack requires exactly 250 registry countries, found {len(area_by_iso3)}.")
	by_year = load_year_payloads(args.input_dir)
	years, overture_release, source_files = validate_year_series(
		config,
		by_year,
		area_by_iso3,
		registry_payload,
	)
	payload = build_indicator_payload(
		config,
		by_year,
		years,
		area_by_iso3,
		source_files,
		overture_release,
	)

	hasher = hashlib.sha256()
	hasher.update(str(config["indicator"]["id"]).encode("utf-8"))
	hasher.update(b"\0")
	hasher.update(canonical_bytes(payload))
	hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	output_dir = args.output_dir
	provider_dir = output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	filename = f"{config['indicator']['slug']}.json"
	write_json(release_dir / filename, payload)

	index_indicator = {
		"id": config["indicator"]["id"],
		"title": config["indicator"]["title"],
		"description": config["indicator"]["description"],
		"areaLevel": "country",
		"frequency": "annual",
		"unit": config["indicator"]["unit"],
		"classification": config["indicator"]["classification"],
		"sourceVariable": config["indicator"]["sourceVariable"],
		"path": f"releases/{snapshot}/{filename}",
		"availableYears": years,
		"defaultYear": years[-1],
		"coverage": payload["coverage"],
	}
	registry_source = registry_payload.get("source") if isinstance(registry_payload.get("source"), dict) else {}
	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": utc_now().isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": {
			"schema": registry_payload.get("schema"),
			"generatedAt": registry_payload.get("generatedAt"),
			"areaCount": len(area_by_iso3),
			"source": registry_source,
		},
		"dataset": {
			"productVersion": int(config["productVersion"]),
			"sourceYearRange": [years[0], years[-1]],
			"sourceFileCount": len(source_files),
			"overtureRelease": overture_release,
			"sourceFiles": source_files,
		},
		"indicators": [index_indicator],
	}
	write_json(provider_dir / "index.json", provider_index)
	write_json(output_dir / "index.json", build_global_index(provider_catalog))

	print(f"Built DLR Global SnowPack snapshot {snapshot}")
	print(f"Years: {years[0]}-{years[-1]} ({len(years)})")
	print(f"Countries per year: {len(area_by_iso3)}")
	print(f"Overture release: {overture_release}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
