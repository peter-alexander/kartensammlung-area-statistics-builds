#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from exactextract import exact_extract
from pyproj import Geod
from rasterio.transform import Affine

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "global-wind-atlas-indicators.json"
EXPECTED_COUNTRIES = 250
EXPECTED_AREAS = 246


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Aggregate one Global Wind Atlas 4.0 global raster to country land areas."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--indicator-id", required=True)
	parser.add_argument("--source", type=Path, required=True)
	parser.add_argument("--source-url", required=True)
	parser.add_argument("--country-geojsonseq", type=Path, required=True)
	parser.add_argument("--registry", type=Path, required=True)
	parser.add_argument("--output", type=Path, required=True)
	parser.add_argument("--work-dir", type=Path, required=True)
	return parser.parse_args()


def read_json(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as handle:
		for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def run_command(command: list[str], timeout: int = 900) -> None:
	completed = subprocess.run(
		command,
		check=False,
		capture_output=True,
		text=True,
		timeout=timeout,
	)
	if completed.returncode != 0:
		raise RuntimeError(
			f"Command failed ({completed.returncode}): {' '.join(command)}\n"
			f"stdout:\n{completed.stdout[-8000:]}\n"
			f"stderr:\n{completed.stderr[-8000:]}"
		)


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


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.global-wind-atlas-statistics/v1":
		raise ValueError("Invalid Global Wind Atlas config.")
	if payload.get("version") != "4.0":
		raise ValueError("Global Wind Atlas version must remain 4.0.")
	if payload.get("heightMeters") != 100:
		raise ValueError("Global Wind Atlas production height must remain 100 m.")
	if payload.get("snapshotYear") != 2025:
		raise ValueError("Global Wind Atlas 4.0 snapshot year must remain 2025.")
	if payload.get("referencePeriod") != [2008, 2017]:
		raise ValueError("Global Wind Atlas 4.0 reference period must remain 2008-2017.")
	expected_missing = validate_iso3_list("expectedMissingIso3", payload.get("expectedMissingIso3"))
	if expected_missing != ["ATA", "BVT", "HMD", "SGS"]:
		raise ValueError("Global Wind Atlas audited missing-country contract changed.")
	for key in (
		"expectedWidth",
		"expectedHeight",
		"expectedPixelSizeDegrees",
		"expectedTransform",
		"expectedBounds",
	):
		if key not in payload:
			raise ValueError(f"Global Wind Atlas config is missing {key}.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 2:
		raise ValueError("Global Wind Atlas production config requires exactly two indicators.")
	ids: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("Global Wind Atlas indicator must be an object.")
		for key in ("id", "slug", "sourceVariable", "sourceUrl", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"Global Wind Atlas indicator is missing {key}.")
		indicator_id = str(indicator["id"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate Global Wind Atlas indicator: {indicator_id}")
		ids.add(indicator_id)
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
	return payload


def select_indicator(config: dict[str, Any], indicator_id: str) -> dict[str, Any]:
	matches = [item for item in config["indicators"] if item["id"] == indicator_id]
	if len(matches) != 1:
		raise ValueError(f"Unknown Global Wind Atlas indicator: {indicator_id}")
	return matches[0]


def load_registry(path: Path) -> tuple[set[str], str]:
	payload = read_json(path)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.area-registry/v1":
		raise ValueError("Invalid country area registry.")
	areas = payload.get("areas")
	if not isinstance(areas, list) or len(areas) != EXPECTED_COUNTRIES:
		raise ValueError(f"Expected {EXPECTED_COUNTRIES} registry areas.")
	iso3_codes: set[str] = set()
	for area in areas:
		if not isinstance(area, dict) or area.get("level") != "country":
			raise ValueError("Registry contains a non-country area.")
		codes = area.get("codes")
		if not isinstance(codes, dict):
			raise ValueError("Registry country has no codes object.")
		iso3 = str(codes.get("iso3", "")).strip().upper()
		if len(iso3) != 3 or iso3 in iso3_codes:
			raise ValueError(f"Invalid or duplicate registry ISO3: {iso3!r}")
		iso3_codes.add(iso3)
	source = payload.get("source")
	if not isinstance(source, dict) or not str(source.get("release", "")).strip():
		raise ValueError("Country registry has no Overture release.")
	return iso3_codes, str(source["release"])


def load_features(path: Path, registry_codes: set[str]) -> list[dict[str, Any]]:
	features: list[dict[str, Any]] = []
	seen: set[str] = set()
	for raw in path.read_text(encoding="utf-8").splitlines():
		line = raw.strip().lstrip("\x1e")
		if not line:
			continue
		feature = json.loads(line)
		properties = feature.get("properties") or {}
		iso3 = str(properties.get("iso3", "")).strip().upper()
		if not iso3 or iso3 in seen:
			raise RuntimeError(f"Invalid or duplicate geometry ISO3: {iso3!r}")
		geometry = feature.get("geometry")
		if not geometry:
			raise RuntimeError(f"Missing geometry for {iso3}.")
		seen.add(iso3)
		features.append({
			"type": "Feature",
			"properties": {"iso3": iso3},
			"geometry": geometry,
		})
	if seen != registry_codes:
		raise RuntimeError(
			"Country geometry and registry ISO3 sets differ: "
			f"missing={sorted(registry_codes - seen)}, extra={sorted(seen - registry_codes)}"
		)
	return features


def assert_close_sequence(name: str, actual: Any, expected: Any, tolerance: float = 1e-9) -> None:
	if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
		raise RuntimeError(f"{name} length changed: {actual} != {expected}")
	for actual_value, expected_value in zip(actual, expected, strict=True):
		if abs(float(actual_value) - float(expected_value)) > tolerance:
			raise RuntimeError(f"{name} changed: {actual} != {expected}")


def inspect_source(path: Path, config: dict[str, Any], indicator: dict[str, Any]) -> dict[str, Any]:
	with rasterio.open(path) as dataset:
		if dataset.width != int(config["expectedWidth"]) or dataset.height != int(config["expectedHeight"]):
			raise RuntimeError(
				f"Unexpected Global Wind Atlas raster size: {dataset.width}x{dataset.height}."
			)
		if dataset.count != 1:
			raise RuntimeError(f"Expected one raster band, found {dataset.count}.")
		if dataset.crs is None or dataset.crs.to_epsg() != 4326:
			raise RuntimeError(f"Expected EPSG:4326, found {dataset.crs}.")
		if dataset.dtypes[0] != "float32":
			raise RuntimeError(f"Expected Float32 source, found {dataset.dtypes[0]!r}.")
		if dataset.nodata is None or not math.isnan(float(dataset.nodata)):
			raise RuntimeError(f"Expected NaN NoData, found {dataset.nodata!r}.")
		assert_close_sequence("Global Wind Atlas transform", dataset.transform[:6], config["expectedTransform"])
		assert_close_sequence("Global Wind Atlas bounds", dataset.bounds, config["expectedBounds"])
		pixel = float(config["expectedPixelSizeDegrees"])
		if abs(float(dataset.transform.a) - pixel) > 1e-12 or abs(abs(float(dataset.transform.e)) - pixel) > 1e-12:
			raise RuntimeError(f"Unexpected Global Wind Atlas pixel size: {dataset.transform}")
		metadata = {
			"width": dataset.width,
			"height": dataset.height,
			"crs": dataset.crs.to_string(),
			"dataType": dataset.dtypes[0],
			"declaredNoData": "NaN",
			"transform": list(dataset.transform[:6]),
			"bounds": list(dataset.bounds),
			"blockShape": list(dataset.block_shapes[0]),
			"bytes": path.stat().st_size,
			"sha256": sha256_file(path),
		}
	if metadata["bytes"] != indicator["expectedSourceBytes"]:
		raise RuntimeError(
			f"{indicator['id']}: source byte size changed: "
			f"{metadata['bytes']} != {indicator['expectedSourceBytes']}"
		)
	if metadata["sha256"] != indicator["expectedSourceSha256"]:
		raise RuntimeError(
			f"{indicator['id']}: source SHA-256 changed: "
			f"{metadata['sha256']} != {indicator['expectedSourceSha256']}"
		)
	return metadata


def create_area_weights(source: Path, work_dir: Path) -> tuple[Path, dict[str, Any]]:
	with rasterio.open(source) as dataset:
		width = dataset.width
		height = dataset.height
		transform = dataset.transform

	geod = Geod(ellps="WGS84")
	row_weights = np.empty((height, 1), dtype=np.float64)
	west = 0.0
	east = abs(float(transform.a))
	for row in range(height):
		north = float(transform.f + row * transform.e)
		south = float(north + transform.e)
		area, _ = geod.polygon_area_perimeter(
			[west, east, east, west],
			[north, north, south, south],
		)
		row_weights[row, 0] = abs(area)

	work_dir.mkdir(parents=True, exist_ok=True)
	row_path = work_dir / "row-cell-area.tif"
	row_transform = Affine(
		transform.a * width,
		0.0,
		transform.c,
		0.0,
		transform.e,
		transform.f,
	)
	with rasterio.open(
		row_path,
		"w",
		driver="GTiff",
		width=1,
		height=height,
		count=1,
		dtype="float64",
		crs="EPSG:4326",
		transform=row_transform,
		compress="DEFLATE",
	) as dataset:
		dataset.write(row_weights, 1)

	weights_vrt = work_dir / "cell-area-full-grid.vrt"
	run_command([
		"gdal_translate",
		"-of",
		"VRT",
		"-r",
		"nearest",
		"-outsize",
		str(width),
		str(height),
		str(row_path),
		str(weights_vrt),
	])
	with rasterio.open(weights_vrt) as weights_dataset:
		if weights_dataset.width != width or weights_dataset.height != height:
			raise RuntimeError("Global Wind Atlas weight VRT size differs from source grid.")
		assert_close_sequence(
			"Global Wind Atlas weight transform",
			weights_dataset.transform[:6],
			transform[:6],
		)
	return weights_vrt, {
		"minimumCellAreaM2": float(row_weights.min()),
		"maximumCellAreaM2": float(row_weights.max()),
		"rows": height,
		"columnsInPhysicalWeightRaster": 1,
		"virtualColumns": width,
	}


def normalize_results(
	raw: list[dict[str, Any]],
	registry_codes: set[str],
	expected_missing: list[str],
	value_range: list[float],
) -> tuple[dict[str, Any], list[str]]:
	values: dict[str, Any] = {}
	missing: list[str] = []
	minimum_allowed = float(value_range[0])
	maximum_allowed = float(value_range[1])
	for feature in raw:
		properties = feature.get("properties") or {}
		iso3 = str(properties.get("iso3", "")).strip().upper()
		if not iso3 or iso3 in values:
			raise RuntimeError(f"Invalid or duplicate extraction ISO3: {iso3!r}")
		mean = properties.get("weighted_mean")
		minimum = properties.get("min")
		maximum = properties.get("max")
		count = properties.get("count")
		if mean is None or minimum is None or maximum is None or count is None:
			values[iso3] = None
			missing.append(iso3)
			continue
		entry = {
			"weightedMean": float(mean),
			"minimum": float(minimum),
			"maximum": float(maximum),
			"coveredCellEquivalent": float(count),
		}
		if not all(math.isfinite(value) for value in entry.values()):
			raise RuntimeError(f"Non-finite extraction result for {iso3}: {entry}")
		if entry["coveredCellEquivalent"] <= 0:
			raise RuntimeError(f"Non-positive raster coverage for {iso3}: {entry}")
		if not minimum_allowed <= entry["weightedMean"] <= maximum_allowed:
			raise RuntimeError(
				f"Weighted mean outside configured range for {iso3}: {entry['weightedMean']}"
			)
		if entry["minimum"] < 0 or entry["maximum"] < entry["minimum"]:
			raise RuntimeError(f"Invalid source-value range for {iso3}: {entry}")
		values[iso3] = entry
	if set(values) != registry_codes:
		raise RuntimeError("Extraction result ISO3 set differs from registry.")
	if sorted(missing) != expected_missing:
		raise RuntimeError(
			f"Global Wind Atlas coverage changed: expected missing={expected_missing}, actual={sorted(missing)}"
		)
	return dict(sorted(values.items())), sorted(missing)


def main() -> int:
	args = parse_args()
	config = validate_config(read_json(args.config))
	indicator = select_indicator(config, args.indicator_id)
	if args.source_url != indicator["sourceUrl"]:
		raise ValueError(
			f"Unexpected source URL for {args.indicator_id}: {args.source_url!r} != {indicator['sourceUrl']!r}"
		)
	registry_codes, overture_release = load_registry(args.registry)
	features = load_features(args.country_geojsonseq, registry_codes)
	metadata = inspect_source(args.source, config, indicator)
	weights, weight_metadata = create_area_weights(args.source, args.work_dir)

	started = time.monotonic()
	raw = exact_extract(
		str(args.source),
		features,
		["weighted_mean", "min", "max", "count"],
		weights=str(weights),
		include_cols=["iso3"],
		strategy="raster-sequential",
		max_cells_in_memory=5_000_000,
	)
	runtime_seconds = time.monotonic() - started
	values, missing = normalize_results(
		raw,
		registry_codes,
		config["expectedMissingIso3"],
		indicator["valueRange"],
	)

	payload = {
		"schema": "kartensammlung.global-wind-atlas-extraction/v1",
		"indicatorId": indicator["id"],
		"sourceVariable": indicator["sourceVariable"],
		"heightMeters": int(config["heightMeters"]),
		"source": {
			"url": args.source_url,
			**metadata,
		},
		"geometry": {
			"source": "Overture Maps divisions area polygons with is_land = TRUE",
			"overtureRelease": overture_release,
			"countryCount": len(registry_codes),
		},
		"method": {
			"engine": "exactextract 0.3.0",
			"strategy": "raster-sequential",
			"coverage": "exact fractional source-cell coverage",
			"areaWeighting": "WGS84 geodesic source-cell area by latitude row",
			"resampling": "none",
			"sourceOverviews": "not used for statistic",
			"weightRaster": weight_metadata,
		},
		"runtimeSeconds": runtime_seconds,
		"countryCount": len(registry_codes),
		"areasWithValue": len(registry_codes) - len(missing),
		"missingIso3": missing,
		"values": values,
	}
	args.output.parent.mkdir(parents=True, exist_ok=True)
	args.output.write_text(json.dumps(payload, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
	print(
		f"indicator={indicator['id']} countries={len(registry_codes)} "
		f"values={payload['areasWithValue']} missing={len(missing)} seconds={runtime_seconds:.3f}"
	)
	print(
		f"source={metadata['width']}x{metadata['height']} bytes={metadata['bytes']} "
		f"sha256={metadata['sha256']}"
	)
	print("missingIso3=" + ",".join(missing))
	for iso3 in ("AUT", "NOR", "USA", "CAN", "IND", "NAM", "XKX", "VAT", "ATA"):
		entry = values.get(iso3)
		print(f"{iso3}={None if entry is None else entry['weightedMean']}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
