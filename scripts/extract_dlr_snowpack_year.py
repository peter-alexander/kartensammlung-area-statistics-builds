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
DEFAULT_CONFIG = ROOT / "config" / "dlr-snowpack-indicators.json"
EXPECTED_COUNTRIES = 250


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Aggregate one DLR Global SnowPack yearly SCD raster to country land areas."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--year", type=int, required=True)
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


def run_command(command: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
	completed = subprocess.run(
		command,
		check=False,
		capture_output=True,
		text=True,
		timeout=timeout,
	)
	if completed.returncode != 0:
		raise RuntimeError(
			"Command failed with exit code "
			f"{completed.returncode}: {' '.join(command)}\n"
			f"stdout:\n{completed.stdout[-8000:]}\n"
			f"stderr:\n{completed.stderr[-8000:]}"
		)
	return completed


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.dlr-snowpack-statistics/v1":
		raise ValueError("Invalid DLR SnowPack config.")
	for key in (
		"downloadBase",
		"startYear",
		"minimumLatestYear",
		"expectedWidth",
		"expectedHeight",
		"expectedPixelSizeDegrees",
	):
		if key not in payload:
			raise ValueError(f"DLR SnowPack config is missing {key}.")
	return payload


def load_registry(path: Path) -> tuple[set[str], str]:
	payload = read_json(path)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.area-registry/v1":
		raise ValueError("Invalid country area registry.")
	source = payload.get("source")
	if not isinstance(source, dict):
		raise ValueError("Country area registry has no source metadata.")
	overture_release = str(source.get("release", "")).strip()
	if not overture_release:
		raise ValueError("Country area registry has no Overture release.")
	iso3_codes: set[str] = set()
	for area in payload.get("areas", []):
		if not isinstance(area, dict) or area.get("level") != "country":
			continue
		codes = area.get("codes")
		if not isinstance(codes, dict):
			continue
		iso3 = str(codes.get("iso3", "")).strip().upper()
		if len(iso3) != 3:
			raise ValueError(f"Invalid ISO3 code in registry: {iso3!r}")
		if iso3 in iso3_codes:
			raise ValueError(f"Duplicate ISO3 code in registry: {iso3}")
		iso3_codes.add(iso3)
	if len(iso3_codes) != EXPECTED_COUNTRIES:
		raise RuntimeError(
			f"Country registry count mismatch: expected={EXPECTED_COUNTRIES}, actual={len(iso3_codes)}"
		)
	return iso3_codes, overture_release


def read_country_features(path: Path, registry_codes: set[str]) -> list[dict[str, Any]]:
	features: list[dict[str, Any]] = []
	seen: set[str] = set()
	for raw_line in path.read_text(encoding="utf-8").splitlines():
		line = raw_line.strip().lstrip("\x1e")
		if not line:
			continue
		feature = json.loads(line)
		properties = feature.get("properties") or {}
		iso3 = str(properties.get("iso3") or "").strip().upper()
		if not iso3:
			raise RuntimeError("Country feature without iso3.")
		if iso3 in seen:
			raise RuntimeError(f"Duplicate country feature: {iso3}")
		geometry = feature.get("geometry")
		if not geometry:
			raise RuntimeError(f"Country feature without geometry: {iso3}")
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


def validate_source(path: Path, config: dict[str, Any]) -> dict[str, Any]:
	expected_width = int(config["expectedWidth"])
	expected_height = int(config["expectedHeight"])
	expected_pixel = float(config["expectedPixelSizeDegrees"])
	with rasterio.open(path) as dataset:
		if dataset.width != expected_width or dataset.height != expected_height:
			raise RuntimeError(
				f"Unexpected source raster size: {dataset.width}x{dataset.height}; "
				f"expected {expected_width}x{expected_height}."
			)
		if dataset.count != 1:
			raise RuntimeError(f"Expected one source band, found {dataset.count}.")
		if dataset.dtypes[0] != "int16":
			raise RuntimeError(f"Unexpected source data type: {dataset.dtypes[0]!r}")
		if dataset.crs is None or dataset.crs.to_epsg() != 4326:
			raise RuntimeError(f"Unexpected source CRS: {dataset.crs}")
		transform = dataset.transform
		expected_transform = Affine(expected_pixel, 0.0, -180.0, 0.0, -expected_pixel, 90.0)
		for actual, expected in zip(transform[:6], expected_transform[:6], strict=True):
			if abs(float(actual) - float(expected)) > 1e-12:
				raise RuntimeError(
					f"Unexpected source geotransform: actual={transform}, expected={expected_transform}"
				)
		bounds = dataset.bounds
		for actual, expected in zip(bounds, (-180.0, -90.0, 180.0, 90.0), strict=True):
			if abs(float(actual) - expected) > 1e-9:
				raise RuntimeError(f"Unexpected source bounds: {bounds}")
		if dataset.nodata != 0.0:
			raise RuntimeError(
				"DLR SnowPack source NoData metadata changed. The audited production method expects "
				f"declared NoData=0 while retaining zero as a valid SCD value; got {dataset.nodata!r}."
			)
		return {
			"width": dataset.width,
			"height": dataset.height,
			"crs": dataset.crs.to_string(),
			"transform": list(transform[:6]),
			"dataType": dataset.dtypes[0],
			"declaredNoData": dataset.nodata,
			"bytes": path.stat().st_size,
			"sha256": sha256_file(path),
		}


def prepare_value_vrt(source: Path, work_dir: Path) -> Path:
	value_vrt = work_dir / "snowpack-no-nodata.vrt"
	run_command([
		"gdal_translate",
		"-of",
		"VRT",
		"-a_nodata",
		"none",
		str(source),
		str(value_vrt),
	])
	return value_vrt


def source_grid(path: Path) -> tuple[int, int, Affine]:
	with rasterio.open(path) as dataset:
		return dataset.width, dataset.height, dataset.transform


def create_row_area_weights(value_vrt: Path, work_dir: Path) -> tuple[Path, dict[str, Any]]:
	width, height, transform = source_grid(value_vrt)
	geod = Geod(ellps="WGS84")
	row_weights = np.empty((height, 1), dtype=np.float64)
	west = 0.0
	east = abs(transform.a)
	for row in range(height):
		north = transform.f + row * transform.e
		south = north + transform.e
		area, _ = geod.polygon_area_perimeter(
			[west, east, east, west],
			[north, north, south, south],
		)
		row_weights[row, 0] = abs(area)

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
	weight_width, weight_height, weight_transform = source_grid(weights_vrt)
	if (weight_width, weight_height) != (width, height):
		raise RuntimeError("Weight VRT size does not match source grid.")
	for source_value, weight_value in zip(transform[:6], weight_transform[:6], strict=True):
		if abs(float(source_value) - float(weight_value)) > 1e-10:
			raise RuntimeError(
				f"Weight VRT geotransform mismatch: source={transform}, weights={weight_transform}"
			)
	return weights_vrt, {
		"minimumCellAreaM2": float(row_weights.min()),
		"maximumCellAreaM2": float(row_weights.max()),
		"equatorCellAreaM2": float(row_weights[height // 2, 0]),
		"rows": height,
		"columnsInPhysicalWeightRaster": 1,
		"virtualColumns": width,
	}


def normalize_results(raw_results: list[dict[str, Any]], registry_codes: set[str]) -> dict[str, dict[str, float]]:
	values: dict[str, dict[str, float]] = {}
	for feature in raw_results:
		properties = feature.get("properties") or {}
		iso3 = str(properties.get("iso3") or "").strip().upper()
		if not iso3:
			raise RuntimeError(f"exactextract result without iso3: {properties}")
		if iso3 in values:
			raise RuntimeError(f"Duplicate exactextract result for {iso3}")
		entry = {
			"weightedMeanDays": float(properties["weighted_mean"]),
			"minimumDays": float(properties["min"]),
			"maximumDays": float(properties["max"]),
			"coveredCellEquivalent": float(properties["count"]),
		}
		for key in ("weightedMeanDays", "minimumDays", "maximumDays", "coveredCellEquivalent"):
			if not math.isfinite(entry[key]):
				raise RuntimeError(f"Non-finite {key} for {iso3}: {entry[key]}")
		if not 0.0 <= entry["minimumDays"] <= 366.001:
			raise RuntimeError(f"Snow-cover minimum range violation for {iso3}: {entry['minimumDays']}")
		if not 0.0 <= entry["maximumDays"] <= 366.001:
			raise RuntimeError(f"Snow-cover maximum range violation for {iso3}: {entry['maximumDays']}")
		if not 0.0 <= entry["weightedMeanDays"] <= 366.001:
			raise RuntimeError(f"Snow-cover mean range violation for {iso3}: {entry['weightedMeanDays']}")
		if entry["coveredCellEquivalent"] <= 0:
			raise RuntimeError(f"No raster coverage for {iso3}.")
		values[iso3] = entry
	if set(values) != registry_codes:
		raise RuntimeError("exactextract result ISO3 set differs from the country registry.")
	return dict(sorted(values.items()))


def main() -> int:
	args = parse_args()
	config = validate_config(read_json(args.config))
	if args.year < int(config["startYear"]):
		raise ValueError(f"Year {args.year} predates configured SnowPack start year.")
	registry_codes, overture_release = load_registry(args.registry)
	features = read_country_features(args.country_geojsonseq, registry_codes)
	metadata = validate_source(args.source, config)
	args.work_dir.mkdir(parents=True, exist_ok=True)
	value_vrt = prepare_value_vrt(args.source, args.work_dir)
	weights_vrt, weights_metadata = create_row_area_weights(value_vrt, args.work_dir)

	started = time.monotonic()
	raw_results = exact_extract(
		str(value_vrt),
		features,
		["weighted_mean", "min", "max", "count"],
		weights=str(weights_vrt),
		include_cols=["iso3"],
		strategy="raster-sequential",
		max_cells_in_memory=5_000_000,
	)
	extract_seconds = time.monotonic() - started
	values = normalize_results(raw_results, registry_codes)

	payload = {
		"schema": "kartensammlung.dlr-snowpack-year/v1",
		"year": args.year,
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
			"zeroPolicy": "Source value 0 is retained as valid; source NoData metadata is removed only in an analysis VRT.",
			"sourceOverviews": "not used; extraction reads the native source grid",
			"maxCellsInMemory": 5_000_000,
		},
		"weights": weights_metadata,
		"countryCount": len(values),
		"extractSeconds": round(extract_seconds, 3),
		"values": values,
	}
	args.output.parent.mkdir(parents=True, exist_ok=True)
	args.output.write_text(
		json.dumps(payload, ensure_ascii=False, indent="\t") + "\n",
		encoding="utf-8",
	)
	print(
		f"{args.year}: extracted {len(values)} countries in {extract_seconds:.3f}s; "
		f"sourceSha256={metadata['sha256']} overtureRelease={overture_release}",
		flush=True,
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
