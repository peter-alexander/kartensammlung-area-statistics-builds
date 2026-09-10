#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "eurostat-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
SEMESTER_RE = re.compile(r"^(\d{4})-?S([12])$")
YEAR_RE = re.compile(r"^\d{4}$")


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build normalized country statistics from Eurostat JSON-stat datasets."
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


def validate_classification(indicator_id: str, classification: Any) -> None:
	if classification is None:
		return
	if not isinstance(classification, dict):
		raise ValueError(f"Indicator {indicator_id} has invalid classification metadata.")

	classification_type = str(classification.get("type", "")).strip()
	if classification_type != "fixed":
		raise ValueError(
			f"Indicator {indicator_id} uses unsupported classification type: {classification_type or '(empty)'}."
		)

	scale = str(classification.get("scale", "linear")).strip()
	if scale not in ("linear", "logarithmic"):
		raise ValueError(f"Indicator {indicator_id} has invalid classification scale: {scale}.")

	breaks = classification.get("breaks")
	if not isinstance(breaks, list) or len(breaks) != 6:
		raise ValueError(f"Indicator {indicator_id} fixed classification requires exactly 6 breaks.")

	normalized_breaks: list[float] = []
	for value in breaks:
		if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
			raise ValueError(f"Indicator {indicator_id} has a non-numeric classification break.")
		normalized_breaks.append(float(value))

	if any(value <= normalized_breaks[index - 1] for index, value in enumerate(normalized_breaks) if index > 0):
		raise ValueError(f"Indicator {indicator_id} classification breaks must be strictly ascending.")
	if scale == "logarithmic" and normalized_breaks[0] <= 0:
		raise ValueError(f"Indicator {indicator_id} logarithmic classification breaks must be positive.")


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.eurostat-statistics/v1":
		raise ValueError("Invalid Eurostat statistics config.")
	api_base = str(payload.get("apiBase", "")).strip().rstrip("/")
	provider = payload.get("provider")
	indicators = payload.get("indicators")
	fraction = payload.get("broadCoverageFraction")
	aliases = payload.get("geoAliases", {})
	if not api_base.startswith("https://ec.europa.eu/eurostat/api/"):
		raise ValueError("Eurostat apiBase must use the official HTTPS Eurostat API.")
	if not isinstance(provider, dict):
		raise ValueError("Eurostat provider metadata is required.")
	for key in ("id", "name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"Eurostat provider metadata is missing {key}.")
	if not isinstance(fraction, (int, float)) or not 0 < float(fraction) <= 1:
		raise ValueError("broadCoverageFraction must be greater than 0 and at most 1.")
	if not isinstance(aliases, dict):
		raise ValueError("geoAliases must be an object.")
	for source, target in aliases.items():
		if len(str(source).strip()) != 2 or len(str(target).strip()) != 2:
			raise ValueError("Eurostat geoAliases must map two-character country codes.")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("Eurostat config requires at least one indicator.")

	ids: set[str] = set()
	slugs: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("Eurostat indicator entries must be objects.")
		for key in ("id", "slug", "dataset", "title", "description", "timeMode"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"Eurostat indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate indicator slug: {slug}")
		ids.add(indicator_id)
		slugs.add(slug)
		validate_classification(indicator_id, indicator.get("classification"))
		if indicator["timeMode"] not in ("annual", "latest-semester-per-year"):
			raise ValueError(f"Unsupported timeMode for {indicator_id}: {indicator['timeMode']}")
		filters = indicator.get("filters")
		if not isinstance(filters, dict) or not filters:
			raise ValueError(f"Indicator {indicator_id} requires filters.")
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"Indicator {indicator_id} has invalid unit metadata.")
		min_areas = indicator.get("minAreasWithAnyValue")
		max_age = indicator.get("maxDefaultYearAge")
		required_areas = indicator.get("requiredAreas")
		excluded_geos = indicator.get("excludedGeos", [])
		if not isinstance(min_areas, int) or min_areas <= 0:
			raise ValueError(f"Indicator {indicator_id} has invalid minAreasWithAnyValue.")
		if not isinstance(max_age, int) or max_age < 0:
			raise ValueError(f"Indicator {indicator_id} has invalid maxDefaultYearAge.")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"Indicator {indicator_id} requires at least one required area.")
		if not isinstance(excluded_geos, list):
			raise ValueError(f"Indicator {indicator_id} has invalid excludedGeos.")
	return payload


def load_registry(source: str, timeout: int) -> tuple[dict[str, str], dict[str, Any]]:
	payload = load_json_source(source, timeout)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.area-registry/v1":
		raise ValueError("Invalid area registry.")
	areas = payload.get("areas")
	if not isinstance(areas, list) or not areas:
		raise ValueError("Area registry has no areas.")

	area_by_iso2: dict[str, str] = {}
	for area in areas:
		if not isinstance(area, dict) or area.get("level") != "country":
			continue
		area_id = str(area.get("area_id", "")).strip()
		codes = area.get("codes")
		if not isinstance(codes, dict):
			continue
		iso2 = str(codes.get("iso2", "")).strip().upper()
		if not area_id or len(iso2) != 2:
			continue
		if iso2 in area_by_iso2:
			raise ValueError(f"Duplicate ISO2 code in area registry: {iso2}")
		area_by_iso2[iso2] = area_id

	if len(area_by_iso2) < 240:
		raise RuntimeError(f"Area registry unexpectedly small: {len(area_by_iso2)} country areas.")
	for required in ("AT", "DE", "US", "IN", "XK"):
		if required not in area_by_iso2:
			raise RuntimeError(f"Area registry sanity check failed: {required} is missing.")
	return area_by_iso2, payload


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


def category_codes(payload: dict[str, Any], dimension_id: str, expected_size: int) -> list[str]:
	dimension = payload.get("dimension")
	if not isinstance(dimension, dict) or dimension_id not in dimension:
		raise RuntimeError(f"Eurostat response is missing dimension {dimension_id}.")
	entry = dimension[dimension_id]
	category = entry.get("category") if isinstance(entry, dict) else None
	index = category.get("index") if isinstance(category, dict) else None
	if isinstance(index, list):
		codes = [str(code) for code in index]
	elif isinstance(index, dict):
		pairs = []
		for code, position in index.items():
			if not isinstance(position, int):
				raise RuntimeError(f"Invalid category position for {dimension_id}:{code}")
			pairs.append((position, str(code)))
		pairs.sort()
		codes = [code for _, code in pairs]
	else:
		raise RuntimeError(f"Eurostat response has invalid category index for {dimension_id}.")
	if len(codes) != expected_size:
		raise RuntimeError(
			f"Eurostat dimension size mismatch for {dimension_id}: {len(codes)} != {expected_size}."
		)
	return codes


def iter_jsonstat_observations(payload: Any) -> Iterator[dict[str, Any]]:
	if not isinstance(payload, dict) or payload.get("version") != "2.0" or payload.get("class") != "dataset":
		raise RuntimeError("Unexpected Eurostat JSON-stat response.")
	dimension_ids = payload.get("id")
	sizes = payload.get("size")
	if not isinstance(dimension_ids, list) or not isinstance(sizes, list) or len(dimension_ids) != len(sizes):
		raise RuntimeError("Eurostat JSON-stat response has invalid dimensions.")
	if not dimension_ids or not all(isinstance(size, int) and size > 0 for size in sizes):
		raise RuntimeError("Eurostat JSON-stat response has invalid dimension sizes.")

	codes_by_dimension = {
		str(dimension_id): category_codes(payload, str(dimension_id), sizes[index])
		for index, dimension_id in enumerate(dimension_ids)
	}
	cell_count = math.prod(sizes)
	values = payload.get("value")
	if isinstance(values, list):
		if len(values) != cell_count:
			raise RuntimeError(f"Eurostat value array size mismatch: {len(values)} != {cell_count}.")
		items = enumerate(values)
	elif isinstance(values, dict):
		items = ((int(key), value) for key, value in values.items())
	else:
		raise RuntimeError("Eurostat JSON-stat response has invalid value storage.")

	strides = []
	for index in range(len(sizes)):
		strides.append(math.prod(sizes[index + 1:]) if index + 1 < len(sizes) else 1)

	for flat_index, raw_value in items:
		if raw_value is None:
			continue
		if flat_index < 0 or flat_index >= cell_count:
			raise RuntimeError(f"Eurostat sparse value index out of range: {flat_index}.")
		observation: dict[str, Any] = {"value": raw_value}
		remaining = flat_index
		for dimension_index, dimension_id in enumerate(dimension_ids):
			stride = strides[dimension_index]
			position = remaining // stride
			remaining %= stride
			observation[str(dimension_id)] = codes_by_dimension[str(dimension_id)][position]
		yield observation


def build_query_url(api_base: str, dataset: str, filters: dict[str, Any]) -> str:
	query_items: list[tuple[str, str]] = [("format", "JSON"), ("lang", "en")]
	for key, raw_value in filters.items():
		if isinstance(raw_value, list):
			for value in raw_value:
				query_items.append((str(key), str(value)))
		else:
			query_items.append((str(key), str(raw_value)))
	return f"{api_base}/{dataset}?{urlencode(query_items)}"


def source_geo_to_area_id(
	geo: str,
	area_by_iso2: dict[str, str],
	aliases: dict[str, str],
) -> str | None:
	code = str(geo).strip().upper()
	code = aliases.get(code, code)
	return area_by_iso2.get(code)


def normalized_year_period(raw_time: str, time_mode: str) -> tuple[int, int] | None:
	value = str(raw_time).strip()
	if time_mode == "annual":
		if not YEAR_RE.fullmatch(value):
			return None
		return int(value), 0
	match = SEMESTER_RE.fullmatch(value)
	if not match:
		return None
	return int(match.group(1)), int(match.group(2))


def normalize_indicator(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_iso2: dict[str, str],
	now: datetime,
	timeout: int,
) -> dict[str, Any]:
	api_base = str(config["apiBase"]).rstrip("/")
	provider = config["provider"]
	dataset = str(indicator["dataset"])
	filters = dict(indicator["filters"])
	aliases = {str(key).upper(): str(value).upper() for key, value in config.get("geoAliases", {}).items()}
	excluded_geos = {str(code).upper() for code in indicator.get("excludedGeos", [])}
	time_mode = str(indicator["timeMode"])
	url = build_query_url(api_base, dataset, filters)

	print(f"Fetching {indicator['id']} ({dataset})")
	payload = fetch_json(url, timeout)
	observations = iter_jsonstat_observations(payload)

	values_by_year: dict[int, dict[str, int | float]] = {}
	selected_periods: dict[int, dict[str, int]] = {}
	areas_with_any_value: set[str] = set()
	ignored_geo_codes: set[str] = set()
	excluded_geo_codes: set[str] = set()
	future_records = 0
	invalid_time_records = 0

	for observation in observations:
		geo = str(observation.get("geo", "")).strip().upper()
		if not geo:
			continue
		if geo in excluded_geos:
			excluded_geo_codes.add(geo)
			continue
		area_id = source_geo_to_area_id(geo, area_by_iso2, aliases)
		if area_id is None:
			ignored_geo_codes.add(geo)
			continue
		period = normalized_year_period(str(observation.get("time", "")), time_mode)
		if period is None:
			invalid_time_records += 1
			continue
		year, rank = period
		if year > now.year:
			future_records += 1
			continue
		number = normalize_number(observation["value"])
		year_values = values_by_year.setdefault(year, {})
		year_periods = selected_periods.setdefault(year, {})
		if area_id in year_values:
			previous_rank = year_periods[area_id]
			if time_mode == "annual" or rank == previous_rank:
				raise RuntimeError(f"Duplicate value for {indicator['id']} {year} {area_id}.")
			if rank < previous_rank:
				continue
		year_values[area_id] = number
		year_periods[area_id] = rank
		areas_with_any_value.add(area_id)

	values_by_year = {year: values for year, values in values_by_year.items() if values}
	if not values_by_year:
		raise RuntimeError(f"Eurostat returned no mapped values for {indicator['id']}.")

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

	normalization: dict[str, Any] = {
		"sourceFrequency": "annual" if time_mode == "annual" else "half-yearly",
		"outputFrequency": "annual",
	}
	if time_mode == "latest-semester-per-year":
		normalization["yearSelection"] = "latest available semester per area (S2 preferred, otherwise S1)"

	source_url = f"https://ec.europa.eu/eurostat/databrowser/view/{dataset}/default/table?lang=en"
	result = {
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
			"dataset": payload.get("label") or provider["dataset"],
			"datasetId": dataset,
			"updated": payload.get("updated"),
			"filters": filters,
			"normalization": normalization,
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": source_url,
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso2),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": latest_year,
			"areasInLatestYear": len(values_by_year[latest_year]),
			"broadCoverageThreshold": broad_threshold,
			"areasInDefaultYear": len(values_by_year[default_year]),
		},
		"values": sorted_values,
	}
	if indicator.get("classification") is not None:
		result["indicator"]["classification"] = indicator["classification"]

	print(
		f"  mapped={len(areas_with_any_value)} "
		f"years={available_years[0]}-{latest_year} "
		f"defaultYear={default_year} "
		f"defaultCoverage={len(values_by_year[default_year])} "
		f"ignoredGeos={sorted(ignored_geo_codes)} "
		f"excludedGeos={sorted(excluded_geo_codes)} "
		f"invalidTimes={invalid_time_records} "
		f"futureSkipped={future_records}"
	)
	return result


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
	listed = any(item["id"] == provider["id"] for item in provider_catalog["providers"])
	if not listed:
		print(
			f"Provider {provider['id']} is not yet listed in statistics-providers.json; "
			"building it without advertising it in the global index."
		)

	area_by_iso2, registry_payload = load_registry(args.registry, args.timeout)
	now = utc_now()
	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload = normalize_indicator(config, indicator, area_by_iso2, now, args.timeout)
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
		index_indicator = {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"sourceDataset": indicator["dataset"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		}
		if indicator.get("classification") is not None:
			index_indicator["classification"] = indicator["classification"]
		index_indicators.append(index_indicator)

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_iso2),
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

	print(f"Built Eurostat snapshot {snapshot}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
