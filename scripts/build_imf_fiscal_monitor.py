#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
from typing import Any

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "imf-fiscal-monitor-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"

ISO3_ALIASES = {
	"UVK": "XKX",
	"WBG": "PSE",
}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build country fiscal statistics from the IMF Fiscal Monitor DataMapper dataset."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=60)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.imf-fiscal-monitor-statistics/v1":
		raise ValueError("Invalid IMF Fiscal Monitor statistics config.")

	api_base = str(payload.get("apiBase", "")).strip().rstrip("/")
	source_page = str(payload.get("sourcePage", "")).strip()
	dataset_code = str(payload.get("datasetCode", "")).strip()
	provider = payload.get("provider")
	minimum_projection_year = payload.get("minimumProjectionYear")
	minimum_latest_year = payload.get("minimumLatestYear")
	indicators = payload.get("indicators")

	if not api_base.startswith("https://"):
		raise ValueError("IMF Fiscal Monitor apiBase must use HTTPS.")
	if not source_page.startswith("https://"):
		raise ValueError("IMF Fiscal Monitor sourcePage must use HTTPS.")
	if dataset_code != "FM":
		raise ValueError("IMF Fiscal Monitor datasetCode must be FM.")
	if not isinstance(provider, dict) or provider.get("id") != "imf-fiscal-monitor":
		raise ValueError("IMF Fiscal Monitor provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"IMF Fiscal Monitor provider metadata is missing {key}.")
	if not isinstance(minimum_projection_year, int) or minimum_projection_year < 2026:
		raise ValueError("IMF Fiscal Monitor minimumProjectionYear is invalid.")
	if not isinstance(minimum_latest_year, int) or minimum_latest_year < minimum_projection_year + 4:
		raise ValueError("IMF Fiscal Monitor minimumLatestYear is invalid.")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("IMF Fiscal Monitor config requires indicators.")

	ids: set[str] = set()
	slugs: set[str] = set()
	source_indicators: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("IMF Fiscal Monitor indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"IMF Fiscal Monitor indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		source_indicator = str(indicator["sourceIndicator"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate IMF Fiscal Monitor indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate IMF Fiscal Monitor indicator slug: {slug}")
		if source_indicator in source_indicators:
			raise ValueError(f"Duplicate IMF Fiscal Monitor source indicator: {source_indicator}")
		ids.add(indicator_id)
		slugs.add(slug)
		source_indicators.add(source_indicator)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or unit.get("id") != "percent":
			raise ValueError(f"IMF Fiscal Monitor indicator {indicator_id} must use percent.")
		if not str(unit.get("label", "")).strip():
			raise ValueError(f"IMF Fiscal Monitor indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"IMF Fiscal Monitor indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"IMF Fiscal Monitor indicator {indicator_id} requires at least one required area.")

	return payload


def load_datamapper_catalog(
	api_base: str,
	timeout: int,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
	countries_payload = common.fetch_json(f"{api_base}/countries", timeout)
	if not isinstance(countries_payload, dict) or not isinstance(countries_payload.get("countries"), dict):
		raise RuntimeError("Unexpected IMF DataMapper countries response.")
	country_codes = {
		str(code).strip().upper()
		for code in countries_payload["countries"]
		if str(code).strip()
	}
	if len(country_codes) < 200:
		raise RuntimeError(f"IMF DataMapper country catalog unexpectedly small: {len(country_codes)} entries.")
	for required in ("AUT", "DEU", "USA", "IND", "UVK"):
		if required not in country_codes:
			raise RuntimeError(f"IMF DataMapper country catalog sanity check failed: {required} is missing.")

	indicators_payload = common.fetch_json(f"{api_base}/indicators", timeout)
	if not isinstance(indicators_payload, dict) or not isinstance(indicators_payload.get("indicators"), dict):
		raise RuntimeError("Unexpected IMF DataMapper indicators response.")
	indicator_catalog = {
		str(code): metadata
		for code, metadata in indicators_payload["indicators"].items()
		if isinstance(metadata, dict)
	}
	if len(indicator_catalog) < 100:
		raise RuntimeError(f"IMF DataMapper indicator catalog unexpectedly small: {len(indicator_catalog)} entries.")
	return country_codes, indicator_catalog


def mapped_iso3(source_code: str) -> str:
	code = source_code.strip().upper()
	return ISO3_ALIASES.get(code, code)


def validate_source_metadata(
	config: dict[str, Any],
	indicator: dict[str, Any],
	metadata: dict[str, Any],
) -> dict[str, Any]:
	source_indicator = str(indicator["sourceIndicator"])
	dataset = str(metadata.get("dataset", "")).strip()
	source_label = str(metadata.get("source", "")).strip()
	unit = str(metadata.get("unit", "")).strip()
	last_modified = str(metadata.get("last-modified", "")).strip()
	projection_value = metadata.get("projection-year")
	try:
		projection_year = int(projection_value)
	except (TypeError, ValueError) as exc:
		raise RuntimeError(f"IMF DataMapper metadata has invalid projection year for {source_indicator}: {projection_value!r}") from exc

	if dataset != str(config["datasetCode"]):
		raise RuntimeError(f"IMF DataMapper dataset mismatch for {source_indicator}: {dataset!r} != {config['datasetCode']!r}")
	if "Fiscal Monitor" not in source_label:
		raise RuntimeError(f"IMF DataMapper source mismatch for {source_indicator}: {source_label!r}")
	if unit.lower().replace("percent", "%").replace(" ", "") not in {"%ofgdp", "%ofgdp"}:
		raise RuntimeError(f"IMF DataMapper unit mismatch for {source_indicator}: {unit!r}")
	if projection_year < int(config["minimumProjectionYear"]):
		raise RuntimeError(
			f"IMF Fiscal Monitor projection year for {source_indicator} is unexpectedly old: "
			f"{projection_year} < {config['minimumProjectionYear']}"
		)
	if not last_modified:
		raise RuntimeError(f"IMF DataMapper metadata is missing last-modified for {source_indicator}.")

	return {
		"dataset": dataset,
		"sourceLabel": source_label,
		"unit": unit,
		"lastModified": last_modified,
		"projectionYear": projection_year,
	}


def normalize_indicator(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_iso3: dict[str, str],
	country_codes: set[str],
	indicator_catalog: dict[str, dict[str, Any]],
	timeout: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
	api_base = str(config["apiBase"]).rstrip("/")
	provider = config["provider"]
	source_indicator = str(indicator["sourceIndicator"])
	metadata = indicator_catalog.get(source_indicator)
	if not isinstance(metadata, dict):
		raise RuntimeError(f"IMF DataMapper indicator catalog is missing {source_indicator}.")
	source_metadata = validate_source_metadata(config, indicator, metadata)
	projection_year = int(source_metadata["projectionYear"])

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
			raise RuntimeError(f"IMF Fiscal Monitor country series has invalid shape: {source_indicator} {code}.")
		area_id = area_by_iso3[iso3]
		for raw_year, raw_value in yearly_values.items():
			if raw_value is None:
				continue
			year_text = str(raw_year).strip()
			if len(year_text) != 4 or not year_text.isdigit():
				continue
			year = int(year_text)
			if year < 1900 or year > projection_year + 10:
				continue
			number = common.normalize_number(raw_value)
			if not math.isfinite(float(number)):
				raise RuntimeError(f"Non-finite IMF Fiscal Monitor value: {source_indicator} {code} {year}.")
			year_values = values_by_year.setdefault(year, {})
			if area_id in year_values:
				raise RuntimeError(f"Duplicate IMF Fiscal Monitor value for {indicator['id']} {year} {area_id}.")
			year_values[area_id] = number
			areas_with_any_value.add(area_id)

	if not values_by_year:
		raise RuntimeError(f"IMF Fiscal Monitor returned no mapped values for {indicator['id']}.")
	minimum_any = int(indicator["minAreasWithAnyValue"])
	if len(areas_with_any_value) < minimum_any:
		raise RuntimeError(
			f"IMF Fiscal Monitor coverage too small for {indicator['id']}: {len(areas_with_any_value)} areas, "
			f"expected at least {minimum_any}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in areas_with_any_value:
			raise RuntimeError(f"Required area {area_id} has no IMF Fiscal Monitor values for {indicator['id']}.")

	available_years = sorted(values_by_year)
	latest_year = available_years[-1]
	if latest_year < int(config["minimumLatestYear"]):
		raise RuntimeError(
			f"IMF Fiscal Monitor latest year for {indicator['id']} is too old: {latest_year}, "
			f"expected at least {config['minimumLatestYear']}."
		)

	minimum_default_coverage = int(indicator["minAreasInDefaultYear"])
	required_areas = [str(area_id) for area_id in indicator["requiredAreas"]]
	eligible_default_years = [
		year
		for year in available_years
		if year < projection_year
		and len(values_by_year[year]) >= minimum_default_coverage
		and all(area_id in values_by_year[year] for area_id in required_areas)
	]
	if not eligible_default_years:
		raise RuntimeError(
			f"IMF Fiscal Monitor has no sufficiently complete pre-projection year for {indicator['id']}: "
			f"expected at least {minimum_default_coverage} areas and all required areas."
		)
	default_year = eligible_default_years[-1]
	if projection_year - default_year > 2:
		raise RuntimeError(
			f"IMF Fiscal Monitor default year for {indicator['id']} is unexpectedly old: {default_year}."
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
		"classification": indicator["classification"],
	}

	result = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": indicator_metadata,
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"indicator": source_indicator,
			"sourceRelease": source_metadata["sourceLabel"],
			"lastModified": source_metadata["lastModified"],
			"projectionStartYear": projection_year,
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": f"https://www.imf.org/external/datamapper/{source_indicator}@FM",
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
			"projectionStartYear": projection_year,
		},
		"values": sorted_values,
	}
	print(
		f"  mapped={len(areas_with_any_value)} "
		f"years={available_years[0]}-{latest_year} "
		f"defaultYear={default_year} "
		f"defaultCoverage={len(values_by_year[default_year])} "
		f"projectionStartYear={projection_year} "
		f"ignoredCodes={len(ignored_codes)}"
	)
	if ignored_codes:
		print(f"  ignored country codes: {', '.join(sorted(ignored_codes))}")
	return result, source_metadata


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	country_codes, indicator_catalog = load_datamapper_catalog(str(config["apiBase"]).rstrip("/"), args.timeout)
	now = common.utc_now()
	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	source_metadata_rows: list[dict[str, Any]] = []
	for indicator in config["indicators"]:
		payload, source_metadata = normalize_indicator(
			config,
			indicator,
			area_by_iso3,
			country_codes,
			indicator_catalog,
			args.timeout,
		)
		indicator_payloads.append((indicator, payload))
		source_metadata_rows.append(source_metadata)

	projection_years = {int(row["projectionYear"]) for row in source_metadata_rows}
	source_labels = {str(row["sourceLabel"]) for row in source_metadata_rows}
	if len(projection_years) != 1:
		raise RuntimeError(f"IMF Fiscal Monitor indicators disagree on projection year: {sorted(projection_years)}")
	if len(source_labels) != 1:
		raise RuntimeError(f"IMF Fiscal Monitor indicators disagree on source release: {sorted(source_labels)}")
	projection_year = next(iter(projection_years))
	source_label = next(iter(source_labels))
	last_modified = max(str(row["lastModified"]) for row in source_metadata_rows)

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
		index_indicators.append({
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
			"sourcePage": config["sourcePage"],
			"apiBase": config["apiBase"],
			"datasetCode": config["datasetCode"],
			"sourceRelease": source_label,
			"lastModified": last_modified,
			"projectionStartYear": projection_year,
			"projectionLabel": "IWF Fiscal Monitor",
			"defaultYearPolicy": "Latest sufficiently covered year before the IMF projection start year.",
		},
		"indicators": index_indicators,
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(output_dir / "index.json", common.build_global_index(provider_catalog))

	print(f"Built IMF Fiscal Monitor snapshot {snapshot}")
	print(f"Source release: {source_label}")
	print(f"Projection start year: {projection_year}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
