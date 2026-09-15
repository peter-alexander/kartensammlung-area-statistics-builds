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
DEFAULT_CONFIG = ROOT / "config" / "global-wind-atlas-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_INPUT_DIR = ROOT / "raw" / "global-wind-atlas"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = ROOT / "raw" / "global-wind-atlas-geometry" / "area-registry-countries.json"
EXPECTED_COUNTRIES = 250
EXPECTED_AREAS = 246


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized Global Wind Atlas 4.0 country statistics.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
	return parser.parse_args()


def validate_iso3_list(name: str, value: Any) -> list[str]:
	if not isinstance(value, list) or any(
		not isinstance(item, str) or len(item) != 3 or item.upper() != item
		for item in value
	):
		raise ValueError(f"{name} must be a list of uppercase ISO3 codes.")
	if value != sorted(set(value)):
		raise ValueError(f"{name} must be sorted and unique.")
	return value


def validate_sha256(name: str, value: Any) -> str:
	normalized = str(value or "").lower()
	if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
		raise ValueError(f"{name} must be a lowercase SHA-256 digest.")
	return normalized


def assert_close_sequence(name: str, actual: Any, expected: Any, tolerance: float = 1e-9) -> None:
	if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
		raise RuntimeError(f"{name} length changed: {actual} != {expected}")
	for actual_value, expected_value in zip(actual, expected, strict=True):
		if abs(float(actual_value) - float(expected_value)) > tolerance:
			raise RuntimeError(f"{name} changed: {actual} != {expected}")


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.global-wind-atlas-statistics/v1":
		raise ValueError("Invalid Global Wind Atlas config.")
	if payload.get("version") != "4.0":
		raise ValueError("Global Wind Atlas version must remain 4.0.")
	if payload.get("snapshotYear") != 2025 or payload.get("releaseMonth") != "June 2025":
		raise ValueError("Global Wind Atlas 4.0 release metadata must remain June 2025 / snapshotYear 2025.")
	if payload.get("referencePeriod") != [2008, 2017]:
		raise ValueError("Global Wind Atlas 4.0 reference period must remain 2008-2017.")
	if payload.get("heightMeters") != 100:
		raise ValueError("Global Wind Atlas production height must remain 100 m.")
	if not str(payload.get("auditOvertureRelease", "")).strip():
		raise ValueError("Global Wind Atlas config requires auditOvertureRelease.")
	for key in ("sourcePage", "gisPage", "methodUrl", "releaseNotesUrl", "termsUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"Global Wind Atlas {key} must use HTTPS.")
	if payload.get("expectedWidth") != 144000 or payload.get("expectedHeight") != 57600:
		raise ValueError("Global Wind Atlas audited raster size changed.")
	if abs(float(payload.get("expectedPixelSizeDegrees", 0)) - 0.0025) > 1e-12:
		raise ValueError("Global Wind Atlas audited pixel size changed.")
	expected_transform = payload.get("expectedTransform")
	expected_bounds = payload.get("expectedBounds")
	if not isinstance(expected_transform, list) or len(expected_transform) != 6:
		raise ValueError("Global Wind Atlas expectedTransform must contain six values.")
	if not isinstance(expected_bounds, list) or len(expected_bounds) != 4:
		raise ValueError("Global Wind Atlas expectedBounds must contain four values.")
	expected_missing = validate_iso3_list("expectedMissingIso3", payload.get("expectedMissingIso3"))
	if expected_missing != ["ATA", "BVT", "HMD", "SGS"]:
		raise ValueError("Global Wind Atlas audited missing-country contract changed.")
	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "global-wind-atlas":
		raise ValueError("Global Wind Atlas provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"Global Wind Atlas provider metadata is missing {key}.")
	if provider.get("license") != "CC BY 4.0":
		raise ValueError("Global Wind Atlas license must remain CC BY 4.0.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 2:
		raise ValueError("Global Wind Atlas production config requires exactly two indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("Global Wind Atlas indicator must be an object.")
		for key in ("id", "slug", "sourceVariable", "sourceUrl", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"Global Wind Atlas indicator is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		if indicator_id in ids or slug in slugs:
			raise ValueError(f"Duplicate Global Wind Atlas indicator id/slug: {indicator_id} / {slug}")
		ids.add(indicator_id)
		slugs.add(slug)
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"Indicator {indicator_id} has invalid unit metadata.")
		validate_classification(indicator_id, indicator.get("classification"))
		value_range = indicator.get("valueRange")
		if (
			not isinstance(value_range, list)
			or len(value_range) != 2
			or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in value_range)
			or not math.isfinite(float(value_range[0]))
			or not math.isfinite(float(value_range[1]))
			or float(value_range[0]) >= float(value_range[1])
		):
			raise ValueError(f"Indicator {indicator_id} has invalid valueRange.")
		if indicator.get("expectedAreas") != EXPECTED_AREAS:
			raise ValueError(f"Indicator {indicator_id} expectedAreas must remain {EXPECTED_AREAS}.")
		expected_bytes = indicator.get("expectedSourceBytes")
		if not isinstance(expected_bytes, int) or expected_bytes <= 1_000_000_000:
			raise ValueError(f"Indicator {indicator_id} has invalid expectedSourceBytes.")
		validate_sha256(f"{indicator_id}.expectedSourceSha256", indicator.get("expectedSourceSha256"))
		audit_values = indicator.get("auditValues")
		if not isinstance(audit_values, dict) or not audit_values:
			raise ValueError(f"Indicator {indicator_id} requires auditValues.")
		for area_id, value in audit_values.items():
			if not str(area_id).startswith("country:"):
				raise ValueError(f"Indicator {indicator_id} has invalid audit area {area_id!r}.")
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
				raise ValueError(f"Indicator {indicator_id} has invalid audit value for {area_id}.")
	return payload


def load_extractions(config: dict[str, Any], input_dir: Path) -> dict[str, dict[str, Any]]:
	extractions: dict[str, dict[str, Any]] = {}
	for indicator in config["indicators"]:
		path = input_dir / f"{indicator['slug']}.json"
		if not path.exists():
			raise RuntimeError(f"Missing Global Wind Atlas extraction: {path}")
		payload = read_json_path(path)
		if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.global-wind-atlas-extraction/v1":
			raise ValueError(f"Invalid Global Wind Atlas extraction: {path}")
		if payload.get("indicatorId") != indicator["id"]:
			raise RuntimeError(f"Extraction indicator mismatch in {path}.")
		extractions[str(indicator["id"])] = payload
	return extractions


def validate_extraction(
	config: dict[str, Any],
	indicator: dict[str, Any],
	payload: dict[str, Any],
	registry_iso3: set[str],
	overture_release: str,
) -> dict[str, float]:
	if payload.get("sourceVariable") != indicator["sourceVariable"]:
		raise RuntimeError(f"{indicator['id']}: source variable mismatch.")
	if payload.get("heightMeters") != config["heightMeters"]:
		raise RuntimeError(f"{indicator['id']}: source height mismatch.")
	if payload.get("countryCount") != EXPECTED_COUNTRIES or payload.get("areasWithValue") != EXPECTED_AREAS:
		raise RuntimeError(f"{indicator['id']}: country coverage mismatch.")
	if payload.get("missingIso3") != config["expectedMissingIso3"]:
		raise RuntimeError(f"{indicator['id']}: missing-country contract changed.")
	geometry = payload.get("geometry")
	if not isinstance(geometry, dict) or geometry.get("overtureRelease") != overture_release:
		raise RuntimeError(f"{indicator['id']}: Overture release mismatch.")
	source = payload.get("source")
	if not isinstance(source, dict) or source.get("url") != indicator["sourceUrl"]:
		raise RuntimeError(f"{indicator['id']}: source URL mismatch.")
	if source.get("width") != config["expectedWidth"] or source.get("height") != config["expectedHeight"]:
		raise RuntimeError(f"{indicator['id']}: source grid size mismatch.")
	if source.get("dataType") != "float32" or source.get("declaredNoData") != "NaN":
		raise RuntimeError(f"{indicator['id']}: source raster contract changed.")
	assert_close_sequence(f"{indicator['id']} source transform", source.get("transform"), config["expectedTransform"])
	assert_close_sequence(f"{indicator['id']} source bounds", source.get("bounds"), config["expectedBounds"])
	sha256 = validate_sha256(f"{indicator['id']} source.sha256", source.get("sha256"))
	if sha256 != indicator["expectedSourceSha256"]:
		raise RuntimeError(
			f"{indicator['id']}: source SHA-256 changed: {sha256} != {indicator['expectedSourceSha256']}"
		)
	bytes_value = source.get("bytes")
	if bytes_value != indicator["expectedSourceBytes"]:
		raise RuntimeError(
			f"{indicator['id']}: source byte size changed: {bytes_value} != {indicator['expectedSourceBytes']}"
		)
	values = payload.get("values")
	if not isinstance(values, dict) or set(values) != registry_iso3:
		raise RuntimeError(f"{indicator['id']}: extraction ISO3 set differs from registry.")

	mapped: dict[str, float] = {}
	minimum_allowed = float(indicator["valueRange"][0])
	maximum_allowed = float(indicator["valueRange"][1])
	for iso3 in sorted(registry_iso3):
		entry = values[iso3]
		if iso3 in config["expectedMissingIso3"]:
			if entry is not None:
				raise RuntimeError(f"{indicator['id']} {iso3}: expected missing value.")
			continue
		if not isinstance(entry, dict):
			raise RuntimeError(f"{indicator['id']} {iso3}: invalid extraction value.")
		mean = entry.get("weightedMean")
		count = entry.get("coveredCellEquivalent")
		if isinstance(mean, bool) or not isinstance(mean, (int, float)) or not math.isfinite(float(mean)):
			raise RuntimeError(f"{indicator['id']} {iso3}: invalid weighted mean.")
		if not minimum_allowed <= float(mean) <= maximum_allowed:
			raise RuntimeError(f"{indicator['id']} {iso3}: weighted mean outside configured range.")
		if isinstance(count, bool) or not isinstance(count, (int, float)) or float(count) <= 0:
			raise RuntimeError(f"{indicator['id']} {iso3}: invalid coverage count.")
		mapped[iso3] = float(mean)
	if len(mapped) != EXPECTED_AREAS:
		raise RuntimeError(f"{indicator['id']}: expected {EXPECTED_AREAS} values, found {len(mapped)}.")
	return mapped


def source_file_metadata(indicator: dict[str, Any], extraction: dict[str, Any]) -> dict[str, Any]:
	source = extraction["source"]
	return {
		"indicatorId": indicator["id"],
		"variable": indicator["sourceVariable"],
		"heightMeters": extraction["heightMeters"],
		"url": source["url"],
		"bytes": source["bytes"],
		"sha256": source["sha256"],
	}


def build_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	values_by_iso3: dict[str, float],
	area_by_iso3: dict[str, str],
	overture_release: str,
	extraction: dict[str, Any],
) -> dict[str, Any]:
	provider = config["provider"]
	snapshot_year = int(config["snapshotYear"])
	values = {
		area_by_iso3[iso3]: round(value, 6)
		for iso3, value in values_by_iso3.items()
	}
	if overture_release == config["auditOvertureRelease"]:
		for area_id, expected in indicator["auditValues"].items():
			actual = values.get(area_id)
			if actual is None or abs(float(actual) - float(expected)) > 1e-6:
				raise RuntimeError(
					f"{indicator['id']} audit value changed for {area_id}: {actual} != {expected}."
				)
	return {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "snapshot",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		},
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"datasetVersion": config["version"],
			"indicator": indicator["sourceVariable"],
			"heightMeters": config["heightMeters"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourcePage"],
			"gisUrl": config["gisPage"],
			"releaseMonth": config["releaseMonth"],
			"snapshotYear": snapshot_year,
			"referencePeriod": config["referencePeriod"],
			"referencePeriodDescription": config["referencePeriodDescription"],
			"sourceFile": source_file_metadata(indicator, extraction),
			"aggregation": {
				"sourceGrid": "native Global Wind Atlas 4.0 WGS84 grid, 144000 × 57600 cells",
				"sourceResolution": "0.0025 degree (~250 m nominal)",
				"countryGeometry": "Overture Maps land polygons (is_land = TRUE)",
				"overtureRelease": overture_release,
				"coverage": "exact fractional source-cell coverage",
				"areaWeighting": "WGS84 geodesic source-cell area by latitude row",
				"resampling": "none",
				"sourceOverviews": "not used for statistic",
				"expectedMissingIso3": config["expectedMissingIso3"],
			},
		},
		"availableYears": [snapshot_year],
		"defaultYear": snapshot_year,
		"coverage": {
			"registryAreas": EXPECTED_COUNTRIES,
			"areasWithAnyValue": len(values),
			"latestYear": snapshot_year,
			"areasInLatestYear": len(values),
			"areasInDefaultYear": len(values),
			"observations": len(values),
		},
		"values": {
			str(snapshot_year): dict(sorted(values.items())),
		},
	}


def main() -> int:
	args = parse_args()
	config = validate_config(read_json_path(args.config))
	catalog = validate_provider_catalog(read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in catalog["providers"]):
		raise RuntimeError("Global Wind Atlas is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = load_registry(args.registry, 60)
	if len(area_by_iso3) != EXPECTED_COUNTRIES:
		raise RuntimeError(f"Global Wind Atlas requires 250 registry countries, found {len(area_by_iso3)}.")
	registry_source = registry_payload.get("source")
	if not isinstance(registry_source, dict) or not str(registry_source.get("release", "")).strip():
		raise RuntimeError("Country registry is missing Overture release metadata.")
	overture_release = str(registry_source["release"])
	extractions = load_extractions(config, args.input_dir)

	payloads: dict[str, dict[str, Any]] = {}
	source_files: list[dict[str, Any]] = []
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		extraction = extractions[indicator_id]
		values_by_iso3 = validate_extraction(
			config,
			indicator,
			extraction,
			set(area_by_iso3),
			overture_release,
		)
		payloads[indicator_id] = build_payload(
			config,
			indicator,
			values_by_iso3,
			area_by_iso3,
			overture_release,
			extraction,
		)
		source_files.append(source_file_metadata(indicator, extraction))

	hasher = hashlib.sha256()
	for indicator_id in sorted(payloads):
		hasher.update(indicator_id.encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(canonical_bytes(payloads[indicator_id]))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	indicator_index: list[dict[str, Any]] = []
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		payload = payloads[indicator_id]
		filename = f"{indicator['slug']}.json"
		write_json(release_dir / filename, payload)
		indicator_index.append({
			"id": indicator_id,
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "snapshot",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"sourceVariable": indicator["sourceVariable"],
			"heightMeters": config["heightMeters"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		})

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
			"version": config["version"],
			"releaseMonth": config["releaseMonth"],
			"snapshotYear": config["snapshotYear"],
			"referencePeriod": config["referencePeriod"],
			"heightMeters": config["heightMeters"],
			"overtureRelease": overture_release,
			"auditOvertureRelease": config["auditOvertureRelease"],
			"sourceFileCount": len(source_files),
			"sourceFiles": source_files,
			"expectedMissingIso3": config["expectedMissingIso3"],
		},
		"indicators": indicator_index,
	}
	write_json(provider_dir / "index.json", provider_index)
	write_json(args.output_dir / "index.json", build_global_index(catalog))

	print(f"Built Global Wind Atlas snapshot {snapshot}")
	print(f"Indicators: {len(indicator_index)}")
	print(f"Countries with values per indicator: {EXPECTED_AREAS}/{EXPECTED_COUNTRIES}")
	print(f"Overture release: {overture_release}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
