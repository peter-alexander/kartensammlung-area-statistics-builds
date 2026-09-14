#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import rasterio
from exactextract import exact_extract
from pyproj import Geod
from rasterio.transform import Affine

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_WIDTH = 86400
EXPECTED_HEIGHT = 43200
EXPECTED_PIXEL_SIZE = 1.0 / 240.0
EXPECTED_COUNTRIES = 250
REPRESENTATIVE = ("AUT", "NOR", "USA", "CAN", "NAM", "IND", "XKX", "VAT")


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Audit native-resolution DLR Global SnowPack country aggregation with exactextract."
	)
	parser.add_argument("--source", type=Path, required=True)
	parser.add_argument(
		"--country-geojsonseq",
		type=Path,
		default=ROOT / "build" / "country-geometry" / "country.geojsonseq",
	)
	parser.add_argument(
		"--output",
		type=Path,
		default=ROOT / "diagnostics" / "dlr-snowpack-exactextract.json",
	)
	parser.add_argument(
		"--work-dir",
		type=Path,
		default=ROOT / "build" / "dlr-snowpack-exactextract",
	)
	return parser.parse_args()


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


def sha256_file(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as handle:
		for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def read_country_features(path: Path) -> list[dict]:
	features = []
	seen: set[str] = set()
	for raw_line in path.read_text(encoding="utf-8").splitlines():
		line = raw_line.strip().lstrip("\x1e")
		if not line:
			continue
		feature = json.loads(line)
		properties = feature.get("properties") or {}
		iso3 = str(properties.get("iso3") or "").strip().upper()
		if not iso3:
			raise RuntimeError("Country feature without iso3")
		if iso3 in seen:
			raise RuntimeError(f"Duplicate country feature: {iso3}")
		seen.add(iso3)
		features.append(feature)
	if len(features) != EXPECTED_COUNTRIES:
		raise RuntimeError(
			f"Country geometry count mismatch: expected={EXPECTED_COUNTRIES}, actual={len(features)}"
		)
	return features


def source_metadata(path: Path) -> dict:
	completed = run_command(["gdalinfo", "-json", str(path)])
	payload = json.loads(completed.stdout)
	size = payload.get("size") or []
	transform = payload.get("geoTransform") or []
	if size != [EXPECTED_WIDTH, EXPECTED_HEIGHT]:
		raise RuntimeError(f"Unexpected source raster size: {size}")
	if len(transform) != 6:
		raise RuntimeError(f"Unexpected source geotransform: {transform}")
	if abs(float(transform[1]) - EXPECTED_PIXEL_SIZE) > 1e-12:
		raise RuntimeError(f"Unexpected source x resolution: {transform[1]}")
	if abs(float(transform[5]) + EXPECTED_PIXEL_SIZE) > 1e-12:
		raise RuntimeError(f"Unexpected source y resolution: {transform[5]}")
	bands = payload.get("bands") or []
	if len(bands) != 1:
		raise RuntimeError(f"Expected one source band, found {len(bands)}")
	return {
		"size": size,
		"geoTransform": transform,
		"dataType": bands[0].get("type"),
		"declaredNoData": bands[0].get("noDataValue"),
		"bytes": path.stat().st_size,
		"sha256": sha256_file(path),
	}


def prepare_value_vrt(source: Path, work_dir: Path) -> Path:
	value_vrt = work_dir / "snowpack-no-nodata.vrt"
	run_command(
		[
			"gdal_translate",
			"-of",
			"VRT",
			"-a_nodata",
			"none",
			str(source),
			str(value_vrt),
		]
	)
	return value_vrt


def source_grid(path: Path) -> tuple[int, int, Affine]:
	with rasterio.open(path) as dataset:
		return dataset.width, dataset.height, dataset.transform


def create_row_area_weights(value_vrt: Path, work_dir: Path) -> tuple[Path, dict]:
	width, height, transform = source_grid(value_vrt)
	if (width, height) != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
		raise RuntimeError(f"Unexpected VRT grid: {width}x{height}")

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
	run_command(
		[
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
		]
	)

	weight_width, weight_height, weight_transform = source_grid(weights_vrt)
	if (weight_width, weight_height) != (width, height):
		raise RuntimeError("Weight VRT size does not match source grid")
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


def normalize_results(raw_results: list[dict]) -> dict[str, dict]:
	values: dict[str, dict] = {}
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
		if entry["minimumDays"] < -0.001 or entry["maximumDays"] > 366.001:
			raise RuntimeError(
				f"Snow-cover duration range violation for {iso3}: "
				f"min={entry['minimumDays']}, max={entry['maximumDays']}"
			)
		if entry["weightedMeanDays"] < -0.001 or entry["weightedMeanDays"] > 366.001:
			raise RuntimeError(
				f"Snow-cover duration mean range violation for {iso3}: {entry['weightedMeanDays']}"
			)
		values[iso3] = entry
	if len(values) != EXPECTED_COUNTRIES:
		raise RuntimeError(
			f"exactextract result count mismatch: expected={EXPECTED_COUNTRIES}, actual={len(values)}"
		)
	return dict(sorted(values.items()))


def main() -> int:
	args = parse_args()
	args.work_dir.mkdir(parents=True, exist_ok=True)
	features = read_country_features(args.country_geojsonseq)
	metadata = source_metadata(args.source)
	print(f"Source: {metadata}", flush=True)

	value_vrt = prepare_value_vrt(args.source, args.work_dir)
	weights_vrt, weights_metadata = create_row_area_weights(value_vrt, args.work_dir)
	print(f"Weights: {weights_metadata}", flush=True)

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
	values = normalize_results(raw_results)

	for iso3 in REPRESENTATIVE:
		print(f"{iso3}: {values[iso3]}", flush=True)

	payload = {
		"source": metadata,
		"method": {
			"engine": "exactextract 0.3.0",
			"strategy": "raster-sequential",
			"countryGeometry": "Overture Maps division_area with is_land = TRUE",
			"coverage": "exact fractional cell coverage",
			"areaWeighting": "WGS84 geodesic source-cell area by latitude row",
			"zeroPolicy": "Source value 0 is explicitly retained as valid; source NoData metadata is removed in a VRT.",
			"sourceOverviews": "Not used; extraction reads the native source grid.",
			"maxCellsInMemory": 5_000_000,
		},
		"weights": weights_metadata,
		"countryCount": len(values),
		"extractSeconds": round(extract_seconds, 3),
		"representative": {iso3: values[iso3] for iso3 in REPRESENTATIVE},
		"values": values,
	}
	args.output.parent.mkdir(parents=True, exist_ok=True)
	args.output.write_text(
		json.dumps(payload, ensure_ascii=False, indent="\t") + "\n",
		encoding="utf-8",
	)
	print(f"Extracted {len(values)} countries in {extract_seconds:.3f} seconds", flush=True)
	print(f"Wrote {args.output}", flush=True)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
