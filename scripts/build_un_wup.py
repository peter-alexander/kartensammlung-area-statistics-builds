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

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "un-wup-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
REQUIRED_COLUMNS = {
	"LocID",
	"Index",
	"Location",
	"Notes",
	"ISO3_Code",
	"ISO2_Code",
	"SDMX_Code",
	"LocType",
	"LocTypeName",
	"ParentID",
	"Category_order",
	"Category",
	"Year",
	"Pop1Jan",
	"Perc1Jan",
	"TimeMid",
	"Pop",
	"percPop",
	"Pop_rate",
	"percPop_rate",
}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized country urbanization statistics from UN DESA World Urbanization Prospects.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=90)
	return parser.parse_args()


def read_json(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def validate_classification(indicator: dict[str, Any]) -> None:
	indicator_id = str(indicator["id"])
	classification = indicator.get("classification")
	if not isinstance(classification, dict) or classification.get("type") != "fixed":
		raise ValueError(f"Indicator {indicator_id} requires fixed classification metadata.")
	breaks = classification.get("breaks")
	if not isinstance(breaks, list) or len(breaks) != 6:
		raise ValueError(f"Indicator {indicator_id} requires exactly 6 classification breaks.")
	numbers = [float(value) for value in breaks]
	if not all(math.isfinite(value) for value in numbers):
		raise ValueError(f"Indicator {indicator_id} has non-finite classification breaks.")
	if any(numbers[index] <= numbers[index - 1] for index in range(1, len(numbers))):
		raise ValueError(f"Indicator {indicator_id} classification breaks must be strictly ascending.")


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.un-wup-statistics/v1":
		raise ValueError("Invalid UN WUP statistics config.")
	if not str(payload.get("downloadUrl", "")).startswith("https://population.un.org/wup/"):
		raise ValueError("UN WUP downloadUrl must use the official population.un.org/wup HTTPS origin.")
	if payload.get("revision") != "2025":
		raise ValueError("UN WUP revision must be 2025.")
	if payload.get("estimateEndYear") != 2025:
		raise ValueError("UN WUP estimateEndYear must be 2025.")
	fraction = payload.get("broadCoverageFraction")
	if not isinstance(fraction, (int, float)) or not 0 < float(fraction) <= 1:
		raise ValueError("broadCoverageFraction must be greater than 0 and at most 1.")
	provider = payload.get("provider")
	if not isinstance(provider, dict):
		raise ValueError("UN WUP provider metadata is required.")
	for key in ("id", "name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"UN WUP provider metadata is missing {key}.")
	if provider.get("id") != "un-wup":
		raise ValueError("UN WUP provider id must be un-wup.")
	if provider.get("license") != "CC BY 3.0 IGO":
		raise ValueError("UN WUP license metadata must be CC BY 3.0 IGO.")
	invariants = payload.get("sourceInvariants")
	if not isinstance(invariants, dict):
		raise ValueError("UN WUP sourceInvariants are required.")
	expected_invariants = {
		"locationType": "Country/Area",
		"category": "Urban",
		"valueColumn": "percPop",
		"timeReference": "Mid-Year",
		"minimumSourceCountryAreas": 230,
		"minimumSourceStartYear": 1950,
		"sourceProjectionEndYear": 2050,
	}
	if invariants != expected_invariants:
		raise ValueError("Unexpected UN WUP source invariants.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 1:
		raise ValueError("UN WUP config currently requires exactly one indicator.")
	indicator = indicators[0]
	if not isinstance(indicator, dict):
		raise ValueError("UN WUP indicator must be an object.")
	for key in ("id", "slug", "sourceIndicator", "title", "description"):
		if not str(indicator.get(key, "")).strip():
			raise ValueError(f"UN WUP indicator is missing {key}.")
	if indicator["id"] != "urban-population.percent" or indicator["sourceIndicator"] != "percPop":
		raise ValueError("Unexpected UN WUP urbanization indicator identity.")
	unit = indicator.get("unit")
	if not isinstance(unit, dict) or unit.get("id") != "percent":
		raise ValueError("UN WUP urbanization requires percent unit metadata.")
	for key in ("minAreasWithAnyValue", "minAreasInDefaultYear", "minimumDefaultYear", "minimumLatestYear"):
		if not isinstance(indicator.get(key), int) or int(indicator[key]) <= 0:
			raise ValueError(f"UN WUP indicator has invalid {key}.")
	validate_classification(indicator)
	required_areas = payload.get("requiredAreas")
	if not isinstance(required_areas, list) or not required_areas:
		raise ValueError("UN WUP config requires requiredAreas.")
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


def download(url: str, timeout: int) -> tuple[Path, dict[str, Any]]:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 5, 15, 30, 60), start=1):
		if delay:
			time.sleep(delay)
		handle = tempfile.NamedTemporaryFile(prefix="wup-", suffix=".csv.gz", delete=False)
		path = Path(handle.name)
		handle.close()
		try:
			request = Request(url, headers={"Accept": "application/gzip, application/octet-stream, */*", "User-Agent": USER_AGENT})
			with urlopen(request, timeout=timeout) as response, path.open("wb") as output:
				last_modified = response.headers.get("Last-Modified")
				shutil.copyfileobj(response, output, length=1024 * 1024)
			size = path.stat().st_size
			if size < 1000000:
				raise RuntimeError(f"Downloaded UN WUP file is unexpectedly small: {size} bytes")
			return path, {"bytes": size, "lastModified": last_modified}
		except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
			last_error = error
			path.unlink(missing_ok=True)
			print(f"Download failed ({attempt}/5): {url}: {error}")
	if last_error is None:
		raise RuntimeError("UN WUP download failed without exception.")
	raise RuntimeError(f"Download failed after 5 attempts: {url}") from last_error


def read_wup(
	path: Path,
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
) -> tuple[dict[int, dict[str, int | float]], dict[str, Any]]:
	invariants = config["sourceInvariants"]
	estimate_end_year = int(config["estimateEndYear"])
	values_by_year: dict[int, dict[str, int | float]] = {}
	source_country_areas: set[str] = set()
	mapped_source_areas: set[str] = set()
	ignored_codes: set[str] = set()
	categories: set[str] = set()
	source_years: set[int] = set()
	row_count = 0
	country_urban_rows = 0
	projection_rows_skipped = 0

	with gzip.open(path, "rb") as compressed, io.TextIOWrapper(compressed, encoding="utf-8-sig", newline="") as text:
		reader = csv.DictReader(text)
		fields = set(reader.fieldnames or [])
		missing = sorted(REQUIRED_COLUMNS - fields)
		if missing:
			raise RuntimeError(f"UN WUP CSV is missing required columns: {', '.join(missing)}")
		for row in reader:
			row_count += 1
			category = str(row.get("Category", "")).strip()
			if category:
				categories.add(category)
			if str(row.get("LocTypeName", "")).strip() != invariants["locationType"]:
				continue
			iso3 = str(row.get("ISO3_Code", "")).strip().upper()
			if iso3:
				source_country_areas.add(iso3)
			if category != invariants["category"]:
				continue
			country_urban_rows += 1
			raw_year = str(row.get("Year", "")).strip()
			if len(raw_year) != 4 or not raw_year.isdigit():
				raise RuntimeError(f"Invalid UN WUP year in country urban row: {raw_year!r}")
			year = int(raw_year)
			source_years.add(year)
			if year > estimate_end_year:
				projection_rows_skipped += 1
				continue
			if iso3 not in area_by_iso3:
				if iso3:
					ignored_codes.add(iso3)
				continue
			raw_value = str(row.get(invariants["valueColumn"], "")).strip()
			if not raw_value:
				continue
			value = float(raw_value)
			if not math.isfinite(value) or value < 0 or value > 100:
				raise RuntimeError(f"Invalid UN WUP urban percentage for {iso3} {year}: {raw_value!r}")
			area_id = area_by_iso3[iso3]
			year_values = values_by_year.setdefault(year, {})
			if area_id in year_values:
				raise RuntimeError(f"Duplicate UN WUP value for {year} {area_id}.")
			year_values[area_id] = int(value) if value.is_integer() else value
			mapped_source_areas.add(area_id)

	if not {"Rural", "Urban", "Total"}.issubset(categories):
		raise RuntimeError(f"Unexpected UN WUP categories: {sorted(categories)}")
	if len(source_country_areas) < int(invariants["minimumSourceCountryAreas"]):
		raise RuntimeError(f"UN WUP source country coverage unexpectedly small: {len(source_country_areas)}.")
	if not source_years or min(source_years) > int(invariants["minimumSourceStartYear"]):
		raise RuntimeError(f"UN WUP source starts unexpectedly late: {min(source_years) if source_years else 'none'}.")
	if max(source_years) != int(invariants["sourceProjectionEndYear"]):
		raise RuntimeError(f"UN WUP source projection end year changed: {max(source_years)}.")
	if projection_rows_skipped <= 0:
		raise RuntimeError("UN WUP projection filter did not skip any rows.")
	if ignored_codes:
		raise RuntimeError(f"UN WUP contains country ISO3 codes missing from registry: {', '.join(sorted(ignored_codes))}")
	if any(year > estimate_end_year for year in values_by_year):
		raise RuntimeError("UN WUP output contains projection years.")

	return values_by_year, {
		"rows": row_count,
		"sourceCountryAreas": len(source_country_areas),
		"mappedSourceAreas": len(mapped_source_areas),
		"sourceStartYear": min(source_years),
		"sourceEndYear": max(source_years),
		"countryUrbanRows": country_urban_rows,
		"projectionRowsSkipped": projection_rows_skipped,
		"categories": sorted(categories),
		"ignoredIso3Codes": sorted(ignored_codes),
	}


def build_indicator(
	config: dict[str, Any],
	indicator: dict[str, Any],
	values_by_year: dict[int, dict[str, int | float]],
	area_count: int,
) -> dict[str, Any]:
	areas = {area_id for year_values in values_by_year.values() for area_id in year_values}
	if len(areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(f"Coverage too small for {indicator['id']}: {len(areas)} areas.")
	for area_id in config["requiredAreas"]:
		if area_id not in areas:
			raise RuntimeError(f"Required area {area_id} has no UN WUP values.")
	available_years = sorted(values_by_year)
	if not available_years:
		raise RuntimeError("UN WUP returned no mapped urbanization values.")
	if available_years[-1] > int(config["estimateEndYear"]):
		raise RuntimeError("UN WUP availableYears contains projections.")
	broad_threshold = max(1, math.ceil(len(areas) * float(config["broadCoverageFraction"])))
	broad_years = [year for year in available_years if len(values_by_year[year]) >= broad_threshold]
	if not broad_years:
		raise RuntimeError("No UN WUP year reaches broad coverage.")
	default_year = broad_years[-1]
	if default_year < int(indicator["minimumDefaultYear"]):
		raise RuntimeError(f"UN WUP default year too old: {default_year}.")
	latest_year = available_years[-1]
	if latest_year < int(indicator["minimumLatestYear"]):
		raise RuntimeError(f"UN WUP latest year too old: {latest_year}.")
	if len(values_by_year[default_year]) < int(indicator["minAreasInDefaultYear"]):
		raise RuntimeError(f"UN WUP default-year coverage too small: {len(values_by_year[default_year])}.")
	provider = config["provider"]
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
			"datasetId": f"WUP{config['revision']}",
			"indicator": indicator["sourceIndicator"],
			"definition": "Urban population as a percentage of total population, using each country or area's national urban definition.",
			"filters": {
				"LocTypeName": config["sourceInvariants"]["locationType"],
				"Category": config["sourceInvariants"]["category"],
				"maximumYear": config["estimateEndYear"],
				"valueColumn": config["sourceInvariants"]["valueColumn"],
			},
			"sourceInvariants": config["sourceInvariants"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": "https://population.un.org/wup/",
			"downloadUrl": config["downloadUrl"],
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": area_count,
			"areasWithAnyValue": len(areas),
			"latestYear": latest_year,
			"areasInLatestYear": len(values_by_year[latest_year]),
			"broadCoverageThreshold": broad_threshold,
			"areasInDefaultYear": len(values_by_year[default_year]),
			"observations": sum(len(year_values) for year_values in values_by_year.values()),
		},
		"values": {
			str(year): {area_id: values_by_year[year][area_id] for area_id in sorted(values_by_year[year])}
			for year in available_years
		},
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
	area_by_iso3, registry = common.load_registry(args.registry, args.timeout)
	now = datetime.now(timezone.utc)
	print(f"Downloading {provider['dataset']}")
	path, download_metadata = download(str(config["downloadUrl"]), args.timeout)
	try:
		values_by_year, dataset_metadata = read_wup(path, config, area_by_iso3)
	finally:
		path.unlink(missing_ok=True)

	indicator = config["indicators"][0]
	payload = build_indicator(config, indicator, values_by_year, len(area_by_iso3))
	coverage = payload["coverage"]
	print(
		f"{indicator['id']}: observations={coverage['observations']} areas={coverage['areasWithAnyValue']} "
		f"years={payload['availableYears'][0]}-{payload['availableYears'][-1]} "
		f"defaultYear={payload['defaultYear']} defaultCoverage={coverage['areasInDefaultYear']} "
		f"projectionsSkipped={dataset_metadata['projectionRowsSkipped']}"
	)

	hasher = hashlib.sha256()
	hasher.update(str(indicator["id"]).encode("utf-8") + b"\0" + canonical_bytes(payload) + b"\0")
	snapshot = hasher.hexdigest()[:16]
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	filename = f"{indicator['slug']}.json"
	write_json(release_dir / filename, payload)

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
			"downloadUrl": config["downloadUrl"],
			"bytes": download_metadata["bytes"],
			"lastModified": download_metadata["lastModified"],
			**dataset_metadata,
		},
		"indicators": [{
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"sourceIndicator": indicator["sourceIndicator"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		}],
	}
	write_json(provider_dir / "index.json", provider_index)
	write_json(args.output_dir / "index.json", {
		"schema": "kartensammlung.statistics-index/v1",
		"areaRegistry": "../area-registry-countries.json",
		"providers": provider_catalog["providers"],
	})
	print(f"Built UN WUP snapshot {snapshot}")
	print(f"Dataset rows: {dataset_metadata['rows']}; source country areas: {dataset_metadata['sourceCountryAreas']}")


if __name__ == "__main__":
	main()
