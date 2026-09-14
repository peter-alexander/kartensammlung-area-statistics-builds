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
DEFAULT_CONFIG = ROOT / "config" / "cru-cy-indicators.json"
DEFAULT_MAPPING = ROOT / "config" / "cru-cy-country-map.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
EXPECTED_VARIABLES = {"tmp", "tmx", "tmn", "pre", "dtr", "frs", "wet", "pet", "cld", "vap"}
EXPECTED_PET_UNAVAILABLE = {
	"BMU", "CCK", "COK", "CXR", "IOT", "KIR", "LCA", "MDV", "MHL", "NFK", "NRU", "TKL", "TUV",
}
EXPECTED_AUSTRIA_2025 = {
	"tmp": 8.4,
	"tmx": 13.2,
	"tmn": 3.7,
	"pre": 870.1,
	"dtr": 9.5,
	"frs": 133.5,
	"wet": 148.1,
	"pet": 2.1,
	"cld": 59.4,
	"vap": 8.5,
}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized CRU-CY country climate statistics.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--input-json", type=Path, required=True)
	parser.add_argument("--input-metadata", type=Path, required=True)
	parser.add_argument("--timeout", type=int, default=60)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.cru-cy-statistics/v1":
		raise ValueError("Invalid CRU-CY statistics config.")
	if payload.get("sourceVersion") != "4.10" or payload.get("sourceRun") != "2606161920":
		raise ValueError("Unexpected CRU-CY source version/run.")
	if payload.get("sourceStartYear") != 1901 or payload.get("sourceEndYear") != 2025:
		raise ValueError("Unexpected CRU-CY source period.")
	for key in (
		"familyPage", "sourcePage", "sourceRoot", "readmeUrl", "countryDefinitionsUrl", "releaseNotesUrl", "referenceDoi", "licenseUrl",
	):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"CRU-CY {key} must use HTTPS.")
	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "cru-cy":
		raise ValueError("Invalid CRU-CY provider metadata.")
	if provider.get("license") != "ODbL 1.0" or provider.get("licenseUrl") != payload.get("licenseUrl"):
		raise ValueError("CRU-CY provider must use audited ODbL 1.0 metadata.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 10:
		raise ValueError("CRU-CY config must contain exactly ten indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	variables: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("CRU-CY indicator entries must be objects.")
		for key in ("id", "slug", "sourceVariable", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"CRU-CY indicator is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		variable = str(indicator["sourceVariable"])
		if indicator_id in ids or slug in slugs or variable in variables:
			raise ValueError(f"Duplicate CRU-CY indicator identity: {indicator_id}")
		ids.add(indicator_id)
		slugs.add(slug)
		variables.add(variable)
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not all(str(unit.get(key, "")).strip() for key in ("id", "label", "symbol")):
			raise ValueError(f"CRU-CY indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		range_value = indicator.get("sanityRange")
		if not isinstance(range_value, list) or len(range_value) != 2 or not all(isinstance(value, (int, float)) for value in range_value):
			raise ValueError(f"CRU-CY indicator {indicator_id} has invalid sanityRange.")
		if float(range_value[0]) >= float(range_value[1]):
			raise ValueError(f"CRU-CY indicator {indicator_id} sanityRange is not increasing.")
		minimum_coverage = int(indicator.get("minimumLatestCoverage", 0))
		if minimum_coverage < 200:
			raise ValueError(f"CRU-CY indicator {indicator_id} has too-small coverage threshold.")
	if variables != EXPECTED_VARIABLES:
		raise ValueError(f"Unexpected CRU-CY source variables: {variables}")
	required = payload.get("requiredAreas")
	if not isinstance(required, list) or not required:
		raise ValueError("CRU-CY requiredAreas is missing.")
	return payload


def validate_mapping(payload: Any, config: dict[str, Any]) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.cru-cy-country-map/v1":
		raise ValueError("Invalid CRU-CY country mapping.")
	if payload.get("sourceVersion") != config["sourceVersion"]:
		raise ValueError("CRU-CY mapping version differs from config.")
	if payload.get("sourceYears") != [config["sourceStartYear"], config["sourceEndYear"]]:
		raise ValueError("CRU-CY mapping period differs from config.")
	name_to_iso3 = payload.get("sourceNameToIso3")
	if not isinstance(name_to_iso3, dict) or len(name_to_iso3) != 218:
		raise ValueError("CRU-CY country mapping must contain exactly 218 direct mappings.")
	if len(set(name_to_iso3.values())) != 218:
		raise ValueError("CRU-CY country mapping must be one-to-one.")
	if int(payload.get("sourceAreaCount", -1)) != 292 or int(payload.get("mappedAreaCount", -1)) != 218:
		raise ValueError("CRU-CY audited source/mapped area counts changed.")
	excluded = payload.get("excludedSourceAreas")
	missing = payload.get("expectedMissingRegistryIso3")
	if not isinstance(excluded, list) or len(excluded) != 73:
		raise ValueError("CRU-CY excluded source-area set changed.")
	if not isinstance(missing, list) or len(missing) != 32:
		raise ValueError("CRU-CY expected registry-gap set changed.")
	return payload


def validate_download_metadata(path: Path, config: dict[str, Any], mapping: dict[str, Any], source_bytes: bytes) -> dict[str, Any]:
	payload = common.read_json_path(path)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.cru-cy-download-metadata/v1":
		raise RuntimeError("Invalid CRU-CY download metadata.")
	if payload.get("sourceVersion") != config["sourceVersion"] or payload.get("sourceRun") != config["sourceRun"]:
		raise RuntimeError("CRU-CY download source version/run differs from config.")
	if payload.get("sourceYears") != [config["sourceStartYear"], config["sourceEndYear"]]:
		raise RuntimeError("CRU-CY download source period differs from config.")
	if int(payload.get("sourceAreaCount", -1)) != int(mapping["sourceAreaCount"]):
		raise RuntimeError("CRU-CY download source-area count differs from mapping.")
	if int(payload.get("mappedAreaCount", -1)) != int(mapping["mappedAreaCount"]):
		raise RuntimeError("CRU-CY download mapped-area count differs from mapping.")
	if int(payload.get("excludedSourceAreaCount", -1)) != len(mapping["excludedSourceAreas"]):
		raise RuntimeError("CRU-CY excluded source-area count differs from mapping.")
	if int(payload.get("downloadedFileCount", -1)) != 2180:
		raise RuntimeError(f"Unexpected CRU-CY downloaded file count: {payload.get('downloadedFileCount')}")
	if set(payload.get("variables") or []) != EXPECTED_VARIABLES:
		raise RuntimeError("CRU-CY download variable set differs from audited set.")
	input_file = payload.get("inputFile") or {}
	actual_hash = hashlib.sha256(source_bytes).hexdigest()
	if int(input_file.get("bytes", -1)) != len(source_bytes) or input_file.get("sha256") != actual_hash:
		raise RuntimeError("CRU-CY input file hash/size differs from downloader metadata.")
	return payload


def parse_source(
	config: dict[str, Any],
	mapping: dict[str, Any],
	input_json: Path,
	area_by_iso3: dict[str, str],
) -> tuple[dict[str, dict[int, dict[str, float]]], dict[str, Any]]:
	payload = common.read_json_path(input_json)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.cru-cy-download/v1":
		raise RuntimeError("Invalid CRU-CY input JSON.")
	if payload.get("sourceVersion") != config["sourceVersion"] or payload.get("sourceRun") != config["sourceRun"]:
		raise RuntimeError("CRU-CY input source version/run differs from config.")
	if payload.get("sourceYears") != [config["sourceStartYear"], config["sourceEndYear"]]:
		raise RuntimeError("CRU-CY input source period differs from config.")
	if payload.get("sourceRoot") != config["sourceRoot"]:
		raise RuntimeError("CRU-CY input source root differs from config.")
	variables = payload.get("variables")
	if not isinstance(variables, dict) or set(variables) != EXPECTED_VARIABLES:
		raise RuntimeError("CRU-CY input variable structure changed.")

	mapped_iso3 = {str(value) for value in mapping["sourceNameToIso3"].values()}
	if not mapped_iso3.issubset(area_by_iso3):
		raise RuntimeError(f"CRU-CY mapping contains ISO3 outside registry: {sorted(mapped_iso3 - set(area_by_iso3))}")
	registry_gap = sorted(set(area_by_iso3) - mapped_iso3)
	if registry_gap != mapping["expectedMissingRegistryIso3"]:
		raise RuntimeError(f"CRU-CY registry gap changed: {registry_gap}")

	indicator_by_variable = {str(indicator["sourceVariable"]): indicator for indicator in config["indicators"]}
	values: dict[str, dict[int, dict[str, float]]] = {
		str(indicator["id"]): defaultdict(dict)
		for indicator in config["indicators"]
	}
	start_year = int(config["sourceStartYear"])
	end_year = int(config["sourceEndYear"])
	for variable in sorted(EXPECTED_VARIABLES):
		indicator = indicator_by_variable[variable]
		indicator_id = str(indicator["id"])
		minimum_value, maximum_value = (float(value) for value in indicator["sanityRange"])
		series_by_iso3 = variables[variable]
		if not isinstance(series_by_iso3, dict) or set(series_by_iso3) != mapped_iso3:
			raise RuntimeError(f"CRU-CY mapped ISO3 set changed for {variable}.")
		for iso3, series in series_by_iso3.items():
			if not isinstance(series, dict):
				raise RuntimeError(f"Invalid CRU-CY series for {variable}/{iso3}")
			area_id = area_by_iso3[iso3]
			expected_year_count = 0 if variable == "pet" and iso3 in EXPECTED_PET_UNAVAILABLE else end_year - start_year + 1
			if len(series) != expected_year_count:
				raise RuntimeError(f"Unexpected CRU-CY year count for {variable}/{iso3}: {len(series)} != {expected_year_count}")
			for year_text, raw_value in series.items():
				try:
					year = int(year_text)
					value = float(raw_value)
				except (TypeError, ValueError) as error:
					raise RuntimeError(f"Invalid CRU-CY value for {variable}/{iso3}/{year_text}") from error
				if year < start_year or year > end_year:
					raise RuntimeError(f"CRU-CY year outside configured period: {variable}/{iso3}/{year}")
				if not math.isfinite(value) or value < minimum_value or value > maximum_value:
					raise RuntimeError(f"CRU-CY value outside sanity range for {variable}/{iso3}/{year}: {value}")
				if area_id in values[indicator_id][year]:
					raise RuntimeError(f"Duplicate CRU-CY observation for {indicator_id}/{year}/{area_id}")
				values[indicator_id][year][area_id] = value

	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		variable = str(indicator["sourceVariable"])
		expected_coverage = 205 if variable == "pet" else 218
		for year in range(start_year, end_year + 1):
			if len(values[indicator_id].get(year, {})) != expected_coverage:
				raise RuntimeError(
					f"CRU-CY annual coverage changed for {indicator_id}/{year}: "
					f"{len(values[indicator_id].get(year, {}))} != {expected_coverage}"
				)
	return values, {
		"mappedAreas": len(mapped_iso3),
		"registryMissingIso3": registry_gap,
		"sourceAreaCount": int(mapping["sourceAreaCount"]),
		"excludedSourceAreaCount": len(mapping["excludedSourceAreas"]),
		"minimumYear": start_year,
		"maximumYear": end_year,
	}


def validate_regression_values(config: dict[str, Any], values: dict[str, dict[int, dict[str, float]]]) -> None:
	indicator_by_variable = {str(indicator["sourceVariable"]): str(indicator["id"]) for indicator in config["indicators"]}
	for variable, expected in EXPECTED_AUSTRIA_2025.items():
		actual = values[indicator_by_variable[variable]][2025]["country:AUT"]
		if abs(actual - expected) > 1e-9:
			raise RuntimeError(f"CRU-CY Austria 2025 audit value changed for {variable}: {actual} != {expected}")


def build_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	provider: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_year: dict[int, dict[str, float]],
	source_file: dict[str, Any],
) -> dict[str, Any]:
	available_years = sorted(year for year, year_values in values_by_year.items() if year_values)
	if available_years != list(range(int(config["sourceStartYear"]), int(config["sourceEndYear"]) + 1)):
		raise RuntimeError(f"CRU-CY available years changed for {indicator['id']}")
	default_year = int(config["sourceEndYear"])
	mapped_areas = {area for year_values in values_by_year.values() for area in year_values}
	if len(values_by_year[default_year]) < int(indicator["minimumLatestCoverage"]):
		raise RuntimeError(f"CRU-CY latest-year coverage too small for {indicator['id']}")
	for required in config["requiredAreas"]:
		if required not in values_by_year[default_year]:
			raise RuntimeError(f"CRU-CY required area missing in latest year for {indicator['id']}: {required}")
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
			"sourceRoot": config["sourceRoot"],
			"readmeUrl": config["readmeUrl"],
			"countryDefinitionsUrl": config["countryDefinitionsUrl"],
			"releaseNotesUrl": config["releaseNotesUrl"],
			"referenceDoi": config["referenceDoi"],
			"sourceVersion": config["sourceVersion"],
			"sourceRun": config["sourceRun"],
			"sourceVariable": indicator["sourceVariable"],
			"aggregation": "CRU-CY area-weighted country average",
			"inputFile": source_file,
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(mapped_areas),
			"latestYear": default_year,
			"areasInLatestYear": len(values_by_year[default_year]),
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
	mapping = validate_mapping(common.read_json_path(args.mapping), config)
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("CRU-CY provider is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	if len(area_by_iso3) != 250:
		raise RuntimeError(f"Expected 250 registry countries, got {len(area_by_iso3)}")
	source_bytes = args.input_json.read_bytes()
	download_metadata = validate_download_metadata(args.input_metadata, config, mapping, source_bytes)
	source_file = {
		"fileName": args.input_json.name,
		"bytes": len(source_bytes),
		"sha256": hashlib.sha256(source_bytes).hexdigest(),
	}
	values, source_info = parse_source(config, mapping, args.input_json, area_by_iso3)
	validate_regression_values(config, values)

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload = build_payload(
			config,
			indicator,
			provider,
			area_by_iso3,
			values[str(indicator["id"])],
			source_file,
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
			"sourceRoot": config["sourceRoot"],
			"readmeUrl": config["readmeUrl"],
			"countryDefinitionsUrl": config["countryDefinitionsUrl"],
			"releaseNotesUrl": config["releaseNotesUrl"],
			"referenceDoi": config["referenceDoi"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"sourceVersion": config["sourceVersion"],
			"sourceRun": config["sourceRun"],
			"sourceYearRange": [source_info["minimumYear"], source_info["maximumYear"]],
			"sourceAreaCount": source_info["sourceAreaCount"],
			"mappedAreas": source_info["mappedAreas"],
			"excludedSourceAreaCount": source_info["excludedSourceAreaCount"],
			"registryMissingIso3": source_info["registryMissingIso3"],
			"inputFile": source_file,
		},
		"indicators": index_indicators,
		"notes": [
			"CRU-CY consists of country-averaged time series calculated by the Climatic Research Unit from CRU-TS. CRU states that the country spatial means are area-weighted.",
			"Production uses only 218 direct CRU-CY country/territory equivalents that were explicitly mapped to the Kartensammlung registry. CRU subregions and island fragments are not combined locally into synthetic country values.",
			"The source is licensed under ODbL 1.0. The CRU-derived database remains separately identified and machine-readable within the Kartensammlung statistics collection; attribution is Climatic Research Unit, University of East Anglia.",
			"CRU-TS prioritizes complete time series and may substitute 1961-1990 monthly climatological means where observations are unavailable. This source characteristic also applies to the derived CRU-CY series and must be considered when interpreting sparse-data regions and long-term trends.",
			"TMX and TMN are annual means of daily maximum and minimum temperatures, not annual record extremes. They therefore complement, rather than duplicate, the ERA5 TXx and TNn extreme indices.",
			"PRE uses the annual ANN field, which is the sum of the twelve monthly precipitation amounts. WET counts days with at least 0.1 mm precipitation. FRS is statistically derived from minimum-temperature information. PET is the annual mean daily potential evapotranspiration rate.",
			"Nine variables have complete annual values for all 218 mapped areas from 1901 through 2025. PET is unavailable for 13 mapped small-island areas in every year and therefore has 205-area coverage.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built CRU-CY snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")
	print(f"Years: {source_info['minimumYear']}-{source_info['maximumYear']} mapped areas: {source_info['mappedAreas']}")


if __name__ == "__main__":
	main()
