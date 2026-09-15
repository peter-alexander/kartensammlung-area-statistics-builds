#!/usr/bin/env python3
from __future__ import annotations

import argparse
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

EXPECTED_COUNTRIES = 250


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Benchmark native all-country aggregation of one downloaded Global Wind Atlas raster."
	)
	parser.add_argument("--source", type=Path, required=True)
	parser.add_argument("--country-geojsonseq", type=Path, required=True)
	parser.add_argument("--registry", type=Path, required=True)
	parser.add_argument("--work-dir", type=Path, required=True)
	parser.add_argument("--output", type=Path, required=True)
	return parser.parse_args()


def read_json(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def run(command: list[str], timeout: int = 600) -> None:
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
			f"stdout:\n{completed.stdout[-4000:]}\nstderr:\n{completed.stderr[-4000:]}"
		)


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
		codes = area.get("codes") or {}
		iso3 = str(codes.get("iso3", "")).strip().upper()
		if len(iso3) != 3 or iso3 in iso3_codes:
			raise ValueError(f"Invalid or duplicate registry ISO3: {iso3!r}")
		iso3_codes.add(iso3)
	release = str((payload.get("source") or {}).get("release", "")).strip()
	if not release:
		raise ValueError("Registry has no Overture release.")
	return iso3_codes, release


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
			"Geometry and registry ISO3 sets differ: "
			f"missing={sorted(registry_codes - seen)}, extra={sorted(seen - registry_codes)}"
		)
	return features


def inspect_source(path: Path) -> dict[str, Any]:
	with rasterio.open(path) as dataset:
		if dataset.count != 1:
			raise RuntimeError(f"Expected one raster band, found {dataset.count}.")
		if dataset.crs is None or dataset.crs.to_epsg() != 4326:
			raise RuntimeError(f"Expected EPSG:4326, found {dataset.crs}.")
		if dataset.dtypes[0] != "float32":
			raise RuntimeError(f"Expected Float32 source, found {dataset.dtypes[0]!r}.")
		transform = dataset.transform
		if abs(transform.b) > 1e-12 or abs(transform.d) > 1e-12:
			raise RuntimeError(f"Expected north-up source grid, found {transform}.")
		if abs(float(transform.a) - 0.0025) > 1e-12 or abs(abs(float(transform.e)) - 0.0025) > 1e-12:
			raise RuntimeError(f"Expected 0.0025° source pixels, found {transform}.")
		if dataset.nodata is None or not math.isnan(float(dataset.nodata)):
			raise RuntimeError(f"Expected NaN NoData, found {dataset.nodata!r}.")
		return {
			"width": dataset.width,
			"height": dataset.height,
			"crs": dataset.crs.to_string(),
			"dtype": dataset.dtypes[0],
			"nodata": "NaN",
			"transform": list(transform[:6]),
			"bounds": list(dataset.bounds),
			"bytes": path.stat().st_size,
		}


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
	run([
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
	return weights_vrt, {
		"minimumCellAreaM2": float(row_weights.min()),
		"maximumCellAreaM2": float(row_weights.max()),
		"rows": height,
		"columnsInPhysicalWeightRaster": 1,
		"virtualColumns": width,
	}


def normalize_results(raw: list[dict[str, Any]], registry_codes: set[str]) -> tuple[dict[str, Any], list[str]]:
	values: dict[str, Any] = {}
	missing: list[str] = []
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
		values[iso3] = entry
	if set(values) != registry_codes:
		raise RuntimeError("Extraction result ISO3 set differs from registry.")
	return dict(sorted(values.items())), sorted(missing)


def main() -> int:
	args = parse_args()
	registry_codes, overture_release = load_registry(args.registry)
	features = load_features(args.country_geojsonseq, registry_codes)
	metadata = inspect_source(args.source)
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
	seconds = time.monotonic() - started
	values, missing = normalize_results(raw, registry_codes)

	payload = {
		"schema": "kartensammlung.global-wind-atlas-audit/v1",
		"source": metadata,
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
			"weightRaster": weight_metadata,
		},
		"runtimeSeconds": seconds,
		"areasWithValue": len(values) - len(missing),
		"missingIso3": missing,
		"values": values,
	}
	args.output.parent.mkdir(parents=True, exist_ok=True)
	args.output.write_text(json.dumps(payload, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
	print(
		f"countries={len(registry_codes)} values={payload['areasWithValue']} "
		f"missing={len(missing)} seconds={seconds:.3f}"
	)
	print(f"raster={metadata['width']}x{metadata['height']} bytes={metadata['bytes']}")
	if missing:
		print("missingIso3=" + ",".join(missing))
	for iso3 in ("AUT", "NOR", "USA", "CAN", "IND", "NAM", "XKX", "VAT", "ATA"):
		print(f"{iso3}={values.get(iso3)}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
