#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "un-wpp-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized country statistics from UN DESA World Population Prospects.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=90)
	return parser.parse_args()


def read_json(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def fetch_json(source: str, timeout: int) -> Any:
	if not source.startswith(("https://", "http://")):
		return read_json(Path(source))
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 5, 15, 30, 60), start=1):
		if delay:
			time.sleep(delay)
		try:
			request = Request(source, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
			with urlopen(request, timeout=timeout) as response:
				return json.load(response)
		except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
			last_error = error
			print(f"Request failed ({attempt}/5): {source}: {error}")
	raise RuntimeError(f"Request failed after 5 attempts: {source}") from last_error


def download(url: str, timeout: int) -> Path:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 5, 15, 30, 60), start=1):
		if delay:
			time.sleep(delay)
		handle = tempfile.NamedTemporaryFile(prefix="wpp-", suffix=".csv.gz", delete=False)
		path = Path(handle.name)
		handle.close()
		try:
			request = Request(url, headers={"Accept": "application/gzip, application/octet-stream, */*", "User-Agent": USER_AGENT})
			with urlopen(request, timeout=timeout) as response, path.open("wb") as output:
				shutil.copyfileobj(response, output, length=1024 * 1024)
			if path.stat().st_size < 1024:
				raise RuntimeError(f"Downloaded file is unexpectedly small: {path.stat().st_size} bytes")
			return path
		except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
			last_error = error
			path.unlink(missing_ok=True)
			print(f"Download failed ({attempt}/5): {url}: {error}")
	raise RuntimeError(f"Download failed after 5 attempts: {url}") from last_error


def validate_classification(indicator: dict[str, Any]) -> None:
	indicator_id = str(indicator["id"])
	classification = indicator.get("classification")
	if not isinstance(classification, dict) or classification.get("type") != "fixed":
		raise ValueError(f"Indicator {indicator_id} requires fixed classification metadata.")
	scale = str(classification.get("scale", "linear"))
	if scale not in ("linear", "logarithmic"):
		raise ValueError(f"Indicator {indicator_id} has invalid classification scale: {scale}.")
	breaks = classification.get("breaks")
	if not isinstance(breaks, list) or len(breaks) != 6:
		raise ValueError(f"Indicator {indicator_id} requires exactly 6 classification breaks.")
	numbers = [float(value) for value in breaks]
	if not all(math.isfinite(value) for value in numbers):
		raise ValueError(f"Indicator {indicator_id} has non-finite classification breaks.")
	if any(numbers[index] <= numbers[index - 1] for index in range(1, 6)):
		raise ValueError(f"Indicator {indicator_id} classification breaks must be strictly ascending.")
	if scale == "logarithmic" and numbers[0] <= 0:
		raise ValueError(f"Indicator {indicator_id} logarithmic classification requires positive breaks.")


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.un-wpp-statistics/v1":
		raise ValueError("Invalid UN WPP statistics config.")
	if not str(payload.get("downloadUrl", "")).startswith("https://"):
		raise ValueError("UN WPP downloadUrl must use HTTPS.")
	if not isinstance(payload.get("estimateEndYear"), int):
		raise ValueError("UN WPP estimateEndYear is invalid.")
	fraction = payload.get("broadCoverageFraction")
	if not isinstance(fraction, (int, float)) or not 0 < float(fraction) <= 1:
		raise ValueError("broadCoverageFraction must be greater than 0 and at most 1.")
	provider = payload.get("provider")
	if not isinstance(provider, dict):
		raise ValueError("UN WPP provider metadata is required.")
	for key in ("id", "name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"UN WPP provider metadata is missing {key}.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("UN WPP config requires indicators.")
	if not isinstance(payload.get("requiredAreas"), list) or not payload["requiredAreas"]:
		raise ValueError("UN WPP config requires requiredAreas.")
	ids: set[str] = set()
	slugs: set[str] = set()
	columns: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("UN WPP indicator entries must be objects.")
		for key in ("id", "slug", "sourceColumn", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"UN WPP indicator entry is missing {key}.")
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not unit.get("id") or not unit.get("label"):
			raise ValueError(f"Indicator {indicator['id']} has invalid unit metadata.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		column = str(indicator["sourceColumn"])
		if indicator_id in ids or slug in slugs or column in columns:
			raise ValueError(f"Duplicate UN WPP indicator id, slug or source column: {indicator_id}.")
		ids.add(indicator_id)
		slugs.add(slug)
		columns.add(column)
		if not isinstance(indicator.get("minAreasWithAnyValue"), int) or indicator["minAreasWithAnyValue"] <= 0:
			raise ValueError(f"Indicator {indicator_id} has invalid minAreasWithAnyValue.")
		validate_classification(indicator)
	return payload


def validate_provider_catalog(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.statistics-providers/v1":
		raise ValueError("Invalid statistics provider catalog.")
	providers = payload.get("providers")
	if not isinstance(providers, list) or not providers:
		raise ValueError("Statistics provider catalog is empty.")
	ids = [str(provider.get("id", "")) for provider in providers if isinstance(provider, dict)]
	if len(ids) != len(set(ids)):
		raise ValueError("Duplicate statistics provider id.")
	return payload


def load_registry(source: str, timeout: int) -> tuple[dict[str, str], dict[str, Any]]:
	payload = fetch_json(source, timeout)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.area-registry/v1":
		raise ValueError("Invalid area registry.")
	areas = payload.get("areas")
	if not isinstance(areas, list):
		raise ValueError("Area registry has no areas.")
	area_by_iso3: dict[str, str] = {}
	for area in areas:
		if not isinstance(area, dict) or area.get("level") != "country":
			continue
		codes = area.get("codes")
		if not isinstance(codes, dict):
			continue
		iso3 = str(codes.get("iso3", "")).strip().upper()
		area_id = str(area.get("area_id", "")).strip()
		if len(iso3) != 3 or not area_id:
			continue
		if iso3 in area_by_iso3:
			raise ValueError(f"Duplicate ISO3 in area registry: {iso3}")
		area_by_iso3[iso3] = area_id
	if len(area_by_iso3) < 240:
		raise RuntimeError(f"Area registry unexpectedly small: {len(area_by_iso3)} country areas.")
	for iso3 in ("AUT", "DEU", "USA", "IND", "XKX"):
		if iso3 not in area_by_iso3:
			raise RuntimeError(f"Area registry sanity check failed: {iso3} is missing.")
	return area_by_iso3, payload


def normalize_value(raw: str, indicator: dict[str, Any]) -> int | float | None:
	text = raw.strip()
	if not text or text in ("..", "..."):
		return None
	value = float(text)
	if not math.isfinite(value):
		raise ValueError(f"Non-finite value for {indicator['sourceColumn']}: {raw!r}")
	transform = indicator.get("transform") or {}
	value *= float(transform.get("multiplier", 1))
	if "round" in transform:
		value = round(value, int(transform["round"]))
	if value == 0:
		value = 0.0
	return int(value) if value.is_integer() else value


def read_wpp(path: Path, config: dict[str, Any], area_by_iso3: dict[str, str]) -> tuple[dict[str, dict[int, dict[str, int | float]]], set[str]]:
	indicators = config["indicators"]
	values = {str(indicator["id"]): {} for indicator in indicators}
	ignored_codes: set[str] = set()
	required_columns = {"ISO3_code", "Time", *(str(indicator["sourceColumn"]) for indicator in indicators)}
	with gzip.open(path, "rb") as compressed, io.TextIOWrapper(compressed, encoding="utf-8-sig", newline="") as text:
		reader = csv.DictReader(text)
		missing = sorted(required_columns - set(reader.fieldnames or []))
		if missing:
			raise RuntimeError(f"UN WPP CSV is missing required columns: {', '.join(missing)}")
		for row in reader:
			iso3 = str(row.get("ISO3_code", "")).strip().upper()
			if iso3 not in area_by_iso3:
				if iso3:
					ignored_codes.add(iso3)
				continue
			raw_year = str(row.get("Time", "")).strip()
			if len(raw_year) != 4 or not raw_year.isdigit():
				continue
			year = int(raw_year)
			area_id = area_by_iso3[iso3]
			for indicator in indicators:
				value = normalize_value(str(row.get(indicator["sourceColumn"], "")), indicator)
				if value is None:
					continue
				year_values = values[str(indicator["id"])].setdefault(year, {})
				if area_id in year_values:
					raise RuntimeError(f"Duplicate UN WPP value for {indicator['id']} {year} {area_id}.")
				year_values[area_id] = value
	return values, ignored_codes


def build_indicator(config: dict[str, Any], indicator: dict[str, Any], values_by_year: dict[int, dict[str, int | float]], area_count: int, now: datetime) -> dict[str, Any]:
	indicator_id = str(indicator["id"])
	areas = {area_id for year_values in values_by_year.values() for area_id in year_values}
	if len(areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(f"Coverage too small for {indicator_id}: {len(areas)} areas.")
	for area_id in config["requiredAreas"]:
		if area_id not in areas:
			raise RuntimeError(f"Required area {area_id} has no values for {indicator_id}.")
	available_years = sorted(values_by_year)
	if not available_years:
		raise RuntimeError(f"UN WPP returned no mapped values for {indicator_id}.")
	estimate_end_year = int(config["estimateEndYear"])
	broad_threshold = max(1, math.ceil(len(areas) * float(config["broadCoverageFraction"])))
	broad_estimates = [year for year in available_years if year <= estimate_end_year and len(values_by_year[year]) >= broad_threshold]
	if not broad_estimates:
		raise RuntimeError(f"No estimate year reaches broad coverage for {indicator_id}.")
	default_year = broad_estimates[-1]
	if now.year - default_year > 5:
		raise RuntimeError(f"Latest broadly covered estimate year for {indicator_id} is unexpectedly old: {default_year}.")
	latest_year = available_years[-1]
	projection = {"startYear": estimate_end_year + 1, "endYear": latest_year, "variant": config["projectionVariant"]}
	provider = config["provider"]
	return {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": {
			"id": indicator_id,
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"projection": projection,
		},
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"datasetId": f"WPP{config['revision']}",
			"indicator": indicator["sourceColumn"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": "https://population.un.org/wpp/",
			"downloadUrl": config["downloadUrl"],
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": area_count,
			"areasWithAnyValue": len(areas),
			"latestYear": latest_year,
			"areasInLatestYear": len(values_by_year[latest_year]),
			"latestEstimateYear": default_year,
			"areasInLatestEstimateYear": len(values_by_year[default_year]),
			"broadCoverageThreshold": broad_threshold,
			"areasInDefaultYear": len(values_by_year[default_year]),
		},
		"values": {str(year): {area_id: values_by_year[year][area_id] for area_id in sorted(values_by_year[year])} for year in available_years},
	}


def canonical_bytes(payload: Any) -> bytes:
	return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_json(path: Path, payload: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")


def main() -> None:
	args = parse_args()
	config = validate_config(read_json(args.config))
	provider_catalog = validate_provider_catalog(read_json(args.providers))
	provider = config["provider"]
	if not any(item.get("id") == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")
	area_by_iso3, registry = load_registry(args.registry, args.timeout)
	now = datetime.now(timezone.utc)
	print(f"Downloading {provider['dataset']}")
	path = download(str(config["downloadUrl"]), args.timeout)
	try:
		print(f"Downloaded {path.stat().st_size} bytes")
		all_values, ignored_codes = read_wpp(path, config, area_by_iso3)
	finally:
		path.unlink(missing_ok=True)
	payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload = build_indicator(config, indicator, all_values[str(indicator["id"])], len(area_by_iso3), now)
		payloads.append((indicator, payload))
		coverage = payload["coverage"]
		print(f"{indicator['id']}: mapped={coverage['areasWithAnyValue']} years={payload['availableYears'][0]}-{payload['availableYears'][-1]} defaultYear={payload['defaultYear']} defaultCoverage={coverage['areasInDefaultYear']}")
	hasher = hashlib.sha256()
	for indicator, payload in sorted(payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8") + b"\0" + canonical_bytes(payload) + b"\0")
	snapshot = hasher.hexdigest()[:16]
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators = []
	for indicator, payload in payloads:
		filename = f"{indicator['slug']}.json"
		write_json(release_dir / filename, payload)
		index_indicators.append({
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"projection": payload["indicator"]["projection"],
			"sourceIndicator": indicator["sourceColumn"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		})
	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry.get("schema"),
		"generatedAt": registry.get("generatedAt"),
		"areaCount": len(area_by_iso3),
	}
	if registry_source["url"] is None:
		registry_source.pop("url")
	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"dataset": {
			"revision": config["revision"],
			"estimateEndYear": config["estimateEndYear"],
			"projectionVariant": config["projectionVariant"],
			"projectionEndYear": max(payload["availableYears"][-1] for _, payload in payloads),
		},
		"ignoredIso3Codes": sorted(ignored_codes),
		"indicators": index_indicators,
	}
	write_json(provider_dir / "index.json", provider_index)
	write_json(args.output_dir / "index.json", {
		"schema": "kartensammlung.statistics-index/v1",
		"areaRegistry": "../area-registry-countries.json",
		"providers": provider_catalog["providers"],
	})
	print(f"Built UN WPP snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")
	print(f"Ignored ISO3 codes: {', '.join(sorted(ignored_codes)) or '(none)'}")


if __name__ == "__main__":
	main()
