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


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Benchmark exact country extraction from a Global Wind Atlas raster.")
	parser.add_argument("--source", required=True)
	parser.add_argument("--country-geojsonseq", type=Path, required=True)
	parser.add_argument("--iso3", required=True)
	parser.add_argument("--work-dir", type=Path, required=True)
	parser.add_argument("--output", type=Path, required=True)
	return parser.parse_args()


def run(command: list[str]) -> None:
	completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=300)
	if completed.returncode != 0:
		raise RuntimeError(
			f"Command failed ({completed.returncode}): {' '.join(command)}\n"
			f"stdout:\n{completed.stdout[-4000:]}\nstderr:\n{completed.stderr[-4000:]}"
		)


def load_feature(path: Path, iso3: str) -> dict[str, Any]:
	matches: list[dict[str, Any]] = []
	for raw in path.read_text(encoding="utf-8").splitlines():
		line = raw.strip().lstrip("\x1e")
		if not line:
			continue
		feature = json.loads(line)
		properties = feature.get("properties") or {}
		if str(properties.get("iso3", "")).upper() == iso3:
			matches.append({
				"type": "Feature",
				"properties": {"iso3": iso3},
				"geometry": feature["geometry"],
			})
	if len(matches) != 1:
		raise RuntimeError(f"Expected exactly one geometry for {iso3}, found {len(matches)}.")
	return matches[0]


def raster_path(source: str) -> str:
	if source.startswith("https://") or source.startswith("http://"):
		return "/vsicurl/" + source
	return source


def create_area_weights(source: str, work_dir: Path) -> tuple[Path, dict[str, Any]]:
	path = raster_path(source)
	with rasterio.open(path) as dataset:
		if dataset.count != 1:
			raise RuntimeError(f"Expected one raster band, found {dataset.count}.")
		if dataset.crs is None or dataset.crs.to_epsg() != 4326:
			raise RuntimeError(f"Expected EPSG:4326, found {dataset.crs}.")
		width = dataset.width
		height = dataset.height
		transform = dataset.transform
		bounds = tuple(float(value) for value in dataset.bounds)
		dtype = dataset.dtypes[0]
		nodata = dataset.nodata

	if abs(transform.b) > 1e-12 or abs(transform.d) > 1e-12 or transform.a <= 0 or transform.e >= 0:
		raise RuntimeError(f"Unexpected raster transform: {transform}")

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
		"width": width,
		"height": height,
		"dtype": dtype,
		"nodata": None if nodata is None else str(nodata),
		"transform": list(transform[:6]),
		"bounds": list(bounds),
		"pixelSizeDegrees": [float(transform.a), abs(float(transform.e))],
	}


def main() -> int:
	args = parse_args()
	iso3 = args.iso3.strip().upper()
	if len(iso3) != 3:
		raise ValueError("--iso3 must be a three-letter code.")
	feature = load_feature(args.country_geojsonseq, iso3)
	weights, raster = create_area_weights(args.source, args.work_dir)

	started = time.monotonic()
	results = exact_extract(
		raster_path(args.source),
		[feature],
		["weighted_mean", "min", "max", "count"],
		weights=str(weights),
		include_cols=["iso3"],
		strategy="feature-sequential",
		max_cells_in_memory=5_000_000,
	)
	seconds = time.monotonic() - started
	if len(results) != 1:
		raise RuntimeError(f"Expected one extraction result, found {len(results)}.")
	properties = results[0].get("properties") or {}
	values = {
		"weightedMean": float(properties["weighted_mean"]),
		"minimum": float(properties["min"]),
		"maximum": float(properties["max"]),
		"coveredCellEquivalent": float(properties["count"]),
	}
	if not all(math.isfinite(value) for value in values.values()):
		raise RuntimeError(f"Non-finite extraction result: {values}")

	payload = {
		"source": args.source,
		"iso3": iso3,
		"raster": raster,
		"strategy": "feature-sequential",
		"areaWeighting": "WGS84 geodesic source-cell area by latitude row",
		"seconds": seconds,
		"values": values,
	}
	args.output.parent.mkdir(parents=True, exist_ok=True)
	args.output.write_text(json.dumps(payload, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
	print(json.dumps(payload, ensure_ascii=False, indent=2))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
