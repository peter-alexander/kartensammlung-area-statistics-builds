#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "aquastat-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
REQUIRED_FIELDS = {
	"Country", "Variable", "IsAggregate", "Year", "Value", "Unit", "Symbol",
	"SymbolDescription", "m49", "VariableCode"
}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized country statistics from FAO AQUASTAT.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def utc_now() -> datetime:
	return datetime.now(timezone.utc)


def read_json(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.aquastat-statistics/v1":
		raise ValueError("Invalid AQUASTAT statistics config.")
	for key in ("apiUrl", "sqlUrl", "datasetUrl", "catalogUrl", "releaseUrl"):
		value = str(payload.get(key, "")).strip()
		if not value.startswith("https://"):
			raise ValueError(f"AQUASTAT {key} must use HTTPS.")
	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "aquastat":
		raise ValueError("AQUASTAT provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"AQUASTAT provider metadata is missing {key}.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("AQUASTAT config requires indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	variables: set[int] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("AQUASTAT indicator entries must be objects.")
		for key in ("id", "slug", "title", "description", "sourceUnit"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"AQUASTAT indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		variable = indicator.get("sourceVariable")
		if not isinstance(variable, int) or variable <= 0:
			raise ValueError(f"AQUASTAT indicator {indicator_id} has invalid sourceVariable.")
		if indicator_id in ids or slug in slugs or variable in variables:
			raise ValueError(f"Duplicate AQUASTAT indicator id, slug or source variable: {indicator_id}")
		ids.add(indicator_id)
		slugs.add(slug)
		variables.add(variable)
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"AQUASTAT indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("startYear", "minimumLatestYear", "minimumDefaultYear", "minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"AQUASTAT indicator {indicator_id} has invalid {key}.")
		if int(indicator["startYear"]) > int(indicator["minimumLatestYear"]):
			raise ValueError(f"AQUASTAT indicator {indicator_id} startYear is after minimumLatestYear.")
		required = indicator.get("requiredAreas")
		if not isinstance(required, list) or not required:
			raise ValueError(f"AQUASTAT indicator {indicator_id} requires requiredAreas.")
		value_range = indicator.get("valueRange")
		if (
			not isinstance(value_range, list) or len(value_range) != 2
			or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in value_range)
			or not math.isfinite(float(value_range[0])) or not math.isfinite(float(value_range[1]))
			or float(value_range[0]) >= float(value_range[1])
		):
			raise ValueError(f"AQUASTAT indicator {indicator_id} has invalid valueRange.")
	return payload


def normalize_m49(raw: Any) -> str:
	text = str(raw if raw is not None else "").strip().lstrip("'")
	if not text:
		return ""
	if not text.isdigit():
		return ""
	text = text.zfill(3)
	return text if len(text) == 3 else ""


def load_registry_by_m49(source: str, timeout: int) -> tuple[dict[str, str], dict[str, Any], int]:
	payload = common.load_json_source(source, timeout)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.area-registry/v1":
		raise ValueError("Invalid area registry.")
	areas = payload.get("areas")
	if not isinstance(areas, list) or not areas:
		raise ValueError("Area registry has no areas.")
	area_by_m49: dict[str, str] = {}
	country_count = 0
	for area in areas:
		if not isinstance(area, dict) or area.get("level") != "country":
			continue
		country_count += 1
		area_id = str(area.get("area_id", "")).strip()
		codes = area.get("codes")
		if not isinstance(codes, dict):
			continue
		m49 = str(codes.get("m49", "")).strip()
		if not m49:
			continue
		if not area_id or len(m49) != 3 or not m49.isdigit():
			raise RuntimeError(f"Invalid M49 registry entry: {area_id} {m49!r}")
		if m49 in area_by_m49:
			raise RuntimeError(f"Duplicate M49 registry code: {m49}")
		area_by_m49[m49] = area_id
	if country_count < 240 or len(area_by_m49) < 240:
		raise RuntimeError(f"Area registry unexpectedly small: countries={country_count} m49={len(area_by_m49)}")
	for required in ("040", "276", "840", "356", "156"):
		if required not in area_by_m49:
			raise RuntimeError(f"Area registry M49 sanity check failed: {required}")
	return area_by_m49, payload, country_count


def fetch_csv(url: str, timeout: int) -> tuple[list[dict[str, str]], list[str], int, dict[str, str]]:
	delays = (0, 5, 15, 30)
	last_error: Exception | None = None
	for attempt, delay in enumerate(delays, start=1):
		if delay:
			time.sleep(delay)
		req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"})
		try:
			with urlopen(req, timeout=timeout) as response:
				data = response.read()
				headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
			if not data:
				raise RuntimeError("AQUASTAT returned an empty response.")
			text = data.decode("utf-8-sig")
			reader = csv.DictReader(io.StringIO(text))
			fields = reader.fieldnames or []
			return list(reader), fields, len(data), headers
		except (HTTPError, URLError, TimeoutError, RuntimeError, UnicodeDecodeError) as error:
			last_error = error
			print(f"AQUASTAT request failed ({attempt}/{len(delays)}): {error}")
	if last_error is None:
		raise RuntimeError("AQUASTAT request failed without exception.")
	raise RuntimeError("AQUASTAT request failed after retries.") from last_error


def query_url(config: dict[str, Any], indicator: dict[str, Any], current_year: int) -> str:
	years = ",".join(str(year) for year in range(int(indicator["startYear"]), current_year + 1))
	params = {
		"area": "World",
		"download": "true",
		"sql_url": str(config["sqlUrl"]),
		"type": "all",
		"variable": str(indicator["sourceVariable"]),
		"year": years,
	}
	return f"{str(config['apiUrl']).rstrip('/')}?{urlencode(params)}"


def fetch_indicator(config: dict[str, Any], indicator: dict[str, Any], current_year: int, timeout: int) -> tuple[dict[str, Any], list[dict[str, str]], int, dict[str, str]]:
	url = query_url(config, indicator, current_year)
	rows, fields, byte_count, headers = fetch_csv(url, timeout)
	missing = sorted(REQUIRED_FIELDS - set(fields))
	if missing:
		raise RuntimeError(f"AQUASTAT schema changed for {indicator['id']}: missing {missing}")
	return indicator, rows, byte_count, headers


def choose_default_year(indicator: dict[str, Any], years: list[int], values_by_year: dict[int, dict[str, int | float]]) -> int:
	minimum = int(indicator["minAreasInDefaultYear"])
	candidates = [year for year in years if len(values_by_year[year]) >= minimum]
	if not candidates:
		raise RuntimeError(f"No AQUASTAT year reaches default coverage for {indicator['id']}.")
	default_year = candidates[-1]
	if default_year < int(indicator["minimumDefaultYear"]):
		raise RuntimeError(f"AQUASTAT default year too old for {indicator['id']}: {default_year}")
	return default_year


def build_indicator_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	rows: list[dict[str, str]],
	byte_count: int,
	headers: dict[str, str],
	area_by_m49: dict[str, str],
	registry_country_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
	indicator_id = str(indicator["id"])
	variable_code = str(indicator["sourceVariable"])
	values_by_year: dict[int, dict[str, int | float]] = defaultdict(dict)
	metadata_by_year: dict[int, dict[str, dict[str, str]]] = defaultdict(dict)
	areas_with_any_value: set[str] = set()
	ignored_source_areas: dict[str, str] = {}
	flag_descriptions: dict[str, str] = {}
	flag_counts: dict[str, int] = defaultdict(int)
	source_names: set[str] = set()
	source_units: set[str] = set()
	min_value, max_value = (float(value) for value in indicator["valueRange"])
	mapped_rows = 0
	missing_rows = 0

	for row in rows:
		code = str(row.get("VariableCode", "")).strip()
		if code != variable_code:
			raise RuntimeError(f"AQUASTAT returned unexpected variable {code!r} for {indicator_id}.")
		source_names.add(str(row.get("Variable", "")).strip())
		unit = str(row.get("Unit", "")).strip()
		source_units.add(unit)
		if unit != str(indicator["sourceUnit"]):
			raise RuntimeError(f"Unexpected AQUASTAT unit for {indicator_id}: {unit!r}")
		if str(row.get("IsAggregate", "")).strip().lower() == "true":
			continue
		m49 = normalize_m49(row.get("m49"))
		area_name = str(row.get("Country", "")).strip()
		area_id = area_by_m49.get(m49)
		if not area_id:
			if m49:
				ignored_source_areas[m49] = area_name
			continue
		year_text = str(row.get("Year", "")).strip()
		if not year_text.isdigit() or len(year_text) != 4:
			raise RuntimeError(f"Invalid AQUASTAT year for {indicator_id}: {year_text!r}")
		year = int(year_text)
		value_text = str(row.get("Value", "")).strip()
		if not value_text:
			missing_rows += 1
			continue
		try:
			value = common.normalize_number(value_text)
		except (TypeError, ValueError) as error:
			raise RuntimeError(f"Invalid AQUASTAT value for {indicator_id} {m49} {year}: {value_text!r}") from error
		numeric = float(value)
		if numeric < min_value or numeric > max_value:
			raise RuntimeError(f"AQUASTAT value outside configured range for {indicator_id} {m49} {year}: {value}")
		if area_id in values_by_year[year]:
			raise RuntimeError(f"Duplicate AQUASTAT value for {indicator_id} {year} {area_id}.")
		values_by_year[year][area_id] = value
		areas_with_any_value.add(area_id)
		mapped_rows += 1
		flag = str(row.get("Symbol", "")).strip()
		description = str(row.get("SymbolDescription", "")).strip()
		if flag:
			flag_counts[flag] += 1
			if description:
				existing = flag_descriptions.get(flag)
				if existing is not None and existing != description:
					raise RuntimeError(f"Conflicting AQUASTAT flag description for {flag}: {existing!r} vs {description!r}")
				flag_descriptions[flag] = description
			metadata_by_year[year][area_id] = {"sourceFlag": flag}

	if len(source_names) != 1:
		raise RuntimeError(f"Unexpected AQUASTAT variable names for {indicator_id}: {sorted(source_names)}")
	if source_units != {str(indicator["sourceUnit"])}:
		raise RuntimeError(f"Unexpected AQUASTAT source units for {indicator_id}: {sorted(source_units)}")
	if not values_by_year:
		raise RuntimeError(f"AQUASTAT returned no mapped values for {indicator_id}.")
	if len(areas_with_any_value) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(f"AQUASTAT coverage too small for {indicator_id}: {len(areas_with_any_value)}")
	available_years = sorted(values_by_year)
	latest_year = available_years[-1]
	if latest_year < int(indicator["minimumLatestYear"]):
		raise RuntimeError(f"AQUASTAT source too old for {indicator_id}: {latest_year}")
	default_year = choose_default_year(indicator, available_years, values_by_year)
	for area_id in indicator["requiredAreas"]:
		if area_id not in values_by_year[default_year]:
			raise RuntimeError(f"Required area {area_id} missing for {indicator_id} in {default_year}.")

	sorted_values = {
		str(year): {area_id: values_by_year[year][area_id] for area_id in sorted(values_by_year[year])}
		for year in available_years
	}
	sorted_metadata = {
		str(year): {area_id: metadata_by_year[year][area_id] for area_id in sorted(metadata_by_year[year])}
		for year in sorted(metadata_by_year) if metadata_by_year[year]
	}
	provider = config["provider"]
	indicator_metadata = {
		"id": indicator_id,
		"title": indicator["title"],
		"description": indicator["description"],
		"areaLevel": "country",
		"frequency": "annual",
		"unit": indicator["unit"],
		"classification": indicator["classification"],
	}
	coverage = {
		"registryAreas": registry_country_count,
		"areasWithAnyValue": len(areas_with_any_value),
		"latestYear": latest_year,
		"areasInLatestYear": len(values_by_year[latest_year]),
		"defaultYear": default_year,
		"areasInDefaultYear": len(values_by_year[default_year]),
	}
	payload: dict[str, Any] = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": indicator_metadata,
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"indicator": variable_code,
			"indicatorName": next(iter(source_names)),
			"sourceUnit": str(indicator["sourceUnit"]),
			"qualityFlags": dict(sorted(flag_descriptions.items())),
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["datasetUrl"],
			"catalogUrl": config["catalogUrl"],
			"releaseUrl": config["releaseUrl"],
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": coverage,
		"values": sorted_values,
	}
	if sorted_metadata:
		payload["observationMetadata"] = sorted_metadata
	diagnostics = {
		"sourceVariable": int(variable_code),
		"sourceName": next(iter(source_names)),
		"sourceRows": len(rows),
		"sourceBytes": byte_count,
		"mappedRows": mapped_rows,
		"mappedAreas": len(areas_with_any_value),
		"firstYear": available_years[0],
		"latestYear": latest_year,
		"defaultYear": default_year,
		"latestCoverage": len(values_by_year[latest_year]),
		"defaultCoverage": len(values_by_year[default_year]),
		"missingMappedRows": missing_rows,
		"flags": dict(sorted(flag_counts.items())),
		"flagDescriptions": dict(sorted(flag_descriptions.items())),
		"ignoredSourceAreas": dict(sorted(ignored_source_areas.items())),
	}
	if headers.get("last-modified"):
		diagnostics["lastModified"] = headers["last-modified"]
	print(
		f"{indicator_id}: variable={variable_code} mapped={len(areas_with_any_value)} "
		f"years={available_years[0]}-{latest_year} default={default_year} "
		f"defaultCoverage={len(values_by_year[default_year])} flags={dict(sorted(flag_counts.items()))}"
	)
	return payload, diagnostics


def canonical_bytes(payload: Any) -> bytes:
	return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_json(path: Path, payload: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")


def main() -> None:
	args = parse_args()
	config = validate_config(read_json(args.config))
	provider_catalog = common.validate_provider_catalog(read_json(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")
	area_by_m49, registry_payload, registry_country_count = load_registry_by_m49(args.registry, args.timeout)
	print(f"AQUASTAT registry: countries={registry_country_count} M49={len(area_by_m49)}")
	now = utc_now()
	fetched: dict[str, tuple[list[dict[str, str]], int, dict[str, str]]] = {}
	with ThreadPoolExecutor(max_workers=4) as pool:
		future_map = {
			pool.submit(fetch_indicator, config, indicator, now.year, args.timeout): indicator
			for indicator in config["indicators"]
		}
		for future in as_completed(future_map):
			indicator = future_map[future]
			_, rows, byte_count, headers = future.result()
			fetched[str(indicator["id"])] = (rows, byte_count, headers)

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		rows, byte_count, headers = fetched[str(indicator["id"])]
		payload, diagnostics = build_indicator_payload(
			config, indicator, rows, byte_count, headers, area_by_m49, registry_country_count
		)
		indicator_payloads.append((indicator, payload, diagnostics))

	hasher = hashlib.sha256()
	for indicator, payload, _ in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []
	all_diagnostics: dict[str, Any] = {}
	for indicator, payload, diagnostics in indicator_payloads:
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
			"sourceIndicator": str(indicator["sourceVariable"]),
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		})
		all_diagnostics[str(indicator["id"])] = diagnostics
	registry_source: dict[str, Any] = {
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": registry_country_count,
		"m49AreaCount": len(area_by_m49),
	}
	if args.registry.startswith(("http://", "https://")):
		registry_source["url"] = args.registry
	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"dataset": {
			"url": config["datasetUrl"],
			"catalogUrl": config["catalogUrl"],
			"releaseUrl": config["releaseUrl"],
		},
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"indicators": index_indicators,
	}
	diagnostics_payload = {
		"schema": "kartensammlung.aquastat-build-diagnostics/v1",
		"retrievedAt": provider_index["retrievedAt"],
		"activeSnapshot": snapshot,
		"registry": registry_source,
		"indicators": all_diagnostics,
	}
	write_json(provider_dir / "index.json", provider_index)
	write_json(provider_dir / "diagnostics.json", diagnostics_payload)
	write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built AQUASTAT snapshot {snapshot}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
