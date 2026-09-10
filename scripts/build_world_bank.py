#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "world-bank-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build normalized country statistics from World Bank World Development Indicators."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument(
		"--registry",
		default=DEFAULT_REGISTRY,
		help="Area-registry JSON URL or local path.",
	)
	parser.add_argument("--timeout", type=int, default=60)
	return parser.parse_args()


def utc_now() -> datetime:
	return datetime.now(timezone.utc)


def read_json_path(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def fetch_json(url: str, timeout: int) -> Any:
	delays = (0, 5, 15, 30, 60)
	last_error: Exception | None = None
	for attempt, delay in enumerate(delays, start=1):
		if delay:
			time.sleep(delay)
		request = Request(
			url,
			headers={
				"Accept": "application/json",
				"User-Agent": USER_AGENT,
			},
		)
		try:
			with urlopen(request, timeout=timeout) as response:
				return json.load(response)
		except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
			last_error = error
			print(f"Request failed ({attempt}/{len(delays)}): {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"Request failed without an exception: {url}")
	raise RuntimeError(f"Request failed after {len(delays)} attempts: {url}") from last_error


def load_json_source(source: str, timeout: int) -> Any:
	if source.startswith(("https://", "http://")):
		return fetch_json(source, timeout)
	return read_json_path(Path(source))


def validate_provider_catalog(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.statistics-providers/v1":
		raise ValueError("Invalid statistics provider catalog.")
	providers = payload.get("providers")
	if not isinstance(providers, list) or not providers:
		raise ValueError("Statistics provider catalog must contain at least one provider.")
	ids: set[str] = set()
	for provider in providers:
		if not isinstance(provider, dict):
			raise ValueError("Statistics provider entries must be objects.")
		provider_id = str(provider.get("id", "")).strip()
		name = str(provider.get("name", "")).strip()
		index = str(provider.get("index", "")).strip()
		if not provider_id or not name or not index:
			raise ValueError("Statistics provider entry requires id, name and index.")
		if provider_id in ids:
			raise ValueError(f"Duplicate statistics provider id: {provider_id}")
		ids.add(provider_id)
	return payload


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.world-bank-statistics/v1":
		raise ValueError("Invalid World Bank statistics config.")
	api_base = str(payload.get("apiBase", "")).strip().rstrip("/")
	source_id = payload.get("sourceId")
	provider = payload.get("provider")
	indicators = payload.get("indicators")
	fraction = payload.get("broadCoverageFraction")
	if not api_base.startswith("https://"):
		raise ValueError("World Bank apiBase must use HTTPS.")
	if not isinstance(source_id, int) or source_id <= 0:
		raise ValueError("World Bank sourceId must be a positive integer.")
	if not isinstance(provider, dict):
		raise ValueError("World Bank provider metadata is required.")
	for key in ("id", "name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"World Bank provider metadata is missing {key}.")
	if not isinstance(fraction, (int, float)) or not 0 < float(fraction) <= 1:
		raise ValueError("broadCoverageFraction must be greater than 0 and at most 1.")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("World Bank config requires at least one indicator.")

	ids: set[str] = set()
	slugs: set[str] = set()
	source_indicators: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("World Bank indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"World Bank indicator entry is missing {key}.")
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"Indicator {indicator.get('id')} has invalid unit metadata.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		source_indicator = str(indicator["sourceIndicator"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate indicator slug: {slug}")
		if source_indicator in source_indicators:
			raise ValueError(f"Duplicate World Bank indicator code: {source_indicator}")
		ids.add(indicator_id)
		slugs.add(slug)
		source_indicators.add(source_indicator)
		min_areas = indicator.get("minAreasWithAnyValue")
		max_age = indicator.get("maxDefaultYearAge")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(min_areas, int) or min_areas <= 0:
			raise ValueError(f"Indicator {indicator_id} has invalid minAreasWithAnyValue.")
		if not isinstance(max_age, int) or max_age < 0:
			raise ValueError(f"Indicator {indicator_id} has invalid maxDefaultYearAge.")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"Indicator {indicator_id} requires at least one required area.")
	return payload


def load_registry(source: str, timeout: int) -> tuple[dict[str, str], dict[str, Any]]:
	payload = load_json_source(source, timeout)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.area-registry/v1":
		raise ValueError("Invalid area registry.")
	areas = payload.get("areas")
	if not isinstance(areas, list) or not areas:
		raise ValueError("Area registry has no areas.")

	area_by_iso3: dict[str, str] = {}
	for area in areas:
		if not isinstance(area, dict) or area.get("level") != "country":
			continue
		area_id = str(area.get("area_id", "")).strip()
		codes = area.get("codes")
		if not isinstance(codes, dict):
			continue
		iso3 = str(codes.get("iso3", "")).strip().upper()
		if not area_id or len(iso3) != 3:
			continue
		if iso3 in area_by_iso3:
			raise ValueError(f"Duplicate ISO3 code in area registry: {iso3}")
		area_by_iso3[iso3] = area_id

	if len(area_by_iso3) < 240:
		raise RuntimeError(f"Area registry unexpectedly small: {len(area_by_iso3)} country areas.")
	for required in ("AUT", "DEU", "USA", "IND", "XKX"):
		if required not in area_by_iso3:
			raise RuntimeError(f"Area registry sanity check failed: {required} is missing.")
	return area_by_iso3, payload


def world_bank_payload(url: str, timeout: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
	payload = fetch_json(url, timeout)
	if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[0], dict):
		raise RuntimeError(f"Unexpected World Bank response shape: {url}")
	metadata = payload[0]
	records = payload[1]
	if records is None:
		records = []
	if not isinstance(records, list):
		raise RuntimeError(f"Unexpected World Bank records shape: {url}")
	return metadata, records


def fetch_world_bank_records(
	api_base: str,
	path: str,
	source_id: int,
	timeout: int,
) -> list[dict[str, Any]]:
	query = {
		"format": "json",
		"source": str(source_id),
		"per_page": "20000",
		"page": "1",
	}
	url = f"{api_base}/{path}?{urlencode(query)}"
	metadata, records = world_bank_payload(url, timeout)
	pages = int(metadata.get("pages", 1))
	if pages < 1:
		raise RuntimeError(f"World Bank returned invalid page count for {path}: {pages}")

	all_records = list(records)
	for page in range(2, pages + 1):
		query["page"] = str(page)
		page_url = f"{api_base}/{path}?{urlencode(query)}"
		page_metadata, page_records = world_bank_payload(page_url, timeout)
		if int(page_metadata.get("page", page)) != page:
			raise RuntimeError(f"World Bank pagination mismatch for {path}: expected page {page}.")
		all_records.extend(page_records)
	return all_records


def fetch_indicator_metadata(
	api_base: str,
	source_id: int,
	source_indicator: str,
	timeout: int,
) -> dict[str, Any]:
	records = fetch_world_bank_records(
		api_base,
		f"indicator/{source_indicator}",
		source_id,
		timeout,
	)
	if not records:
		raise RuntimeError(f"World Bank indicator metadata is missing: {source_indicator}")
	candidates = [
		record
		for record in records
		if str(record.get("id", "")).strip() == source_indicator
	]
	if len(candidates) != 1:
		raise RuntimeError(
			f"Expected one World Bank metadata record for {source_indicator}, found {len(candidates)}."
		)
	return candidates[0]


def normalize_number(value: Any) -> int | float:
	if isinstance(value, bool):
		raise ValueError("Boolean is not a numeric statistics value.")
	if isinstance(value, int):
		return value
	if isinstance(value, float):
		if not math.isfinite(value):
			raise ValueError("Statistics value is not finite.")
		return value
	if isinstance(value, str):
		number = float(value)
		if not math.isfinite(number):
			raise ValueError("Statistics value is not finite.")
		if number.is_integer():
			return int(number)
		return number
	raise ValueError(f"Unsupported statistics value type: {type(value).__name__}")


def normalize_indicator(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_iso3: dict[str, str],
	now: datetime,
	timeout: int,
) -> dict[str, Any]:
	api_base = str(config["apiBase"]).rstrip("/")
	source_id = int(config["sourceId"])
	provider = config["provider"]
	source_indicator = str(indicator["sourceIndicator"])

	print(f"Fetching {indicator['id']} ({source_indicator})")
	source_metadata = fetch_indicator_metadata(api_base, source_id, source_indicator, timeout)
	records = fetch_world_bank_records(
		api_base,
		f"country/all/indicator/{source_indicator}",
		source_id,
		timeout,
	)

	values_by_year: dict[int, dict[str, int | float]] = {}
	areas_with_any_value: set[str] = set()
	ignored_codes: set[str] = set()
	forecast_records = 0
	future_records = 0

	for record in records:
		value = record.get("value")
		if value is None:
			continue
		if str(record.get("obs_status", "")).strip().upper() == "F":
			forecast_records += 1
			continue
		iso3 = str(record.get("countryiso3code", "")).strip().upper()
		if iso3 not in area_by_iso3:
			if iso3:
				ignored_codes.add(iso3)
			continue
		raw_year = str(record.get("date", "")).strip()
		if len(raw_year) != 4 or not raw_year.isdigit():
			continue
		year = int(raw_year)
		if year > now.year:
			future_records += 1
			continue
		area_id = area_by_iso3[iso3]
		number = normalize_number(value)
		year_values = values_by_year.setdefault(year, {})
		if area_id in year_values:
			raise RuntimeError(f"Duplicate value for {indicator['id']} {year} {area_id}.")
		year_values[area_id] = number
		areas_with_any_value.add(area_id)

	if not values_by_year:
		raise RuntimeError(f"World Bank returned no mapped values for {indicator['id']}.")

	min_areas = int(indicator["minAreasWithAnyValue"])
	if len(areas_with_any_value) < min_areas:
		raise RuntimeError(
			f"Coverage too small for {indicator['id']}: "
			f"{len(areas_with_any_value)} areas, expected at least {min_areas}."
		)

	for area_id in indicator["requiredAreas"]:
		if area_id not in areas_with_any_value:
			raise RuntimeError(f"Required area {area_id} has no values for {indicator['id']}.")

	available_years = sorted(values_by_year)
	latest_year = available_years[-1]
	broad_fraction = float(config["broadCoverageFraction"])
	broad_threshold = max(1, math.ceil(len(areas_with_any_value) * broad_fraction))
	broad_years = [
		year
		for year in available_years
		if len(values_by_year[year]) >= broad_threshold
	]
	if not broad_years:
		raise RuntimeError(
			f"No year reaches broad coverage for {indicator['id']} "
			f"(threshold {broad_threshold} areas)."
		)
	default_year = broad_years[-1]
	max_age = int(indicator["maxDefaultYearAge"])
	if now.year - default_year > max_age:
		raise RuntimeError(
			f"Latest broadly covered year for {indicator['id']} is too old: "
			f"{default_year}, current year {now.year}, allowed age {max_age}."
		)

	sorted_values = {
		str(year): {
			area_id: values_by_year[year][area_id]
			for area_id in sorted(values_by_year[year])
		}
		for year in available_years
	}

	source_record = source_metadata.get("source")
	if not isinstance(source_record, dict):
		source_record = {}

	payload = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
		},
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"datasetId": str(source_id),
			"indicator": source_indicator,
			"indicatorName": source_metadata.get("name"),
			"sourceName": source_record.get("value"),
			"sourceNote": source_metadata.get("sourceNote"),
			"sourceOrganization": source_metadata.get("sourceOrganization"),
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": f"https://data.worldbank.org/indicator/{source_indicator}",
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": latest_year,
			"areasInLatestYear": len(values_by_year[latest_year]),
			"broadCoverageThreshold": broad_threshold,
			"areasInDefaultYear": len(values_by_year[default_year]),
		},
		"values": sorted_values,
	}

	print(
		f"  mapped={len(areas_with_any_value)} "
		f"years={available_years[0]}-{latest_year} "
		f"defaultYear={default_year} "
		f"defaultCoverage={len(values_by_year[default_year])} "
		f"ignoredCodes={len(ignored_codes)} "
		f"forecastsSkipped={forecast_records} "
		f"futureSkipped={future_records}"
	)
	return payload


def canonical_bytes(payload: Any) -> bytes:
	return json.dumps(
		payload,
		ensure_ascii=False,
		sort_keys=True,
		separators=(",", ":"),
	).encode("utf-8")


def write_json(path: Path, payload: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		json.dumps(payload, ensure_ascii=False, indent="\t") + "\n",
		encoding="utf-8",
	)


def build_global_index(provider_catalog: dict[str, Any]) -> dict[str, Any]:
	return {
		"schema": "kartensammlung.statistics-index/v1",
		"areaRegistry": "../area-registry-countries.json",
		"providers": provider_catalog["providers"],
	}


def main() -> None:
	args = parse_args()
	config = validate_config(read_json_path(args.config))
	provider_catalog = validate_provider_catalog(read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = load_registry(args.registry, args.timeout)
	now = utc_now()
	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []

	for indicator in config["indicators"]:
		payload = normalize_indicator(config, indicator, area_by_iso3, now, args.timeout)
		indicator_payloads.append((indicator, payload))

	hasher = hashlib.sha256()
	for indicator, payload in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	output_dir = args.output_dir
	provider_dir = output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot

	index_indicators = []
	for indicator, payload in indicator_payloads:
		filename = f"{indicator['slug']}.json"
		write_json(release_dir / filename, payload)
		index_indicators.append(
			{
				"id": indicator["id"],
				"title": indicator["title"],
				"description": indicator["description"],
				"areaLevel": "country",
				"frequency": "annual",
				"unit": indicator["unit"],
				"sourceIndicator": indicator["sourceIndicator"],
				"path": f"releases/{snapshot}/{filename}",
				"availableYears": payload["availableYears"],
				"defaultYear": payload["defaultYear"],
				"coverage": payload["coverage"],
			}
		)

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
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
		"indicators": index_indicators,
	}
	write_json(provider_dir / "index.json", provider_index)
	write_json(output_dir / "index.json", build_global_index(provider_catalog))

	print(f"Built World Bank snapshot {snapshot}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
