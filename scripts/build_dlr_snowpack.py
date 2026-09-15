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
	parser = argparse.ArgumentParser(description="Build normalized DLR Global SnowPack country statistics.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.dlr-snowpack-statistics/v1":
		raise ValueError("Invalid DLR SnowPack config.")
	provider = payload.get("provider")
	indicator = payload.get("indicator")
	if not isinstance(provider, dict) or not isinstance(indicator, dict):
		raise ValueError("DLR SnowPack config requires provider and indicator metadata.")
	for key in ("id", "name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"Provider metadata is missing {key}.")
	for key in ("id", "slug", "sourceVariable", "title", "description"):
		if not str(indicator.get(key, "")).strip():
			raise ValueError(f"Indicator metadata is missing {key}.")
	validate_classification(str(indicator["id"]), indicator.get("classification"))
	unit = indicator.get("unit")
	if not isinstance(unit, dict) or not unit.get("id") or not unit.get("label"):
		raise ValueError("Indicator unit metadata is invalid.")
	return payload


def load_year_payloads(input_dir: Path) -> dict[int, dict[str, Any]]:
	result: dict[int, dict[str, Any]] = {}
	for path in sorted(input_dir.rglob("*.json")):
		payload = read_json_path(path)
		if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.dlr-snowpack-year/v1":
			continue
		year = payload.get("year")
		if not isinstance(year, int):
			raise ValueError(f"Invalid SnowPack year in {path}.")
		if year in result:
			raise RuntimeError(f"Duplicate SnowPack extraction for {year}.")
		result[year] = payload
	if not result:
		raise RuntimeError(f"No SnowPack yearly extraction found in {input_dir}.")
	return result


def validate_series(
	config: dict[str, Any],
	by_year: dict[int, dict[str, Any]],
	area_by_iso3: dict[str, str],
	registry_payload: dict[str, Any],
) -> tuple[list[int], str, list[dict[str, Any]]]:
	start = int(config["startYear"])
	latest = max(by_year)
	if latest < int(config["minimumLatestYear"]):
		raise RuntimeError(f"Latest SnowPack year {latest} is older than required minimum.")
	years = list(range(start, latest + 1))
	if sorted(by_year) != years:
		raise RuntimeError(f"SnowPack year series is not contiguous: {sorted(by_year)}")

	registry_source = registry_payload.get("source")
	if not isinstance(registry_source, dict) or not registry_source.get("release"):
		raise RuntimeError("Country registry is missing Overture release metadata.")
	overture_release = str(registry_source["release"])
	expected_iso3 = set(area_by_iso3)
	base = str(config["downloadBase"]).rstrip("/")
	source_files: list[dict[str, Any]] = []

	for year in years:
		payload = by_year[year]
		if payload.get("countryCount") != len(area_by_iso3):
			raise RuntimeError(f"{year}: country count mismatch.")
		geometry = payload.get("geometry")
		if not isinstance(geometry, dict) or geometry.get("overtureRelease") != overture_release:
			raise RuntimeError(f"{year}: Overture release mismatch.")
		source = payload.get("source")
		if not isinstance(source, dict):
			raise RuntimeError(f"{year}: source metadata missing.")
		expected_url = f"{base}/{year}/{year}_SCD_full_wgs84.tif"
		if source.get("url") != expected_url:
			raise RuntimeError(f"{year}: unexpected source URL.")
		sha256 = str(source.get("sha256", "")).lower()
		if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
			raise RuntimeError(f"{year}: invalid source SHA256.")
		bytes_value = source.get("bytes")
		if not isinstance(bytes_value, int) or bytes_value <= 0:
			raise RuntimeError(f"{year}: invalid source byte size.")
		values = payload.get("values")
		if not isinstance(values, dict) or set(values) != expected_iso3:
			raise RuntimeError(f"{year}: ISO3 set differs from registry.")
		for iso3, entry in values.items():
			if not isinstance(entry, dict):
				raise RuntimeError(f"{year} {iso3}: invalid value entry.")
			for key in ("weightedMeanDays", "minimumDays", "maximumDays", "coveredCellEquivalent"):
				value = entry.get(key)
				if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
					raise RuntimeError(f"{year} {iso3}: invalid {key}.")
			if not 0 <= float(entry["weightedMeanDays"]) <= 366.001:
				raise RuntimeError(f"{year} {iso3}: weighted mean outside 0..366.")
			if not 0 <= float(entry["minimumDays"]) <= 366.001:
				raise RuntimeError(f"{year} {iso3}: minimum outside 0..366.")
			if not 0 <= float(entry["maximumDays"]) <= 366.001:
				raise RuntimeError(f"{year} {iso3}: maximum outside 0..366.")
			if float(entry["coveredCellEquivalent"]) <= 0:
				raise RuntimeError(f"{year} {iso3}: no raster coverage.")
		source_files.append({
			"year": year,
			"url": expected_url,
			"bytes": bytes_value,
			"sha256": sha256,
		})
	return years, overture_release, source_files


def build_payload(
	config: dict[str, Any],
	by_year: dict[int, dict[str, Any]],
	years: list[int],
	area_by_iso3: dict[str, str],
	overture_release: str,
	source_files: list[dict[str, Any]],
) -> dict[str, Any]:
	provider = config["provider"]
	indicator = config["indicator"]
	values: dict[str, dict[str, float]] = {}
	for year in years:
		mapped = {
			area_by_iso3[iso3]: round(float(entry["weightedMeanDays"]), 6)
			for iso3, entry in by_year[year]["values"].items()
		}
		values[str(year)] = dict(sorted(mapped.items()))

	for year in years:
		for area_id in config["requiredAreas"]:
			if area_id not in values[str(year)]:
				raise RuntimeError(f"{year}: required area {area_id} missing.")

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
				"southernHemisphere": "1 March of the labelled year through 28/29 February of the following year",
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
	catalog = validate_provider_catalog(read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = load_registry(args.registry, 60)
	if len(area_by_iso3) != 250:
		raise RuntimeError(f"SnowPack requires 250 registry countries, found {len(area_by_iso3)}.")
	by_year = load_year_payloads(args.input_dir)
	years, overture_release, source_files = validate_series(
		config,
		by_year,
		area_by_iso3,
		registry_payload,
	)
	payload = build_payload(
		config,
		by_year,
		years,
		area_by_iso3,
		overture_release,
		source_files,
	)

	hasher = hashlib.sha256()
	hasher.update(str(config["indicator"]["id"]).encode("utf-8"))
	hasher.update(b"\0")
	hasher.update(canonical_bytes(payload))
	snapshot = hasher.hexdigest()[:16]

	provider_dir = args.output_dir / provider["id"]
	filename = f"{config['indicator']['slug']}.json"
	write_json(provider_dir / "releases" / snapshot / filename, payload)

	indicator_index = {
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
		"retrievedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
		"indicators": [indicator_index],
	}
	write_json(provider_dir / "index.json", provider_index)
	write_json(args.output_dir / "index.json", build_global_index(catalog))

	print(f"Built DLR Global SnowPack snapshot {snapshot}")
	print(f"Years: {years[0]}-{years[-1]} ({len(years)})")
	print(f"Countries per year: {len(area_by_iso3)}")
	print(f"Overture release: {overture_release}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
