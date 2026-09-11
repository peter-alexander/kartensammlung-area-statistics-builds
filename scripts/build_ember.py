#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from io import TextIOWrapper
import math
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "ember-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
EXPECTED_COLUMNS = [
	"Area",
	"ISO 3 code",
	"Year",
	"Area type",
	"Continent",
	"Ember region",
	"EU",
	"OECD",
	"G20",
	"G7",
	"ASEAN",
	"Category",
	"Subcategory",
	"Variable",
	"Unit",
	"Value",
	"YoY absolute change",
	"YoY % change",
]


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build country electricity statistics from Ember Yearly Electricity Data.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=180)
	return parser.parse_args()


def selector_tuple(source: dict[str, Any]) -> tuple[str, str, str, str]:
	return (
		str(source.get("category", "")).strip(),
		str(source.get("subcategory", "")).strip(),
		str(source.get("variable", "")).strip(),
		str(source.get("unit", "")).strip(),
	)


def minimum_default_coverage(indicator: dict[str, Any]) -> int:
	value = indicator.get("minAreasInDefaultYear", indicator.get("minAreasInLatestYear"))
	if not isinstance(value, int) or value <= 0:
		raise ValueError(f"Ember indicator {indicator.get('id')} has invalid default-year coverage threshold.")
	return value


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.ember-statistics/v1":
		raise ValueError("Invalid Ember statistics config.")
	download_url = str(payload.get("downloadUrl", "")).strip()
	if not download_url.startswith("https://"):
		raise ValueError("Ember downloadUrl must use HTTPS.")
	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "ember":
		raise ValueError("Ember provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"Ember provider metadata is missing {key}.")
	expected_start = payload.get("expectedStartYear")
	minimum_latest = payload.get("minimumLatestYear")
	if not isinstance(expected_start, int) or not 1900 <= expected_start <= 2200:
		raise ValueError("Ember expectedStartYear is invalid.")
	if not isinstance(minimum_latest, int) or minimum_latest < expected_start:
		raise ValueError("Ember minimumLatestYear is invalid.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("Ember config requires indicators.")

	ids: set[str] = set()
	slugs: set[str] = set()
	selectors: set[tuple[str, str, str, str]] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("Ember indicator entries must be objects.")
		for key in ("id", "slug", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"Ember indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate Ember indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate Ember indicator slug: {slug}")
		ids.add(indicator_id)
		slugs.add(slug)

		source = indicator.get("source")
		derived = indicator.get("derived")
		if (source is None) == (derived is None):
			raise ValueError(f"Ember indicator {indicator_id} must define exactly one of source or derived.")
		if source is not None:
			if not isinstance(source, dict):
				raise ValueError(f"Ember source for {indicator_id} must be an object.")
			selector = selector_tuple(source)
			if not all(selector):
				raise ValueError(f"Ember source selector for {indicator_id} is incomplete.")
			if selector in selectors:
				raise ValueError(f"Duplicate Ember source selector: {selector}")
			selectors.add(selector)
		else:
			if not isinstance(derived, dict) or derived.get("type") != "ratio-percent":
				raise ValueError(f"Unsupported Ember derived indicator {indicator_id}.")
			for key in ("numerator", "denominator"):
				if not str(derived.get(key, "")).strip():
					raise ValueError(f"Ember derived indicator {indicator_id} is missing {key}.")

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"Ember indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		any_value = indicator.get("minAreasWithAnyValue")
		if not isinstance(any_value, int) or any_value <= 0:
			raise ValueError(f"Ember indicator {indicator_id} has invalid minAreasWithAnyValue.")
		minimum_default_coverage(indicator)

	for indicator in indicators:
		derived = indicator.get("derived")
		if not isinstance(derived, dict):
			continue
		for key in ("numerator", "denominator"):
			reference = str(derived[key])
			if reference not in ids:
				raise ValueError(f"Ember derived indicator {indicator['id']} references unknown {key}: {reference}")
	return payload


def parse_value(raw: str) -> int | float:
	value = common.normalize_number(raw)
	number = float(value)
	if not math.isfinite(number):
		raise RuntimeError(f"Non-finite Ember value: {raw!r}")
	return value


def normalize_derived(number: float) -> int | float:
	if not math.isfinite(number):
		raise RuntimeError("Non-finite Ember derived value.")
	rounded = round(number, 6)
	if rounded.is_integer():
		return int(rounded)
	return rounded


def load_direct_values(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	timeout: int,
) -> tuple[dict[str, dict[int, dict[str, int | float]]], set[str], int, int]:
	direct_indicators = [indicator for indicator in config["indicators"] if isinstance(indicator.get("source"), dict)]
	indicator_by_selector = {
		selector_tuple(indicator["source"]): indicator
		for indicator in direct_indicators
	}
	values: dict[str, dict[int, dict[str, int | float]]] = {
		str(indicator["id"]): defaultdict(dict)
		for indicator in direct_indicators
	}
	ignored_iso3: set[str] = set()
	all_years: set[int] = set()
	request = Request(
		str(config["downloadUrl"]),
		headers={"User-Agent": "kartensammlung-area-statistics-builds/1"},
	)
	with urlopen(request, timeout=timeout) as response:
		reader = csv.DictReader(TextIOWrapper(response, encoding="utf-8-sig", newline=""))
		if reader.fieldnames != EXPECTED_COLUMNS:
			raise RuntimeError(f"Ember CSV columns changed: {reader.fieldnames}")
		for row in reader:
			if (row.get("Area type") or "").strip() != "Country or economy":
				continue
			year_text = (row.get("Year") or "").strip()
			if not year_text.isdigit() or len(year_text) != 4:
				continue
			year = int(year_text)
			all_years.add(year)
			selector = (
				(row.get("Category") or "").strip(),
				(row.get("Subcategory") or "").strip(),
				(row.get("Variable") or "").strip(),
				(row.get("Unit") or "").strip(),
			)
			indicator = indicator_by_selector.get(selector)
			if indicator is None:
				continue
			raw_value = (row.get("Value") or "").strip()
			if not raw_value:
				continue
			iso3 = (row.get("ISO 3 code") or "").strip().upper()
			if iso3 not in area_by_iso3:
				if iso3:
					ignored_iso3.add(iso3)
				continue
			area_id = area_by_iso3[iso3]
			indicator_id = str(indicator["id"])
			year_values = values[indicator_id][year]
			if area_id in year_values:
				raise RuntimeError(f"Duplicate Ember value for {indicator_id} {year} {area_id}.")
			year_values[area_id] = parse_value(raw_value)

	if not all_years:
		raise RuntimeError("Ember CSV contained no annual country rows.")
	return values, ignored_iso3, min(all_years), max(all_years)


def build_derived_values(
	config: dict[str, Any],
	values_by_id: dict[str, dict[int, dict[str, int | float]]],
) -> None:
	for indicator in config["indicators"]:
		derived = indicator.get("derived")
		if not isinstance(derived, dict):
			continue
		indicator_id = str(indicator["id"])
		numerator_id = str(derived["numerator"])
		denominator_id = str(derived["denominator"])
		numerator = values_by_id[numerator_id]
		denominator = values_by_id[denominator_id]
		result: dict[int, dict[str, int | float]] = defaultdict(dict)
		for year in sorted(set(numerator) & set(denominator)):
			for area_id in sorted(set(numerator[year]) & set(denominator[year])):
				denominator_value = float(denominator[year][area_id])
				if denominator_value == 0:
					continue
				result[year][area_id] = normalize_derived(
					float(numerator[year][area_id]) / denominator_value * 100.0
				)
		values_by_id[indicator_id] = result


def source_label(indicator: dict[str, Any]) -> str:
	source = indicator.get("source")
	if isinstance(source, dict):
		return " / ".join(selector_tuple(source))
	derived = indicator["derived"]
	return f"derived:{derived['type']}:{derived['numerator']}:{derived['denominator']}"


def choose_default_year(
	indicator: dict[str, Any],
	available_years: list[int],
	year_values: dict[int, dict[str, int | float]],
) -> int:
	minimum_coverage = minimum_default_coverage(indicator)
	eligible_years = [
		year
		for year in available_years
		if len(year_values[year]) >= minimum_coverage
	]
	if not eligible_years:
		raise RuntimeError(
			f"Ember has no sufficiently complete default year for {indicator['id']}: "
			f"expected at least {minimum_coverage} areas."
		)
	return eligible_years[-1]


def build_payloads(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_id: dict[str, dict[int, dict[str, int | float]]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
	provider = config["provider"]
	result: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		year_values = values_by_id.get(indicator_id, {})
		available_years = sorted(year for year, mapped in year_values.items() if mapped)
		if not available_years:
			raise RuntimeError(f"Ember returned no mapped values for {indicator_id}.")
		if available_years[0] > int(config["expectedStartYear"]):
			raise RuntimeError(f"Ember history for {indicator_id} starts too late: {available_years[0]}.")
		latest_year = available_years[-1]
		if latest_year < int(config["minimumLatestYear"]):
			raise RuntimeError(f"Ember latest year for {indicator_id} is too old: {latest_year}.")
		mapped_areas = {area_id for mapped in year_values.values() for area_id in mapped}
		if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
			raise RuntimeError(
				f"Ember coverage too small for {indicator_id}: {len(mapped_areas)} areas, "
				f"expected at least {indicator['minAreasWithAnyValue']}."
			)
		default_year = choose_default_year(indicator, available_years, year_values)
		latest_coverage = len(year_values[latest_year])
		default_coverage = len(year_values[default_year])

		indicator_metadata = {
			"id": indicator_id,
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		}
		source_metadata: dict[str, Any] = {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": "https://ember-energy.org/data/yearly-electricity-data/",
			"downloadUrl": config["downloadUrl"],
		}
		if isinstance(indicator.get("source"), dict):
			source_metadata["selector"] = indicator["source"]
		else:
			source_metadata["derived"] = indicator["derived"]
			source_metadata["derivationNote"] = "Calculated from two Ember series in the same annual release."

		payload = {
			"schema": "kartensammlung.statistics-indicator/v1",
			"indicator": indicator_metadata,
			"source": source_metadata,
			"availableYears": available_years,
			"defaultYear": default_year,
			"coverage": {
				"registryAreas": len(area_by_iso3),
				"areasWithAnyValue": len(mapped_areas),
				"latestYear": latest_year,
				"areasInLatestYear": latest_coverage,
				"areasInDefaultYear": default_coverage,
			},
			"values": {
				str(year): {
					area_id: year_values[year][area_id]
					for area_id in sorted(year_values[year])
				}
				for year in available_years
			},
		}
		print(
			f"{indicator_id}: mapped={len(mapped_areas)} years={available_years[0]}-{latest_year} "
			f"latestCoverage={latest_coverage} defaultYear={default_year} defaultCoverage={default_coverage}"
		)
		result.append((indicator, payload))
	return result


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("Ember is missing from statistics-providers.json.")
	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	print(f"Fetching Ember Yearly Electricity Data from {config['downloadUrl']}")
	values_by_id, ignored_iso3, source_start, source_latest = load_direct_values(config, area_by_iso3, args.timeout)
	if source_start > int(config["expectedStartYear"]):
		raise RuntimeError(f"Ember source starts too late: {source_start}.")
	if source_latest < int(config["minimumLatestYear"]):
		raise RuntimeError(f"Ember source is unexpectedly old: latest year {source_latest}.")
	build_derived_values(config, values_by_id)
	indicator_payloads = build_payloads(config, area_by_iso3, values_by_id)
	now = datetime.now(timezone.utc)

	hasher = hashlib.sha256()
	for indicator, payload in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(common.canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []
	for indicator, payload in indicator_payloads:
		filename = f"{indicator['slug']}.json"
		common.write_json(release_dir / filename, payload)
		index_indicators.append({
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"sourceIndicator": source_label(indicator),
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		})

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
		"dataset": {
			"downloadUrl": config["downloadUrl"],
			"sourceStartYear": source_start,
			"sourceLatestYear": source_latest,
			"areaType": "Country or economy",
		},
		"indicators": index_indicators,
		"notes": [
			"Annual country/economy electricity data from Ember Yearly Electricity Data.",
			"The newest source year may have partial country coverage; each indicator defaults to the newest year that reaches its configured coverage threshold.",
			"Net Imports: positive values indicate net electricity imports; negative values indicate net exports.",
			"The net-import share of demand is derived from Ember Net Imports divided by Ember Demand for the same country and year.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Ignored Ember ISO3 codes: {sorted(ignored_iso3) or '(none)'}")
	print(f"Built Ember snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
