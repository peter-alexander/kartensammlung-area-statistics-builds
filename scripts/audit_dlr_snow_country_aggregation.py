#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import bounds as window_bounds
from shapely import make_valid
from shapely.geometry import box, shape
from shapely.prepared import prep

DEFAULT_SCD_URL = (
	"https://download.geoservice.dlr.de/GSP/files/yearly/SCD/2024/"
	"2024_SCD_full_wgs84.tif"
)
DEFAULT_COUNTRIES = (
	"AUT",
	"DEU",
	"FIN",
	"NOR",
	"CAN",
	"USA",
	"CHL",
	"ARG",
	"JPN",
	"NZL",
	"ISL",
	"ZAF",
	"XKX",
	"SGP",
	"MLT",
	"MCO",
	"VAT",
)
EARTH_RADIUS_M = 6371008.8


@dataclass
class Aggregate:
	weighted_sum: float = 0.0
	weight_sum: float = 0.0
	pixel_count: int = 0
	zero_count: int = 0
	minimum: int | None = None
	maximum: int | None = None

	def add(self, values: np.ndarray, row_weights: np.ndarray) -> None:
		if values.size == 0:
			return
		minimum = int(values.min())
		maximum = int(values.max())
		if minimum < 0 or maximum > 366:
			raise RuntimeError(
				f"Unexpected SCD value range inside country geometry: min={minimum}, max={maximum}"
			)
		weights = row_weights.astype(np.float64, copy=False)
		self.weighted_sum += float(np.sum(values.astype(np.float64, copy=False) * weights))
		self.weight_sum += float(np.sum(weights))
		self.pixel_count += int(values.size)
		self.zero_count += int(np.count_nonzero(values == 0))
		self.minimum = minimum if self.minimum is None else min(self.minimum, minimum)
		self.maximum = maximum if self.maximum is None else max(self.maximum, maximum)

	def finish(self, pixel_area_scale_km2: float) -> dict:
		mean = self.weighted_sum / self.weight_sum if self.weight_sum > 0 else None
		area_km2 = self.weight_sum * pixel_area_scale_km2
		return {
			"meanSnowCoverDays": mean,
			"pixelCount": self.pixel_count,
			"zeroPixelCount": self.zero_count,
			"zeroPixelShare": (
				self.zero_count / self.pixel_count if self.pixel_count > 0 else None
			),
			"minimum": self.minimum,
			"maximum": self.maximum,
			"rasterizedAreaKm2": area_km2,
		}


@dataclass
class CountryAccumulator:
	iso3: str
	name: str
	registry_area_km2: float
	center: Aggregate
	all_touched: Aggregate
	blocks_read: int = 0


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description=(
			"Prototype exact-land country aggregation for DLR Global SnowPack SCD. "
			"Raster value 0 is intentionally treated as a valid zero-snow value."
		)
	)
	parser.add_argument("--geometry", type=Path, required=True)
	parser.add_argument("--registry", type=Path, required=True)
	parser.add_argument("--source", default=DEFAULT_SCD_URL)
	parser.add_argument(
		"--countries",
		default=",".join(DEFAULT_COUNTRIES),
		help="Comma-separated ISO3 list.",
	)
	parser.add_argument(
		"--output",
		type=Path,
		default=Path("diagnostics/dlr-snow-country-aggregation-2024.json"),
	)
	return parser.parse_args()


def read_geojsonseq(path: Path) -> dict[str, dict]:
	features: dict[str, dict] = {}
	with path.open("r", encoding="utf-8") as handle:
		for raw_line in handle:
			line = raw_line.strip().lstrip("\x1e")
			if not line:
				continue
			feature = json.loads(line)
			properties = feature.get("properties") or {}
			iso3 = str(properties.get("iso3") or "").strip().upper()
			if not iso3:
				continue
			if iso3 in features:
				raise RuntimeError(f"Duplicate geometry for {iso3}")
			features[iso3] = feature
	return features


def read_registry(path: Path) -> dict[str, dict]:
	payload = json.loads(path.read_text(encoding="utf-8"))
	areas: dict[str, dict] = {}
	for area in payload.get("areas", []):
		codes = area.get("codes") or {}
		iso3 = str(codes.get("iso3") or "").strip().upper()
		if iso3:
			areas[iso3] = area
	return areas


def row_area_weights(transform: rasterio.Affine, row_off: int, height: int) -> np.ndarray:
	rows = row_off + np.arange(height, dtype=np.float64)
	lat_top = transform.f + rows * transform.e
	lat_bottom = lat_top + transform.e
	return np.abs(
		np.sin(np.deg2rad(lat_top)) - np.sin(np.deg2rad(lat_bottom))
	)


def selected_values(
	data: np.ndarray,
	mask: np.ndarray,
	row_weights: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
	row_indices, column_indices = np.nonzero(mask)
	if row_indices.size == 0:
		return np.empty(0, dtype=data.dtype), np.empty(0, dtype=np.float64)
	return data[row_indices, column_indices], row_weights[row_indices]


def rasterize_country(
	geometry_mapping: dict,
	shape_: tuple[int, int],
	transform: rasterio.Affine,
	all_touched: bool,
) -> np.ndarray:
	return rasterize(
		[(geometry_mapping, 1)],
		out_shape=shape_,
		transform=transform,
		fill=0,
		default_value=1,
		all_touched=all_touched,
		dtype="uint8",
	)


def main() -> int:
	args = parse_args()
	requested = tuple(
		dict.fromkeys(
			part.strip().upper()
			for part in str(args.countries).split(",")
			if part.strip()
		)
	)
	if not requested:
		raise SystemExit("At least one --countries ISO3 code is required.")

	features = read_geojsonseq(args.geometry)
	registry = read_registry(args.registry)
	missing_geometry = sorted(set(requested) - set(features))
	missing_registry = sorted(set(requested) - set(registry))
	if missing_geometry or missing_registry:
		raise RuntimeError(
			f"Missing prototype inputs: geometry={missing_geometry}, registry={missing_registry}"
		)

	accumulators: dict[str, CountryAccumulator] = {}
	prepared = {}
	geometry_mappings = {}
	for iso3 in requested:
		feature = features[iso3]
		geometry = shape(feature["geometry"])
		if not geometry.is_valid:
			geometry = make_valid(geometry)
		if geometry.is_empty:
			raise RuntimeError(f"Empty geometry for {iso3}")
		area = registry[iso3]
		registry_area_km2 = float(area["metadata"]["areaKm2"])
		name = str((area.get("name") or {}).get("de") or (area.get("name") or {}).get("default") or iso3)
		accumulators[iso3] = CountryAccumulator(
			iso3=iso3,
			name=name,
			registry_area_km2=registry_area_km2,
			center=Aggregate(),
			all_touched=Aggregate(),
		)
		prepared[iso3] = prep(geometry)
		geometry_mappings[iso3] = geometry.__geo_interface__

	started = time.monotonic()
	blocks_total = 0
	blocks_with_samples = 0
	bytes_read_unavailable = True

	with rasterio.Env(
		GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
		CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
		GDAL_HTTP_MULTIRANGE="YES",
		GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
		GDAL_HTTP_CONNECTTIMEOUT="10",
		GDAL_HTTP_TIMEOUT="30",
		VSI_CACHE="TRUE",
		VSI_CACHE_SIZE="50000000",
	):
		with rasterio.open(f"/vsicurl/{args.source}") as source:
			if source.crs is None or source.crs.to_epsg() != 4326:
				raise RuntimeError(f"Expected EPSG:4326 source, got {source.crs}")
			if abs(source.transform.b) > 1e-12 or abs(source.transform.d) > 1e-12:
				raise RuntimeError(f"Rotated raster is unsupported: {source.transform}")
			if source.count != 1:
				raise RuntimeError(f"Expected one SCD band, got {source.count}")
			if source.width != 86400 or source.height != 43200:
				raise RuntimeError(
					f"Unexpected source dimensions: {source.width}x{source.height}"
				)

			longitude_width_rad = math.radians(abs(source.transform.a))
			pixel_area_scale_km2 = (
				EARTH_RADIUS_M * EARTH_RADIUS_M * longitude_width_rad / 1_000_000.0
			)

			print(
				f"source={args.source} size={source.width}x{source.height} "
				f"blockShapes={source.block_shapes} dtype={source.dtypes[0]} "
				f"nodata={source.nodata}",
				flush=True,
			)
			print(
				"IMPORTANT: source nodata=0 is ignored intentionally; "
				"0 is a documented valid snow-cover-duration value.",
				flush=True,
			)

			for _, window in source.block_windows(1):
				blocks_total += 1
				left, bottom, right, top = window_bounds(window, source.transform)
				block_box = box(left, bottom, right, top)
				candidates = [
					iso3
					for iso3 in requested
					if prepared[iso3].intersects(block_box)
				]
				if not candidates:
					continue

				data = source.read(1, window=window, masked=False)
				blocks_with_samples += 1
				block_transform = source.window_transform(window)
				row_weights = row_area_weights(
					source.transform,
					int(window.row_off),
					int(window.height),
				)

				for iso3 in candidates:
					accumulator = accumulators[iso3]
					center_mask = rasterize_country(
						geometry_mappings[iso3],
						data.shape,
						block_transform,
						False,
					)
					center_values, center_weights = selected_values(
						data,
						center_mask,
						row_weights,
					)
					accumulator.center.add(center_values, center_weights)

					all_touched_mask = rasterize_country(
						geometry_mappings[iso3],
						data.shape,
						block_transform,
						True,
					)
					all_values, all_weights = selected_values(
						data,
						all_touched_mask,
						row_weights,
					)
					accumulator.all_touched.add(all_values, all_weights)
					accumulator.blocks_read += 1

		elapsed = time.monotonic() - started
		results = {}
		for iso3 in requested:
			accumulator = accumulators[iso3]
			center = accumulator.center.finish(pixel_area_scale_km2)
			all_touched = accumulator.all_touched.finish(pixel_area_scale_km2)
			registry_area = accumulator.registry_area_km2
			center["areaRatioVsRegistry"] = (
				center["rasterizedAreaKm2"] / registry_area if registry_area > 0 else None
			)
			all_touched["areaRatioVsRegistry"] = (
				all_touched["rasterizedAreaKm2"] / registry_area if registry_area > 0 else None
			)
			center_mean = center["meanSnowCoverDays"]
			all_mean = all_touched["meanSnowCoverDays"]
			results[iso3] = {
				"name": accumulator.name,
				"registryAreaKm2": registry_area,
				"blocksRead": accumulator.blocks_read,
				"centerPixel": center,
				"allTouched": all_touched,
				"boundarySensitivityDays": (
					all_mean - center_mean
					if center_mean is not None and all_mean is not None
					else None
				),
			}
			print(
				f"{iso3} {accumulator.name}: mean={center_mean} "
				f"pixels={center['pixelCount']} zeros={center['zeroPixelShare']} "
				f"area={center['rasterizedAreaKm2']:.2f}/{registry_area:.2f} km2 "
				f"ratio={center['areaRatioVsRegistry']:.6f} "
				f"allTouchedMean={all_mean} "
				f"delta={results[iso3]['boundarySensitivityDays']}",
				flush=True,
			)

	payload = {
		"source": {
			"provider": "DLR/EOC Global SnowPack",
			"collection": "GSP_SCD_P1Y",
			"year": 2024,
			"url": args.source,
			"resolutionDegrees": 1 / 240,
			"documentedValueRangeDays": [0, 365],
			"zeroHandling": (
				"Raster metadata declares NoData=0, but the documented product range includes 0 days. "
				"The prototype therefore reads raw values and uses the Overture is_land=true polygon as "
				"the validity mask."
			),
		},
		"method": {
			"geometry": "Overture division_area with is_land=true, generated by scripts/build_countries.py",
			"aggregation": "area-weighted mean over raster cells selected by country land polygon",
			"areaWeighting": (
				"exact spherical row-area factor sin(latitude_top)-sin(latitude_bottom); "
				"constant longitude width cancels from the mean"
			),
			"primaryBoundaryRule": "pixel center inside polygon (rasterize all_touched=false)",
			"sensitivityRule": "all intersecting pixels (rasterize all_touched=true)",
		},
		"benchmark": {
			"elapsedSeconds": elapsed,
			"sourceBlocksTotal": blocks_total,
			"sourceBlocksRead": blocks_with_samples,
			"remoteBytesRead": None if bytes_read_unavailable else 0,
		},
		"countries": results,
	}
	args.output.parent.mkdir(parents=True, exist_ok=True)
	args.output.write_text(
		json.dumps(payload, ensure_ascii=False, indent="\t") + "\n",
		encoding="utf-8",
	)
	print(
		f"Wrote {args.output}; elapsed={elapsed:.2f}s "
		f"blocks={blocks_with_samples}/{blocks_total}",
		flush=True,
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
