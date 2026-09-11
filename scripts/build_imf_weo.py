#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
from typing import Any

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "imf-weo-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"

# IMF DataMapper uses a few WEO-specific country codes instead of ISO 3166-1 alpha-3.
ISO3_ALIASES = {
	"UVK": "XKX",  # Kosovo
	"WBG": "PSE",  # West Bank and Gaza / State of Palestine
}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build country fiscal statistics from IMF World Economic Outlook DataMapper."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=60)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.imf-weo-statistics/v1":
		raise ValueError("Invalid IMF WEO statistics config.")
	api_base = str(payload.get("apiBase", "")).strip().rstrip("/")
	source_page = str(payload.get("sourcePage", "")).strip()
	provider = payload.get("provider")
	minimum_latest_year = payload.get("minimumLatestYear")
	indicators = payload.get("indicators")

	if not api_base.startswith("https://"):
		raise ValueError("IMF WEO apiBase must use HTTPS.")
	if not source_page.startswith("https://"):
		raise ValueError("IMF WEO sourcePage must use HTTPS.")
	if not isinstance(provider, dict) or provider.get("id") != "imf-weo":
		raise ValueError("IMF WEO provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"IMF WEO provider metadata is missing {key}.")
	if not isinstance(minimum_latest_year, int) or minimum_latest_year < 2025:
		raise ValueError("IMF WEO minimumLatestYear is invalid.")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("IMF WEO config requires indicators.")

	ids: set[str] = set()
	slugs: set[str] = set()
	source_indicators: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("IMF WEO indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"IMF WEO indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		source_indicator = str(indicator["sourceIndicator"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate IMF WEO indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate IMF WEO indicator slug: {slug}")
		if source_indicator in source_indicators:
			raise ValueError(f"Duplicate IMF WEO source indicator: {source_indicator}")
		ids.add(indicator_id)
		slugs.add(slug)
		source_indicators.add(source_indicator)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"IMF WEO indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"IMF WEO indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"IMF WEO indicator {indicator_id} requires at least one required area.")
	return payload


def load_country_codes(api_base: str, timeout: int) -> set[str]:
	payload = common.fetch_json(f"{api_base}/countries", timeout)
	if not isinstance(payload, dict) or not isinstance(payload.get("countries"), dict):
		raise RuntimeError("Unexpected IMF DataMapper countries response.")
	codes = {
		str(code).strip().upper()
		for code in payload["countries"]
		if str(code).strip()
	}
	if len(codes) < 200:
		raise RuntimeError(f"IMF DataMapper country catalog unexpectedly small: {len(codes)} entries.")
	for required in ("AUT", "DEU", "USA", "IND", "UVK"):
		if required not in codes:
			raise RuntimeError(f"IMF DataMapper country catalog sanity check failed: {required} is missing.")
	return codes


def mapped_iso3(source_code: str) -> str:
	code = source_code.strip().upper()
	return ISO3_ALIASES.get(code, code)


def normalize_indicator(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_iso3: dict[str, str],
	country_codes: set[str],
	now,
	timeout: int,
) -> dict[str, Any]:
	api_base = str(config["apiBase"]).rstrip("/")
	provider = config["provider"]
	source_indicator = str(indicator["sourceIndicator"])
	api_url = f"{api_base}/{source_indicator}"
	print(f"Fetching {indicator['id']} ({source_indicator})")
	payload = common.fetch_json(api_url, timeout)
	if not isinstance(payload, dict) or not isinstance(payload.get("values"), dict):
		raise RuntimeError(f"Unexpected IMF DataMapper response for {source_indicator}.")
	indicator_values = payload["values"].get(source_indicator)
	if not isinstance(indicator_values, dict):
		raise RuntimeError(f"IMF DataMapper response is missing values for {source_indicator}.")

	values_by_year: dict[int, dict[str, int | float]] = {}
	areas_with_any_value: set[str] = set()
	ignored_codes: set[str] = set()
	for source_code, yearly_values in indicator_values.items():
		code = str(source_code).strip().upper()
		if code not in country_codes:
			continue
		iso3 = mapped_iso3(code)
		if iso3 not in area_by_iso3:
			ignored_codes.add(code)
			continue
		if not isinstance(yearly_values, dict):
			raise RuntimeError(f"IMF WEO country series has invalid shape: {source_indicator} {code}.")
		area_id = area_by_iso3[iso3]
		for raw_year, raw_value in yearly_values.items():
			if raw_value is None:
				continue
			year_text = str(raw_year).strip()
			if len(year_text) != 4 or not year_text.isdigit():
				continue
			year = int(year_text)
			if year < 1900 or year > now.year + 10:
				continue
			number = common.normalize_number(raw_value)
			if not math.isfinite(float(number)):
				raise RuntimeError(f"Non-finite IMF WEO value: {source_indicator} {code} {year}.")
			year_values = values_by_year.setdefault(year, {})
			if area_id in year_values:
				raise RuntimeError(f"Duplicate IMF WEO value for {indicator['id']} {year} {area_id}.")
			year_values[area_id] = number
			areas_with_any_value.add(area_id)

	if not values_by_year:
		raise RuntimeError(f"IMF WEO returned no mapped values for {indicator['id']}.")
	minimum_any = int(indicator["minAreasWithAnyValue"])
	if len(areas_with_any_value) < minimum_any:
		raise RuntimeError(
			f"IMF WEO coverage too small for {indicator['id']}: {len(areas_with_any_value)} areas, "
			f"expected at least {minimum_any}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in areas_with_any_value:
			raise RuntimeError(f"Required area {area_id} has no IMF WEO values for {indicator['id']}.")

	available_years = sorted(values_by_year)
	latest_year = available_years[-1]
	if latest_year < int(config["minimumLatestYear"]):
		raise RuntimeError(
			f"IMF WEO latest year for {indicator['id']} is too old: {latest_year}, "
			f"expected at least {config['minimumLatestYear']}."
		)

	projection_start_year = now.year
	minimum_default_coverage = int(indicator["minAreasInDefaultYear"])
	eligible_default_years = [
		year
		for year in available_years
		if year < projection_start_year and len(values_by_year[year]) >= minimum_default_coverage
	]
	if not eligible_default_years:
		raise RuntimeError(
			f"IMF WEO has no sufficiently complete pre-projection year for {indicator['id']}: "
			f"expected at least {minimum_default_coverage} areas."
		)
	default_year = eligible_default_years[-1]
	if now.year - default_year > 2:
		raise RuntimeError(
			f"IMF WEO default year for {indicator['id']} is unexpectedly old: {default_year}."
		)

	sorted_values = {
		str(year): {
			area_id: values_by_year[year][area_id]
			for area_id in sorted(values_by_year[year])
		}
		for year in available_years
	}
	indicator_metadata = {
		"id": indicator["id"],
		"title": indicator["title"],
		"description": indicator["description"],
		"areaLevel": "country",
		"frequency": "annual",
		"unit": indicator["unit"],
	}
	if isinstance(indicator.get("classification"), dict):
		indicator_metadata["classification"] = indicator["classification"]

	result = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": indicator_metadata,
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"indicator": source_indicator,
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": f"https://www.imf.org/external/datamapper/{source_indicator}@WEO",
			"apiUrl": api_url,
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": latest_year,
			"areasInLatestYear": len(values_by_year[latest_year]),
			"areasInDefaultYear": len(values_by_year[default_year]),
			"projectionStartYear": projection_start_year,
		},
		"values": sorted_values,
	}
	print(
		f"  mapped={len(areas_with_any_value)} "
		f"years={available_years[0]}-{latest_year} "
		f"defaultYear={default_year} "
		f"defaultCoverage={len(values_by_year[default_year])} "
		f"projectionStartYear={projection_start_year} "
		f"ignoredCodes={len(ignored_codes)}"
	)
	if ignored_codes:
		print(f"  ignored country codes: {', '.join(sorted(ignored_codes))}")
	return result


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	country_codes = load_country_codes(str(config["apiBase"]).rstrip("/"), args.timeout)
	now = common.utc_now()
	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload = normalize_indicator(config, indicator, area_by_iso3, country_codes, now, args.timeout)
		indicator_payloads.append((indicator, payload))

	hasher = hashlib.sha256()
	for indicator, payload in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(common.canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	output_dir = args.output_dir
	provider_dir = output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []
	for indicator, payload in indicator_payloads:
		filename = f"{indicator['slug']}.json"
		common.write_json(release_dir / filename, payload)
		index_indicator = {
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
		if isinstance(indicator.get("classification"), dict):
			index_indicator["classification"] = indicator["classification"]
		index_indicators.append(index_indicator)

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
			"sourcePage": config["sourcePage"],
			"apiBase": config["apiBase"],
			"projectionStartYear": now.year,
			"projectionLabel": "IMF WEO",
			"defaultYearPolicy": "Latest sufficiently covered year before the current calendar year.",
		},
		"indicators": index_indicators,
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(output_dir / "index.json", common.build_global_index(provider_catalog))

	print(f"Built IMF WEO snapshot {snapshot}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
