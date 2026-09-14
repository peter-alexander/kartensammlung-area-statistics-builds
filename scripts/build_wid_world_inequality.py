#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
from typing import Any

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "wid-world-inequality-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
AUDITED_MINIMUM_COVERAGE_2024 = 216
EXPECTED_PERCENTILES = {"p0p50", "p50p90", "p90p100", "p99p100"}
EXPECTED_VARIABLES = {"sptinc992j", "shweal992j"}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized WID.world income and wealth distribution statistics.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--input-csv", type=Path, required=True)
	parser.add_argument("--input-metadata", type=Path, required=True)
	parser.add_argument("--timeout", type=int, default=60)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.wid-world-inequality-statistics/v1":
		raise ValueError("Invalid WID world inequality statistics config.")
	for key in ("sourcePage", "methodologyPage", "codesDictionaryUrl", "widToolRepository"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"WID {key} must use HTTPS.")
	if len(str(payload.get("expectedWidToolCommit", ""))) != 40:
		raise ValueError("WID expectedWidToolCommit must be a full Git commit SHA.")
	if not str(payload.get("expectedPackageVersion", "")).strip():
		raise ValueError("WID expectedPackageVersion is required.")
	latest_year = payload.get("minimumLatestYear")
	if not isinstance(latest_year, int) or latest_year < 2024:
		raise ValueError("WID minimumLatestYear is invalid.")
	if str(payload.get("ageCode", "")) != "992" or str(payload.get("populationCode", "")) != "j":
		raise ValueError("WID age/population concept changed unexpectedly.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "wid-world-inequality":
		raise ValueError("WID provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"WID provider metadata is missing {key}.")
	if provider.get("license") != "Open-Access-Daten":
		raise ValueError("WID license wording must not claim an unverified named license.")

	aliases = payload.get("areaAliases")
	if aliases != {"KS": "XK"}:
		raise ValueError("WID areaAliases must explicitly map KS to XK.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 8:
		raise ValueError("WID config must contain exactly eight target indicators.")
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
		if str(indicator["sourceVariable"]) not in EXPECTED_VARIABLES:
			raise ValueError(f"Unexpected WID source variable for {indicator_id}.")
		if str(indicator["percentile"]) not in EXPECTED_PERCENTILES:
			raise ValueError(f"Unexpected WID percentile for {indicator_id}.")
		if str(indicator["sourceVariable"]) != f"{indicator['sourceIndicator']}{payload['ageCode']}{payload['populationCode']}":
			raise ValueError(f"WID sourceVariable does not match concept codes for {indicator_id}.")
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or unit.get("id") != "percent" or unit.get("symbol") != "%":
			raise ValueError(f"WID indicator {indicator_id} must use percent units.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value < 200:
				raise ValueError(f"WID indicator {indicator_id} has invalid {key}.")
		required = indicator.get("requiredAreas")
		if not isinstance(required, list) or not required or any(not str(value).strip() for value in required):
			raise ValueError(f"WID indicator {indicator_id} requires requiredAreas.")
	if {key[0] for key in source_keys} != EXPECTED_VARIABLES:
		raise ValueError("WID config does not contain both audited target variables.")
	for variable in EXPECTED_VARIABLES:
		if {percentile for source_variable, percentile in source_keys if source_variable == variable} != EXPECTED_PERCENTILES:
			raise ValueError(f"WID config does not contain all four percentiles for {variable}.")
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
	if len(result) != 250:
		raise RuntimeError(f"Expected 250 country ISO2 mappings, got {len(result)}")
	for required in ("AT", "DE", "US", "IN", "CN", "ZA", "NA", "XK"):
		if required not in result:
			raise RuntimeError(f"Country registry is missing ISO2 {required}.")
	if area_by_iso3.get("XKX") != result["XK"]:
		raise RuntimeError("Country registry Kosovo ISO2/ISO3 mapping is inconsistent.")
	if area_by_iso3.get("NAM") != result["NA"]:
		raise RuntimeError("Country registry Namibia ISO2/ISO3 mapping is inconsistent.")
	return result


def load_download_metadata(path: Path, config: dict[str, Any]) -> dict[str, Any]:
	payload = common.read_json_path(path)
	if not isinstance(payload, dict):
		raise RuntimeError("WID download metadata must be an object.")
	package = payload.get("package") or {}
	if package.get("name") != "wid":
		raise RuntimeError(f"Unexpected WID package metadata: {package!r}")
	if str(package.get("version", "")) != str(config["expectedPackageVersion"]):
		raise RuntimeError("WID package version differs from config.")
	if str(package.get("commit", "")) != str(config["expectedWidToolCommit"]):
		raise RuntimeError("WID tool commit differs from audited config.")
	if str(package.get("repository", "")) != str(config["widToolRepository"]):
		raise RuntimeError("WID tool repository differs from config.")
	query = payload.get("query") or {}
	if int(query.get("registryCountries", -1)) != 250:
		raise RuntimeError("WID query metadata has unexpected registry country count.")
	if int(query.get("directCountryOverlap", -1)) != 232 or int(query.get("queryCountries", -1)) != 233:
		raise RuntimeError("WID query country mapping differs from the audited mapping.")
	if query.get("countryAlias") != {"KS": "XK"}:
		raise RuntimeError("WID query metadata is missing KS -> XK alias.")
	if str(query.get("age", "")) != str(config["ageCode"]) or str(query.get("population", "")) != str(config["populationCode"]):
		raise RuntimeError("WID query population concept differs from config.")
	if query.get("years") != "all" or query.get("includeExtrapolations") is not True or query.get("metadata") is not False:
		raise RuntimeError("WID production query must use the full published series without extrapolation filtering.")
	rows = payload.get("rows")
	if not isinstance(rows, int) or rows <= 0:
		raise RuntimeError("WID download metadata has invalid row count.")
	return payload


def parse_source(
	config: dict[str, Any],
	input_csv: Path,
	iso2_to_area: dict[str, str],
) -> tuple[dict[str, dict[int, dict[str, float]]], dict[str, Any]]:
	by_key = {
		(str(indicator["sourceVariable"]), str(indicator["percentile"])): indicator
		for indicator in config["indicators"]
	}
	aliases = {str(source).upper(): str(target).upper() for source, target in config["areaAliases"].items()}
	values: dict[str, dict[int, dict[str, float]]] = {
		str(indicator["id"]): defaultdict(dict)
		for indicator in config["indicators"]
	}
	source_codes_seen: set[str] = set()
	mapped_areas_seen: set[str] = set()
	raw_rows = 0
	min_year: int | None = None
	max_year: int | None = None

	with input_csv.open(encoding="utf-8-sig", newline="") as handle:
		reader = csv.DictReader(handle)
		required_columns = {"country", "variable", "percentile", "year", "value"}
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
			code = str(row.get("country") or "").strip().upper()
			if len(code) != 2 or not code.isalpha():
				raise RuntimeError(f"Unexpected WID country code at row {row_number}: {code!r}")
			source_codes_seen.add(code)
			mapped_code = aliases.get(code, code)
			area_id = iso2_to_area.get(mapped_code)
			if area_id is None:
				raise RuntimeError(f"Unmapped WID country code with target data: {code}")
			mapped_areas_seen.add(area_id)

			try:
				year = int(str(row["year"]).strip())
				raw_value = float(row["value"])
			except (TypeError, ValueError, KeyError) as error:
				raise RuntimeError(f"Invalid WID numeric fields at row {row_number}.") from error
			if not math.isfinite(raw_value):
				raise RuntimeError(f"Non-finite WID value at row {row_number}.")
			if not 1700 <= year <= 2200:
				raise RuntimeError(f"WID year outside sanity range at row {row_number}: {year}")
			if not -2.0 <= raw_value <= 2.0:
				raise RuntimeError(f"WID share outside sanity range -2..2 at row {row_number}: {raw_value}")
			value = round(raw_value * 100, 6)
			indicator_id = str(indicator["id"])
			if area_id in values[indicator_id][year]:
				raise RuntimeError(f"Duplicate WID observation after mapping for {indicator_id} {year} {area_id}")
			values[indicator_id][year][area_id] = value
			min_year = year if min_year is None else min(min_year, year)
			max_year = year if max_year is None else max(max_year, year)

	if raw_rows == 0:
		raise RuntimeError("WID CSV contains no target observations.")
	if "NA" not in source_codes_seen or "KS" not in source_codes_seen:
		raise RuntimeError("WID source must contain both Namibia NA and Kosovo KS target rows.")
	return values, {
		"rawRows": raw_rows,
		"sourceCodes": len(source_codes_seen),
		"mappedAreas": len(mapped_areas_seen),
		"minimumYear": min_year,
		"maximumYear": max_year,
	}


def choose_default_year(indicator: dict[str, Any], values_by_year: dict[int, dict[str, float]]) -> int:
	required = set(str(value) for value in indicator["requiredAreas"])
	eligible = [
		year
		for year, year_values in values_by_year.items()
		if len(year_values) >= int(indicator["minAreasInDefaultYear"])
		and required.issubset(year_values)
	]
	if not eligible:
		raise RuntimeError(f"No sufficiently complete WID default year for {indicator['id']}.")
	return max(eligible)


def validate_distribution_consistency(config: dict[str, Any], values: dict[str, dict[int, dict[str, float]]]) -> None:
	ids_by_key = {
		(str(indicator["sourceVariable"]), str(indicator["percentile"])): str(indicator["id"])
		for indicator in config["indicators"]
	}
	for variable in EXPECTED_VARIABLES:
		bottom = values[ids_by_key[(variable, "p0p50")]]
		middle = values[ids_by_key[(variable, "p50p90")]]
		top10 = values[ids_by_key[(variable, "p90p100")]]
		top1 = values[ids_by_key[(variable, "p99p100")]]
		checked_sums = 0
		checked_nesting = 0
		for year in set(bottom) | set(middle) | set(top10):
			common_areas = set(bottom.get(year, {})) & set(middle.get(year, {})) & set(top10.get(year, {}))
			for area_id in common_areas:
				total = bottom[year][area_id] + middle[year][area_id] + top10[year][area_id]
				if abs(total - 100.0) > 0.05:
					raise RuntimeError(f"WID shares do not sum to 100 for {variable} {year} {area_id}: {total}")
				checked_sums += 1
		for year in set(top1) & set(top10):
			common_areas = set(top1[year]) & set(top10[year])
			for area_id in common_areas:
				if top1[year][area_id] > top10[year][area_id] + 0.000001:
					raise RuntimeError(f"WID top 1 share exceeds top 10 share for {variable} {year} {area_id}")
				checked_nesting += 1
		if checked_sums == 0 or checked_nesting == 0:
			raise RuntimeError(f"WID consistency checks had no comparable observations for {variable}.")

	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		coverage_2024 = len(values[indicator_id].get(2024, {}))
		if coverage_2024 < AUDITED_MINIMUM_COVERAGE_2024:
			raise RuntimeError(f"WID 2024 coverage dropped below {AUDITED_MINIMUM_COVERAGE_2024} for {indicator_id}: {coverage_2024}")
		for required in ("country:NAM", "country:XKX"):
			if required not in values[indicator_id].get(2024, {}):
				raise RuntimeError(f"WID 2024 audit area missing for {indicator_id}: {required}")

	wealth_bottom_id = ids_by_key[("shweal992j", "p0p50")]
	za_value = values[wealth_bottom_id][2024].get("country:ZAF")
	if za_value is None or not -3.0 < za_value < -2.0:
		raise RuntimeError(f"WID South Africa bottom-50 wealth audit value changed unexpectedly: {za_value}")


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
		raise RuntimeError(f"WID returned no values for {indicator['id']}.")
	latest_year = available_years[-1]
	if latest_year < int(config["minimumLatestYear"]):
		raise RuntimeError(f"WID latest year too old for {indicator['id']}: {latest_year}")
	mapped_areas = {area for year_values in values_by_year.values() for area in year_values}
	if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(f"WID coverage too small for {indicator['id']}: {len(mapped_areas)}")
	default_year = choose_default_year(indicator, values_by_year)

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
			"mappingAliases": config["areaAliases"],
			"includeExtrapolations": True,
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
		raise RuntimeError("WID provider is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	iso2_to_area = load_iso2_mapping(registry_payload, area_by_iso3)
	download_metadata = load_download_metadata(args.input_metadata, config)

	source_bytes = args.input_csv.read_bytes()
	source_file = {
		"fileName": args.input_csv.name,
		"bytes": len(source_bytes),
		"sha256": hashlib.sha256(source_bytes).hexdigest(),
	}
	values, source_info = parse_source(config, args.input_csv, iso2_to_area)
	if int(download_metadata["rows"]) != int(source_info["rawRows"]):
		raise RuntimeError(
			f"WID row count changed between downloader and builder: {download_metadata['rows']} != {source_info['rawRows']}"
		)
	validate_distribution_consistency(config, values)

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
		coverage = payload["coverage"]
		print(
			f"{indicator['id']}: years={payload['availableYears'][0]}-{coverage['latestYear']} "
			f"any={coverage['areasWithAnyValue']} default={payload['defaultYear']} "
			f"defaultCoverage={coverage['areasInDefaultYear']} coverage2024={len(values[str(indicator['id'])][2024])}"
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
			"mappedAreas": source_info["mappedAreas"],
			"sourceYearRange": [source_info["minimumYear"], source_info["maximumYear"]],
		},
		"indicators": index_indicators,
		"notes": [
			"All eight series use WID Equal-Split Adults aged 20+ (WID population concept 992j).",
			"The complete annual series published by WID.world are retained; this builder does not create its own interpolation, extrapolation or cross-source fallback values.",
			"WID.world harmonized series may themselves contain imputed, interpolated or extrapolated estimates. An audit of the official WID R client found that include_extrapolations=FALSE removed no observations from these eight target series.",
			"WID shares are converted from fractions to percentages. Bottom-50 net-wealth shares may legitimately be negative when debts exceed assets for that group.",
			"Kosovo is mapped explicitly from WID code KS to registry code XK/country:XKX. Namibia ISO2 NA is asserted explicitly. No fuzzy country matching is used.",
			"WID.world describes its downloadable datasets as open-access data; no Creative Commons or other named data license is asserted here.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built WID world inequality snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")
	print(f"Source rows: {source_info['rawRows']} mapped areas: {source_info['mappedAreas']}")


if __name__ == "__main__":
	main()
