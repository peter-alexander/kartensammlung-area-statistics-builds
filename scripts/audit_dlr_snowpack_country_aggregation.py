#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCD_URL = "https://download.geoservice.dlr.de/GSP/files/yearly/SCD/2024/2024_SCD_full_wgs84.tif"
DEFAULT_COUNTRIES = ("AUT", "NOR", "USA", "CAN", "NAM", "IND", "XKX", "VAT")
DEFAULT_FINE_COUNTRIES = ("AUT", "NOR", "XKX", "VAT")


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Prototype equal-area country aggregation of DLR Global SnowPack SCD."
	)
	parser.add_argument(
		"--country-geojsonseq",
		type=Path,
		default=ROOT / "build" / "country-geometry" / "country.geojsonseq",
	)
	parser.add_argument(
		"--output",
		type=Path,
		default=ROOT / "diagnostics" / "dlr-snowpack-country-aggregation.json",
	)
	parser.add_argument(
		"--work-dir",
		type=Path,
		default=ROOT / "build" / "dlr-snowpack-country-aggregation",
	)
	return parser.parse_args()


def read_country_features(path: Path) -> dict[str, dict]:
	features: dict[str, dict] = {}
	for raw_line in path.read_text(encoding="utf-8").splitlines():
		line = raw_line.strip().lstrip("\x1e")
		if not line:
			continue
		feature = json.loads(line)
		properties = feature.get("properties") or {}
		iso3 = str(properties.get("iso3") or "").strip().upper()
		if not iso3:
			continue
		if iso3 in features:
			raise RuntimeError(f"Duplicate country feature for {iso3}")
		features[iso3] = feature
	return features


def write_cutline(feature: dict, output_path: Path) -> None:
	payload = {
		"type": "FeatureCollection",
		"features": [feature],
	}
	output_path.write_text(
		json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
		encoding="utf-8",
	)


def run_command(command: list[str], env: dict[str, str] | None = None, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
	completed = subprocess.run(
		command,
		check=False,
		capture_output=True,
		text=True,
		env=env,
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


def gdal_env() -> dict[str, str]:
	env = dict(os.environ)
	env.update(
		{
			"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
			"CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
			"GDAL_HTTP_MULTIRANGE": "YES",
			"GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
			"GDAL_CACHEMAX": "512",
		}
	)
	return env


def warp_country(cutline: Path, output_path: Path, resolution_m: int) -> float:
	started = time.monotonic()
	command = [
		"gdalwarp",
		"-overwrite",
		"-multi",
		"-wo",
		"NUM_THREADS=ALL_CPUS",
		"-t_srs",
		"EPSG:6933",
		"-tr",
		str(resolution_m),
		str(resolution_m),
		"-tap",
		"-r",
		"average",
		"-srcnodata",
		"None",
		"-dstnodata",
		"-9999",
		"-ot",
		"Float32",
		"-cutline",
		str(cutline),
		"-crop_to_cutline",
		"-co",
		"TILED=YES",
		"-co",
		"COMPRESS=DEFLATE",
		"-co",
		"PREDICTOR=3",
		f"/vsicurl/{SCD_URL}",
		str(output_path),
	]
	run_command(command, env=gdal_env())
	return time.monotonic() - started


def raster_stats(path: Path) -> dict:
	completed = run_command(["gdalinfo", "-json", "-stats", str(path)], timeout=900)
	payload = json.loads(completed.stdout)
	bands = payload.get("bands") or []
	if len(bands) != 1:
		raise RuntimeError(f"Expected one band in {path}, found {len(bands)}")
	band = bands[0]
	metadata = band.get("metadata") or {}
	stats_metadata = metadata.get("") or {}

	def numeric(field: str, fallback_key: str | None = None) -> float | None:
		value = band.get(field)
		if value is None and fallback_key:
			value = stats_metadata.get(fallback_key)
		if value is None:
			return None
		return float(value)

	size = payload.get("size") or [0, 0]
	valid_percent = numeric("validPercent", "STATISTICS_VALID_PERCENT")
	total_pixels = int(size[0]) * int(size[1])
	valid_pixels = None
	if valid_percent is not None:
		valid_pixels = round(total_pixels * valid_percent / 100.0)
	return {
		"size": size,
		"totalPixels": total_pixels,
		"validPercent": valid_percent,
		"validPixelsApprox": valid_pixels,
		"minimum": numeric("minimum", "STATISTICS_MINIMUM"),
		"maximum": numeric("maximum", "STATISTICS_MAXIMUM"),
		"mean": numeric("mean", "STATISTICS_MEAN"),
		"stdDev": numeric("stdDev", "STATISTICS_STDDEV"),
		"bytes": path.stat().st_size,
	}


def aggregate_country(feature: dict, iso3: str, resolution_m: int, work_dir: Path) -> dict:
	country_dir = work_dir / iso3
	country_dir.mkdir(parents=True, exist_ok=True)
	cutline = country_dir / f"{iso3}.geojson"
	output_path = country_dir / f"{iso3}-{resolution_m}m.tif"
	write_cutline(feature, cutline)
	seconds = warp_country(cutline, output_path, resolution_m)
	stats = raster_stats(output_path)
	stats["warpSeconds"] = round(seconds, 3)
	return stats


def main() -> int:
	args = parse_args()
	features = read_country_features(args.country_geojsonseq)
	missing = sorted(set(DEFAULT_COUNTRIES) - set(features))
	if missing:
		raise RuntimeError("Missing prototype country geometry: " + ", ".join(missing))

	if args.work_dir.exists():
		for child in args.work_dir.iterdir():
			if child.is_dir():
				for nested in child.iterdir():
					nested.unlink()
				child.rmdir()
			else:
				child.unlink()
	else:
		args.work_dir.mkdir(parents=True)

	result = {
		"source": {
			"name": "DLR/EOC Global SnowPack",
			"collection": "GSP_SCD_P1Y",
			"year": 2024,
			"url": SCD_URL,
			"nativeGrid": "EPSG:4326, 1/240 degree (~500 m)",
			"sourceNoDataMetadata": 0,
			"zeroPolicy": "Treat source value 0 as a valid snow-cover duration value inside Overture land polygons.",
		},
		"method": {
			"countryGeometry": "Overture Maps division_area with is_land = TRUE",
			"targetProjection": "EPSG:6933",
			"resampling": "average",
			"sourceNoDataOverride": "None",
			"outputNoData": -9999,
			"coarseResolutionM": 1000,
			"fineResolutionM": 500,
		},
		"countries": {},
	}

	for iso3 in DEFAULT_COUNTRIES:
		print(f"Aggregating {iso3} at 1000 m...", flush=True)
		entry = {
			"1000m": aggregate_country(features[iso3], iso3, 1000, args.work_dir),
		}
		if iso3 in DEFAULT_FINE_COUNTRIES:
			print(f"Aggregating {iso3} at 500 m...", flush=True)
			entry["500m"] = aggregate_country(features[iso3], iso3, 500, args.work_dir)
			coarse_mean = entry["1000m"].get("mean")
			fine_mean = entry["500m"].get("mean")
			if coarse_mean is not None and fine_mean is not None:
				entry["meanDifference1000mMinus500m"] = coarse_mean - fine_mean
		result["countries"][iso3] = entry
		print(f"  {iso3}: {entry}", flush=True)

	args.output.parent.mkdir(parents=True, exist_ok=True)
	args.output.write_text(
		json.dumps(result, ensure_ascii=False, indent="\t") + "\n",
		encoding="utf-8",
	)
	print(f"Wrote {args.output}", flush=True)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
