#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import math
from pathlib import Path
from typing import Any

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "wid-inequality-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized WID.world country inequality statistics.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--input-csv", type=Path, required=True)
	parser.add_argument("--input-metadata", type=Path, required=True)
	parser.add_argument("--timeout", type=int, default=60)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.wid-inequality-statistics/v1":
		raise ValueError("Invalid WID inequality statistics config.")
	for key in ("sourcePage", "methodologyPage", "codesDictionaryUrl", "packagePage"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"WID {key} must use HTTPS.")
	if not str(payload.get("expectedPackageVersion", "")).strip():
		raise ValueError("WID expectedPackageVersion is required.")
	start_year = payload.get("expectedStartYear")
	latest_year = payload.get("minimumLatestYear")
	minimum_quality = payload.get("minimumQuality")
	if not isinstance(start_year, int) or start_year < 1900:
		raise ValueError("WID expectedStartYear is invalid.")
	if not isinstance(latest_year, int) or latest_year < start_year:
		raise ValueError("WID minimumLatestYear is invalid.")
	if not isinstance(minimum_quality, int) or not 0 <= minimum_quality <= 5:
		raise ValueError("WID minimumQuality must be an integer from 0 to 5.")
	if str(payload.get("ageCode", "")) != "992" or str(payload.get("populationCode", "")) != "j":
		raise ValueError("WID age/population concept changed unexpectedly.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "wid-inequality":
		raise ValueError("WID provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"WID provider metadata is missing {key}.")

	aliases = payload.get("areaAliases")
	if not isinstance(aliases, dict):
		raise ValueError("WID areaAliases must be an object.")
	for source, iso3 in aliases.items():
		if not str(source).strip() or len(str(iso3).strip()) != 3:
			raise ValueError(f"Invalid WID area alias: {source!r} -> {iso3!r}")
	ignored_codes = payload.get("ignoredAreaCodes")
	ignored_suffixes = payload.get("ignoredAreaSuffixes")
	if not isinstance(ignored_codes, list) or any(not str(value).strip() for value in ignored_codes):
		raise ValueError("WID ignoredAreaCodes is invalid.")
	if not isinstance(ignored_suffixes, list) or any(not str(value).strip() for value in ignored_suffixes):
		raise ValueError("WID ignoredAreaSuffixes is invalid.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("WID config requires indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	source_keys: set[tuple[str, str]] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("WID indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "sourceVariable", "percentile", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"WID indicator is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		source_key = (str(indicator["sourceVariable"]), str(indicator["percentile"]))
		if indicator_id in ids or slug in slugs or source_key in source_keys:
			raise ValueError(f"Duplicate WID indicator identity: {indicator_id}")
		ids.add(indicator_id)
		slugs.add(slug)
		source_keys.add(source_key)
		if str(indicator["sourceVariable"]) != f"{indicator['sourceIndicator']}{payload['ageCode']}{payload['populationCode']}":
			raise ValueError(f"WID sourceVariable does not match concept codes for {indicator_id}.")
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"WID indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"WID indicator {indicator_id} has invalid {key}.")
		required = indicator.get("requiredAreas")
		if not isinstance(required, list) or not required or any(not str(value).strip() for value in required):
			raise ValueError(f"WID indicator {indicator_id} requires requiredAreas.")
	return payload


def load_iso2_mapping(registry_payload: dict[str, Any], area_by_iso3: dict[str, str]) -> dict[str, str]:
	result: dict[str, str] = {}
	for area in registry_payload.get("areas", []):
		if not isinstance(area, dict) or area.get("level") != "country":
			continue
		area_id = str(area.get("area_id", "")).strip()
		codes = area.get("codes") or {}
		iso2 = str(codes.get("iso2", "")).strip().upper()
		if not area_id or len(iso2) != 2:
			continue
		if iso2 in result and result[iso2] != area_id:
			raise RuntimeError(f"Duplicate ISO2 in country registry: {iso2}")
		result[iso2] = area_id

	for required in ("AT", "DE", "US", "IN", "CN", "ZA"):
		if required not in result:
			raise RuntimeError(f"Country registry is missing ISO2 {required}.")
	if area_by_iso3.get("XKX") != "country:XKX":
		raise RuntimeError("Country registry Kosovo sanity check failed.")
	return result


def load_download_metadata(path: Path, config: dict[str, Any]) -> dict[str, Any]:
	payload = common.read_json_path(path)
	if not isinstance(payload, dict):
		raise RuntimeError("WID download metadata must be an object.")
	package = payload.get("package") or {}
	if package.get("name") != "wid" or str(package.get("version", "")) != str(config["expectedPackageVersion"]):
		raise RuntimeError(f"Unexpected WID package metadata: {package!r}")
	query = payload.get("query") or {}
	if int(query.get("startYear", -1)) != int(config["expectedStartYear"]):
		raise RuntimeError("WID query start year differs from config.")
	if str(query.get("age", "")) != str(config["ageCode"]) or str(query.get("population", "")) != str(config["populationCode"]):
		raise RuntimeError("WID query population concept differs from config.")
	if query.get("metadata") is not False or query.get("qualityFilter") is not None:
		raise RuntimeError("WID production download must use metadata=FALSE and no source-side quality filter.")
	rows = payload.get("rows")
	if not isinstance(rows, int) or rows <= 0:
		raise RuntimeError("WID download metadata has invalid row count.")
	return payload


def should_ignore_area(code: str, config: dict[str, Any]) -> bool:
	if code in set(str(value).upper() for value in config["ignoredAreaCodes"]):
		return True
	return any(code.endswith(str(suffix).upper()) for suffix in config["ignoredAreaSuffixes"])


def parse_source(
	config: dict[str, Any],
	input_csv: Path,
	area_by_iso3: dict[str, str],
	iso2_to_area: dict[str, str],
) -> tuple[dict[str, dict[int, dict[str, float]]], dict[str, Any]]:
	by_key = {
		(str(indicator["sourceVariable"]), str(indicator["percentile"])): indicator
		for indicator in config["indicators"]
	}
	aliases = {str(source).upper(): str(iso3).upper() for source, iso3 in config["areaAliases"].items()}
	for source, iso3 in aliases.items():
		if iso3 not in area_by_iso3:
			raise RuntimeError(f"WID alias target missing from registry: {source} -> {iso3}")

	values: dict[str, dict[int, dict[str, float]]] = {
		str(indicator["id"]): defaultdict(dict)
		for indicator in config["indicators"]
	}
	quality_counts = Counter()
	retained_quality_counts = Counter()
	excluded_low_quality = Counter()
	ignored_area_counts = Counter()
	source_codes_seen: set[str] = set()
	mapped_codes_seen: set[str] = set()
	raw_rows = 0
	expected_rows = 0

	with input_csv.open(encoding="utf-8-sig", newline="") as handle:
		reader = csv.DictReader(handle)
		required_columns = {"country", "variable", "percentile", "year", "value", "data_quality"}
		if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
			raise RuntimeError(f"WID CSV columns changed: {reader.fieldnames}")
		for row_number, row in enumerate(reader, start=2):
			raw_rows += 1
			variable = str(row.get("variable") or "").strip()
			percentile = str(row.get("percentile") or "").strip()
			indicator = by_key.get((variable, percentile))
			if indicator is None:
				raise RuntimeError(
					f"Unexpected WID series at row {row_number}: variable={variable!r} percentile={percentile!r}"
				)
			expected_rows += 1
			code = str(row.get("country") or "").strip().upper()
			if not code:
				raise RuntimeError(f"WID row {row_number} has an empty area code.")
			source_codes_seen.add(code)

			try:
				year = int(str(row["year"]).strip())
				raw_value = float(row["value"])
				quality_float = float(row["data_quality"])
			except (TypeError, ValueError, KeyError) as error:
				raise RuntimeError(f"Invalid WID numeric fields at row {row_number}.") from error
			if not math.isfinite(raw_value) or not math.isfinite(quality_float):
				raise RuntimeError(f"Non-finite WID value at row {row_number}.")
			if not quality_float.is_integer() or not 0 <= quality_float <= 5:
				raise RuntimeError(f"Unexpected WID data_quality at row {row_number}: {quality_float}")
			quality = int(quality_float)
			quality_counts[quality] += 1

			if code in aliases:
				area_id = area_by_iso3[aliases[code]]
			else:
				area_id = iso2_to_area.get(code)
			if area_id is None:
				if should_ignore_area(code, config):
					ignored_area_counts[code] += 1
					continue
				raise RuntimeError(f"Unmapped WID country/area code with data: {code}")

			mapped_codes_seen.add(code)
			if quality < int(config["minimumQuality"]):
				excluded_low_quality[str(indicator["id"])] += 1
				continue

			if not int(config["expectedStartYear"]) <= year <= 2200:
				raise RuntimeError(f"WID year outside expected range at row {row_number}: {year}")
			if not 0 <= raw_value <= 1:
				raise RuntimeError(f"WID share/Gini outside 0..1 at row {row_number}: {raw_value}")
			value = round(raw_value * 100, 6)
			indicator_id = str(indicator["id"])
			existing = values[indicator_id][year].get(area_id)
			if existing is not None:
				raise RuntimeError(
					f"Duplicate WID observation after mapping for {indicator_id} {year} {area_id}: {existing} / {value}"
				)
			values[indicator_id][year][area_id] = value
			retained_quality_counts[quality] += 1

	if raw_rows == 0 or expected_rows != raw_rows:
		raise RuntimeError("WID CSV contains no complete expected observations.")
	if 0 not in quality_counts:
		raise RuntimeError("WID source unexpectedly contains no quality-0 observations; review quality model.")
	if not any(quality >= int(config["minimumQuality"]) for quality in quality_counts):
		raise RuntimeError("WID source contains no observations meeting the configured quality threshold.")

	source_info = {
		"rawRows": raw_rows,
		"sourceCodes": len(source_codes_seen),
		"mappedSourceCodes": len(mapped_codes_seen),
		"qualityCounts": {str(key): quality_counts[key] for key in sorted(quality_counts)},
		"retainedQualityCounts": {str(key): retained_quality_counts[key] for key in sorted(retained_quality_counts)},
		"excludedLowQualityRows": dict(sorted(excluded_low_quality.items())),
		"ignoredAreaCounts": dict(sorted(ignored_area_counts.items())),
	}
	return values, source_info


def choose_default_year(indicator: dict[str, Any], values_by_year: dict[int, dict[str, float]]) -> int:
	eligible = [
		year
		for year, year_values in values_by_year.items()
		if len(year_values) >= int(indicator["minAreasInDefaultYear"])
	]
	if not eligible:
		raise RuntimeError(f"No sufficiently complete WID default year for {indicator['id']}.")
	return max(eligible)


def build_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	provider: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_year: dict[int, dict[str, float]],
	source_info: dict[str, Any],
	source_file: dict[str, Any],
	download_metadata: dict[str, Any],
) -> dict[str, Any]:
	available_years = sorted(year for year, year_values in values_by_year.items() if year_values)
	if not available_years:
		raise RuntimeError(f"WID returned no retained values for {indicator['id']}.")
	if available_years[0] != int(config["expectedStartYear"]):
		raise RuntimeError(
			f"WID history for {indicator['id']} starts at {available_years[0]}, expected {config['expectedStartYear']}."
		)
	latest_year = available_years[-1]
	if latest_year < int(config["minimumLatestYear"]):
		raise RuntimeError(f"WID latest year too old for {indicator['id']}: {latest_year}")
	mapped_areas = {area for year_values in values_by_year.values() for area in year_values}
	if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(f"WID coverage too small for {indicator['id']}: {len(mapped_areas)}")
	default_year = choose_default_year(indicator, values_by_year)
	for area_id in indicator["requiredAreas"]:
		if area_id not in values_by_year[default_year]:
			raise RuntimeError(f"WID required area missing in default year {default_year}: {indicator['id']} {area_id}")

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
			"methodologyUrl": config["methodologyPage"],
			"codesDictionaryUrl": config["codesDictionaryUrl"],
			"package": download_metadata["package"],
			"sourceIndicator": indicator["sourceIndicator"],
			"sourceVariable": indicator["sourceVariable"],
			"percentile": indicator["percentile"],
			"ageCode": config["ageCode"],
			"populationCode": config["populationCode"],
			"minimumDataQuality": config["minimumQuality"],
			"mappingAliases": config["areaAliases"],
			"ignoredAreaCodes": config["ignoredAreaCodes"],
			"ignoredAreaSuffixes": config["ignoredAreaSuffixes"],
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
		raise RuntimeError("WID inequality provider is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	iso2_to_area = load_iso2_mapping(registry_payload, area_by_iso3)
	download_metadata = load_download_metadata(args.input_metadata, config)

	source_bytes = args.input_csv.read_bytes()
	source_file = {
		"fileName": args.input_csv.name,
		"bytes": len(source_bytes),
		"sha256": hashlib.sha256(source_bytes).hexdigest(),
	}
	values, source_info = parse_source(config, args.input_csv, area_by_iso3, iso2_to_area)
	if int(download_metadata["rows"]) != int(source_info["rawRows"]):
		raise RuntimeError(
			f"WID row count changed between downloader and builder: {download_metadata['rows']} != {source_info['rawRows']}"
		)

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload = build_payload(
			config,
			indicator,
			provider,
			area_by_iso3,
			values[str(indicator["id"])],
			source_info,
			source_file,
			download_metadata,
		)
		coverage = payload["coverage"]
		print(
			f"{indicator['id']}: years={payload['availableYears'][0]}-{coverage['latestYear']} "
			f"any={coverage['areasWithAnyValue']} default={payload['defaultYear']} "
			f"defaultCoverage={coverage['areasInDefaultYear']}"
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
			"sourceIndicator": indicator["sourceIndicator"],
			"sourceVariable": indicator["sourceVariable"],
			"sourcePercentile": indicator["percentile"],
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
			"methodologyUrl": config["methodologyPage"],
			"codesDictionaryUrl": config["codesDictionaryUrl"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"package": download_metadata["package"],
			"query": download_metadata["query"],
			"inputFile": source_file,
			"sourceRows": source_info["rawRows"],
			"sourceCodes": source_info["sourceCodes"],
			"mappedSourceCodes": source_info["mappedSourceCodes"],
			"minimumDataQuality": config["minimumQuality"],
			"qualityCounts": source_info["qualityCounts"],
			"retainedQualityCounts": source_info["retainedQualityCounts"],
			"excludedLowQualityRows": source_info["excludedLowQualityRows"],
			"ignoredAreaCounts": source_info["ignoredAreaCounts"],
		},
		"indicators": index_indicators,
		"notes": [
			"Only WID.world observations with data_quality >= 1 are published. Quality-0 observations are excluded because they are source-side imputations without country distributional data.",
			"All four indicators use WID pre-tax national income for adults aged 20+ with equal-split resources within couples (WID codes 992j).",
			"Income shares and the Gini coefficient are converted from WID fractions on a 0-1 scale to percentages / Gini 0-100.",
			"Kosovo is mapped explicitly from WID area code KS to country:XKX. Historical, regional and purchasing-power aggregate area codes are ignored explicitly; fuzzy country matching is not used.",
			"No interpolation, extrapolation or cross-source fallback is applied by this builder. Published values are the harmonized estimates supplied by WID.world after the quality-0 exclusion.",
			"WID.world identifies its downloadable datasets as open-access data; no Creative Commons license is asserted here.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built WID inequality snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")
	print(f"Source quality counts: {source_info['qualityCounts']}")
	print(f"Retained quality counts: {source_info['retainedQualityCounts']}")


if __name__ == "__main__":
	main()
