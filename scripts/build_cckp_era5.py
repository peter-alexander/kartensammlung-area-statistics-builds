#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "cckp-era5-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
EXPECTED_VARIABLES = {"tas", "pr", "txx", "tnn", "fd", "tr", "rx1day", "rx5day"}
EXPECTED_SOURCE_COUNTRIES = 246
AUDITED_MISSING_AREAS = {"country:ATA", "country:ESH", "country:FLK", "country:SGS"}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized World Bank CCKP ERA5 country climate statistics.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--input-json", type=Path, required=True)
	parser.add_argument("--input-metadata", type=Path, required=True)
	parser.add_argument("--timeout", type=int, default=60)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.cckp-era5-statistics/v1":
		raise ValueError("Invalid CCKP ERA5 statistics config.")
	for key in ("apiBaseUrl", "sourcePage", "metadataPage", "documentationPage", "dataReferenceDoi", "licenseUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"CCKP {key} must use HTTPS.")
	if payload.get("collection") != "era5-x0.25" or payload.get("scenario") != "historical_era5":
		raise ValueError("Unexpected CCKP ERA5 collection/scenario.")
	if payload.get("aggregation") != "annual" or payload.get("productType") != "timeseries" or payload.get("statistic") != "mean":
		raise ValueError("Unexpected CCKP ERA5 aggregation/product/statistic.")
	if payload.get("startYear") != 1950 or int(payload.get("minimumLatestYear", 0)) < 2025:
		raise ValueError("Unexpected CCKP ERA5 time coverage policy.")
	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "world-bank-cckp-era5":
		raise ValueError("Invalid CCKP provider metadata.")
	if provider.get("license") != "CC BY 4.0" or provider.get("licenseUrl") != payload.get("licenseUrl"):
		raise ValueError("CCKP provider must use audited CC BY 4.0 license metadata.")
	if payload.get("areaAliases") != {"KSV": "XKX"}:
		raise ValueError("CCKP areaAliases must explicitly map KSV to XKX.")
	if set(payload.get("knownMissingAreas") or []) != AUDITED_MISSING_AREAS:
		raise ValueError("CCKP known missing areas changed unexpectedly.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 8:
		raise ValueError("CCKP config must contain exactly eight audited indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	variables: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("CCKP indicator entries must be objects.")
		for key in ("id", "slug", "sourceVariable", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"CCKP indicator is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		variable = str(indicator["sourceVariable"])
		if indicator_id in ids or slug in slugs or variable in variables:
			raise ValueError(f"Duplicate CCKP indicator identity: {indicator_id}")
		ids.add(indicator_id)
		slugs.add(slug)
		variables.add(variable)
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not all(str(unit.get(key, "")).strip() for key in ("id", "label", "symbol")):
			raise ValueError(f"CCKP indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		range_value = indicator.get("sanityRange")
		if not isinstance(range_value, list) or len(range_value) != 2 or not all(isinstance(value, (int, float)) for value in range_value):
			raise ValueError(f"CCKP indicator {indicator_id} has invalid sanityRange.")
		if float(range_value[0]) >= float(range_value[1]):
			raise ValueError(f"CCKP indicator {indicator_id} sanityRange is not increasing.")
	if variables != EXPECTED_VARIABLES:
		raise ValueError(f"CCKP source variable set changed: {variables}")
	if int(payload.get("minimumAreasWithAnyValue", 0)) < 240 or int(payload.get("minimumAreasInDefaultYear", 0)) < 240:
		raise ValueError("CCKP minimum coverage thresholds are too small.")
	required = payload.get("requiredAreas")
	if not isinstance(required, list) or not required:
		raise ValueError("CCKP requiredAreas is missing.")
	return payload


def validate_download_metadata(path: Path, config: dict[str, Any], source_bytes: bytes) -> dict[str, Any]:
	payload = common.read_json_path(path)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.cckp-era5-download/v1":
		raise RuntimeError("Invalid CCKP download metadata.")
	if payload.get("collection") != config["collection"] or payload.get("scenario") != config["scenario"]:
		raise RuntimeError("CCKP download collection/scenario differs from config.")
	if payload.get("aggregation") != config["aggregation"] or payload.get("statistic") != config["statistic"]:
		raise RuntimeError("CCKP download aggregation/statistic differs from config.")
	if set(payload.get("variables") or []) != EXPECTED_VARIABLES:
		raise RuntimeError("CCKP download variables differ from audited set.")
	if int(payload.get("startYear", -1)) != int(config["startYear"]):
		raise RuntimeError("CCKP download start year differs from config.")
	end_year = int(payload.get("endYear", -1))
	if end_year < int(config["minimumLatestYear"]):
		raise RuntimeError(f"CCKP download latest year too old: {end_year}")
	if payload.get("latestKey") != f"{end_year}-07":
		raise RuntimeError("CCKP download latest key is inconsistent with end year.")
	if int(payload.get("countryCount", -1)) != EXPECTED_SOURCE_COUNTRIES:
		raise RuntimeError(f"CCKP audited country count changed: {payload.get('countryCount')}")
	if int(payload.get("seriesLength", -1)) != end_year - int(config["startYear"]) + 1:
		raise RuntimeError("CCKP download series length is inconsistent.")
	input_file = payload.get("inputFile") or {}
	actual_hash = hashlib.sha256(source_bytes).hexdigest()
	if int(input_file.get("bytes", -1)) != len(source_bytes) or input_file.get("sha256") != actual_hash:
		raise RuntimeError("CCKP input file hash/size differs from downloader metadata.")
	return payload


def parse_source(
	config: dict[str, Any],
	input_json: Path,
	area_by_iso3: dict[str, str],
	download_metadata: dict[str, Any],
) -> tuple[dict[str, dict[int, dict[str, float]]], dict[str, Any]]:
	payload = common.read_json_path(input_json)
	if not isinstance(payload, dict):
		raise RuntimeError("CCKP input JSON must be an object.")
	metadata = payload.get("metadata")
	if not isinstance(metadata, dict) or metadata.get("status") != "success" or metadata.get("messages") not in ([], None):
		raise RuntimeError(f"CCKP API metadata is not successful: {metadata!r}")
	data = payload.get("data")
	if not isinstance(data, dict) or set(data) != EXPECTED_VARIABLES:
		raise RuntimeError("CCKP API variable structure changed.")

	indicator_by_variable = {str(indicator["sourceVariable"]): indicator for indicator in config["indicators"]}
	aliases = {str(source): str(target) for source, target in config["areaAliases"].items()}
	values: dict[str, dict[int, dict[str, float]]] = {
		str(indicator["id"]): defaultdict(dict)
		for indicator in config["indicators"]
	}
	source_codes: set[str] = set()
	mapped_areas: set[str] = set()
	minimum_year: int | None = None
	maximum_year: int | None = None

	for variable in sorted(EXPECTED_VARIABLES):
		indicator = indicator_by_variable[variable]
		indicator_id = str(indicator["id"])
		minimum_value, maximum_value = (float(value) for value in indicator["sanityRange"])
		countries = data[variable]
		if not isinstance(countries, dict) or len(countries) != EXPECTED_SOURCE_COUNTRIES:
			raise RuntimeError(f"CCKP country count changed for {variable}: {len(countries) if isinstance(countries, dict) else 'invalid'}")
		for source_code, series in countries.items():
			if not isinstance(source_code, str) or len(source_code) != 3 or not isinstance(series, dict):
				raise RuntimeError(f"Invalid CCKP series identity for {variable}: {source_code!r}")
			source_codes.add(source_code)
			mapped_code = aliases.get(source_code, source_code)
			area_id = area_by_iso3.get(mapped_code)
			if area_id is None:
				raise RuntimeError(f"Unmapped CCKP country code: {source_code}")
			mapped_areas.add(area_id)
			for date_key, raw_value in series.items():
				if not isinstance(date_key, str) or len(date_key) != 7 or date_key[4:] != "-07":
					raise RuntimeError(f"Unexpected CCKP annual date key: {date_key!r}")
				try:
					year = int(date_key[:4])
					value = float(raw_value)
				except (TypeError, ValueError) as error:
					raise RuntimeError(f"Invalid CCKP value for {variable}/{source_code}/{date_key}") from error
				if not math.isfinite(value) or value < minimum_value or value > maximum_value:
					raise RuntimeError(f"CCKP value outside sanity range for {variable}/{source_code}/{date_key}: {value}")
				if area_id in values[indicator_id][year]:
					raise RuntimeError(f"Duplicate CCKP mapped observation for {indicator_id}/{year}/{area_id}")
				values[indicator_id][year][area_id] = round(value, 6)
				minimum_year = year if minimum_year is None else min(minimum_year, year)
				maximum_year = year if maximum_year is None else max(maximum_year, year)

	if len(source_codes) != EXPECTED_SOURCE_COUNTRIES or len(mapped_areas) != EXPECTED_SOURCE_COUNTRIES:
		raise RuntimeError(f"CCKP source/mapped area counts changed: {len(source_codes)}/{len(mapped_areas)}")
	if "KSV" not in source_codes or "XKX" in source_codes:
		raise RuntimeError("CCKP Kosovo source code policy changed unexpectedly.")
	if minimum_year != int(config["startYear"]) or maximum_year != int(download_metadata["endYear"]):
		raise RuntimeError(f"CCKP source year range changed: {minimum_year}-{maximum_year}")
	return values, {
		"sourceCodes": len(source_codes),
		"mappedAreas": len(mapped_areas),
		"minimumYear": minimum_year,
		"maximumYear": maximum_year,
	}


def choose_default_year(config: dict[str, Any], values_by_year: dict[int, dict[str, float]]) -> int:
	required = set(str(value) for value in config["requiredAreas"])
	eligible = [
		year
		for year, year_values in values_by_year.items()
		if len(year_values) >= int(config["minimumAreasInDefaultYear"])
		and required.issubset(year_values)
	]
	if not eligible:
		raise RuntimeError("No sufficiently complete CCKP default year.")
	return max(eligible)


def validate_audited_values(config: dict[str, Any], values: dict[str, dict[int, dict[str, float]]], latest_year: int) -> None:
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		year_values = values[indicator_id].get(latest_year, {})
		if len(year_values) != EXPECTED_SOURCE_COUNTRIES:
			raise RuntimeError(f"CCKP latest-year coverage changed for {indicator_id}: {len(year_values)}")
		for required in config["requiredAreas"]:
			if required not in year_values:
				raise RuntimeError(f"CCKP latest-year required area missing for {indicator_id}: {required}")

	if latest_year == 2025:
		expected = {
			"tas": 7.86,
			"pr": 1080.68,
			"txx": 29.94,
			"tnn": -12.36,
			"fd": 120.3,
			"tr": 0.25,
			"rx1day": 29.69,
			"rx5day": 71.18,
		}
		for indicator in config["indicators"]:
			variable = str(indicator["sourceVariable"])
			actual = values[str(indicator["id"])][2025]["country:AUT"]
			if abs(actual - expected[variable]) > 0.000001:
				raise RuntimeError(f"CCKP Austria 2025 audit value changed for {variable}: {actual} != {expected[variable]}")


def build_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	provider: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_year: dict[int, dict[str, float]],
	source_file: dict[str, Any],
	download_metadata: dict[str, Any],
) -> dict[str, Any]:
	available_years = sorted(year for year, year_values in values_by_year.items() if year_values)
	if not available_years:
		raise RuntimeError(f"CCKP returned no values for {indicator['id']}.")
	latest_year = available_years[-1]
	if latest_year < int(config["minimumLatestYear"]):
		raise RuntimeError(f"CCKP latest year too old for {indicator['id']}: {latest_year}")
	mapped_areas = {area for year_values in values_by_year.values() for area in year_values}
	if len(mapped_areas) < int(config["minimumAreasWithAnyValue"]):
		raise RuntimeError(f"CCKP coverage too small for {indicator['id']}: {len(mapped_areas)}")
	default_year = choose_default_year(config, values_by_year)
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
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourcePage"],
			"metadataUrl": config["metadataPage"],
			"documentationUrl": config["documentationPage"],
			"dataReferenceDoi": config["dataReferenceDoi"],
			"collection": config["collection"],
			"scenario": config["scenario"],
			"aggregation": config["aggregation"],
			"statistic": config["statistic"],
			"sourceVariable": indicator["sourceVariable"],
			"mappingAliases": config["areaAliases"],
			"requestUrl": download_metadata["requestUrl"],
			"inputFile": source_file,
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(mapped_areas),
			"latestYear": latest_year,
			"areasInLatestYear": len(values_by_year[latest_year]),
			"areasInDefaultYear": len(values_by_year[default_year]),
		},
		"values": {
			str(year): {
				area_id: values_by_year[year][area_id]
				for area_id in sorted(values_by_year[year])
			}
			for year in available_years
		},
	}


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("CCKP provider is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	if len(area_by_iso3) != 250:
		raise RuntimeError(f"Expected 250 registry countries, got {len(area_by_iso3)}")
	source_bytes = args.input_json.read_bytes()
	download_metadata = validate_download_metadata(args.input_metadata, config, source_bytes)
	source_file = {
		"fileName": args.input_json.name,
		"bytes": len(source_bytes),
		"sha256": hashlib.sha256(source_bytes).hexdigest(),
	}
	values, source_info = parse_source(config, args.input_json, area_by_iso3, download_metadata)
	latest_year = int(source_info["maximumYear"])
	validate_audited_values(config, values, latest_year)

	missing_areas = set(area_by_iso3.values()) - {
		area
		for indicator_values in values.values()
		for year_values in indicator_values.values()
		for area in year_values
	}
	if missing_areas != AUDITED_MISSING_AREAS:
		raise RuntimeError(f"CCKP registry coverage gap changed unexpectedly: {sorted(missing_areas)}")

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload = build_payload(
			config,
			indicator,
			provider,
			area_by_iso3,
			values[str(indicator["id"])],
			source_file,
			download_metadata,
		)
		print(
			f"{indicator['id']}: years={payload['availableYears'][0]}-{payload['coverage']['latestYear']} "
			f"areas={payload['coverage']['areasWithAnyValue']} default={payload['defaultYear']} "
			f"defaultCoverage={payload['coverage']['areasInDefaultYear']}"
		)
		indicator_payloads.append((indicator, payload))

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
			"sourceVariable": indicator["sourceVariable"],
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
	retrieved_at = str(download_metadata.get("retrievedAt", "")).strip()
	if not retrieved_at:
		retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": retrieved_at,
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"dataset": {
			"title": provider["dataset"],
			"url": config["sourcePage"],
			"metadataUrl": config["metadataPage"],
			"documentationUrl": config["documentationPage"],
			"dataReferenceDoi": config["dataReferenceDoi"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"requestUrl": download_metadata["requestUrl"],
			"apiVersion": download_metadata.get("apiVersion"),
			"collection": config["collection"],
			"scenario": config["scenario"],
			"aggregation": config["aggregation"],
			"statistic": config["statistic"],
			"variables": download_metadata["variables"],
			"inputFile": source_file,
			"sourceCodes": source_info["sourceCodes"],
			"mappedAreas": source_info["mappedAreas"],
			"sourceYearRange": [source_info["minimumYear"], source_info["maximumYear"]],
		},
		"indicators": index_indicators,
		"notes": [
			"The source is the World Bank Climate Change Knowledge Portal country aggregation of the ERA5 reanalysis at 0.25-degree resolution.",
			"All eight indicators retain the complete annual country series from 1950 through the newest complete year exposed by the audited CCKP API; no local interpolation, extrapolation or cross-source fallback is applied.",
			"Kosovo is mapped explicitly from CCKP code KSV to registry code XKX/country:XKX. No fuzzy country matching is used.",
			"CCKP currently provides values for 246 of the 250 registry areas. Antarctica, Western Sahara, the Falkland Islands, and South Georgia and the South Sandwich Islands are intentionally left without values.",
			"Frost-day and tropical-night country values can be fractional because CCKP spatially aggregates the gridded ERA5 index over each country.",
			"TXx, TNn, Rx1day and Rx5day are country-aggregated annual climate indices, not individual weather-station records.",
			"The audited CCKP API currently returns tasmax and tasmin country time series identical to tas. Those two suspect API series are deliberately excluded until the source behavior is clarified.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built CCKP ERA5 snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")
	print(f"Years: {source_info['minimumYear']}-{source_info['maximumYear']} mapped areas: {source_info['mappedAreas']}")


if __name__ == "__main__":
	main()
