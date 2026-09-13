#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import build_ilostat as ilo_common
import build_ilostat_gender_pay_gap as gender_pay_gap
import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "ilostat-wages-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build country minimum-wage statistics from the ILOSTAT COND database."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.ilostat-wages-statistics/v1":
		raise ValueError("Invalid ILOSTAT wages statistics config.")

	api_base = str(payload.get("apiBase", "")).strip().rstrip("/")
	toc_url = str(payload.get("tocUrl", "")).strip()
	source_page = str(payload.get("sourcePage", "")).strip()
	provider = payload.get("provider")
	source_dataset = str(payload.get("sourceDataset", "")).strip()
	source_indicator = str(payload.get("sourceIndicator", "")).strip()
	max_default_age = payload.get("maxDefaultYearAge")
	indicators = payload.get("indicators")

	for name, url in (("apiBase", api_base), ("tocUrl", toc_url), ("sourcePage", source_page)):
		if not url.startswith("https://"):
			raise ValueError(f"ILOSTAT wages {name} must use HTTPS.")
	if not isinstance(provider, dict) or provider.get("id") != "ilostat-wages":
		raise ValueError("ILOSTAT wages provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"ILOSTAT wages provider metadata is missing {key}.")
	if source_dataset != "EAR_INEE_CUR_NB_A":
		raise ValueError("ILOSTAT wages sourceDataset must be EAR_INEE_CUR_NB_A.")
	if source_indicator != "EAR_INEE_CUR_NB":
		raise ValueError("ILOSTAT wages sourceIndicator must be EAR_INEE_CUR_NB.")
	if not isinstance(max_default_age, int) or max_default_age < 1:
		raise ValueError("ILOSTAT wages maxDefaultYearAge is invalid.")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("ILOSTAT wages config requires indicators.")

	ids: set[str] = set()
	slugs: set[str] = set()
	classifications: set[str] = set()
	allowed_classifications = {"CUR_TYPE_PPP", "CUR_TYPE_USD"}
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("ILOSTAT wages indicator entries must be objects.")
		for key in ("id", "slug", "filterClassif1", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"ILOSTAT wages indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		classif1 = str(indicator["filterClassif1"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate ILOSTAT wages indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate ILOSTAT wages indicator slug: {slug}")
		if classif1 in classifications:
			raise ValueError(f"Duplicate ILOSTAT wages classif1 filter: {classif1}")
		if classif1 not in allowed_classifications:
			raise ValueError(f"Unsupported ILOSTAT wages classif1 filter: {classif1}")
		ids.add(indicator_id)
		slugs.add(slug)
		classifications.add(classif1)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"ILOSTAT wages indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"ILOSTAT wages indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"ILOSTAT wages indicator {indicator_id} requires at least one required area.")
		if "country:AUT" in required_areas:
			raise ValueError("Austria must not be required for statutory minimum wages.")

	return payload


def load_source_metadata(config: dict[str, Any], timeout: int) -> dict[str, str]:
	data = ilo_common.fetch_bytes(str(config["tocUrl"]), timeout)
	rows = ilo_common.read_csv_bytes(data, str(config["tocUrl"]))
	by_id = {
		str(row.get("id", "")).strip(): row
		for row in rows
		if str(row.get("id", "")).strip()
	}
	if len(by_id) < 1000:
		raise RuntimeError(f"ILOSTAT table of contents unexpectedly small: {len(by_id)} datasets.")

	dataset_id = str(config["sourceDataset"])
	row = by_id.get(dataset_id)
	if row is None:
		raise RuntimeError(f"ILOSTAT ToC is missing configured dataset {dataset_id}.")
	label = str(row.get("indicator.label", "")).strip()
	freq = str(row.get("freq", "")).strip()
	subject = str(row.get("subject", "")).strip()
	if label != "Monthly minimum wage by currency":
		raise RuntimeError(f"Unexpected ILOSTAT minimum-wage table label: {label!r}")
	if freq != "A":
		raise RuntimeError(f"ILOSTAT minimum-wage dataset is not annual: freq={freq!r}")
	if subject and subject != "EAR":
		raise RuntimeError(f"Unexpected ILOSTAT minimum-wage subject: {subject!r}")
	return row


def load_source_rows(config: dict[str, Any], timeout: int) -> tuple[list[dict[str, str]], str]:
	url = ilo_common.dataset_url(str(config["apiBase"]), str(config["sourceDataset"]))
	data = ilo_common.fetch_bytes(url, timeout)
	rows = ilo_common.read_csv_bytes(data, url)
	if len(rows) < 10000:
		raise RuntimeError(f"ILOSTAT minimum-wage dataset unexpectedly small: {len(rows)} rows.")

	required_fields = {"ref_area", "source", "indicator", "classif1", "time", "obs_value"}
	missing = required_fields - set(rows[0])
	if missing:
		raise RuntimeError(f"ILOSTAT minimum-wage CSV is missing fields: {sorted(missing)}")
	indicators = {
		str(row.get("indicator", "")).strip()
		for row in rows
		if str(row.get("indicator", "")).strip()
	}
	if indicators != {str(config["sourceIndicator"])}:
		raise RuntimeError(f"Unexpected ILOSTAT minimum-wage indicator codes: {sorted(indicators)}")
	classifications = {
		str(row.get("classif1", "")).strip()
		for row in rows
		if str(row.get("classif1", "")).strip()
	}
	for required in ("CUR_TYPE_LCU", "CUR_TYPE_PPP", "CUR_TYPE_USD"):
		if required not in classifications:
			raise RuntimeError(f"ILOSTAT minimum-wage classification is missing {required}.")
	return rows, url


def normalize_indicator(
	config: dict[str, Any],
	indicator: dict[str, Any],
	rows: list[dict[str, str]],
	area_by_iso3: dict[str, str],
	now_year: int,
	source_url: str,
	source_metadata: dict[str, str],
) -> dict[str, Any]:
	provider = config["provider"]
	classif1 = str(indicator["filterClassif1"])
	values_by_year: dict[int, dict[str, int | float]] = {}
	areas_with_any_value: set[str] = set()
	ignored_codes: set[str] = set()
	future_records = 0
	source_codes: set[str] = set()

	for row in rows:
		if str(row.get("classif1", "")).strip() != classif1:
			continue
		raw_value = str(row.get("obs_value", "")).strip()
		if not raw_value:
			continue
		iso3 = str(row.get("ref_area", "")).strip().upper()
		if iso3 not in area_by_iso3:
			if iso3:
				ignored_codes.add(iso3)
			continue
		year_text = str(row.get("time", "")).strip()
		if len(year_text) != 4 or not year_text.isdigit():
			continue
		year = int(year_text)
		if year > now_year:
			future_records += 1
			continue
		area_id = area_by_iso3[iso3]
		number = common.normalize_number(raw_value)
		year_values = values_by_year.setdefault(year, {})
		if area_id in year_values:
			raise RuntimeError(f"Duplicate ILOSTAT minimum-wage value for {indicator['id']} {year} {area_id}.")
		year_values[area_id] = number
		areas_with_any_value.add(area_id)
		source_code = str(row.get("source", "")).strip()
		if source_code:
			source_codes.add(source_code)

	if not values_by_year:
		raise RuntimeError(f"ILOSTAT returned no mapped values for {indicator['id']}.")
	minimum_any = int(indicator["minAreasWithAnyValue"])
	if len(areas_with_any_value) < minimum_any:
		raise RuntimeError(
			f"ILOSTAT minimum-wage coverage too small for {indicator['id']}: "
			f"{len(areas_with_any_value)} areas, expected at least {minimum_any}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in areas_with_any_value:
			raise RuntimeError(f"Required area {area_id} has no ILOSTAT minimum-wage values for {indicator['id']}.")

	available_years = sorted(values_by_year)
	latest_year = available_years[-1]
	minimum_default_coverage = int(indicator["minAreasInDefaultYear"])
	required_areas = [str(area_id) for area_id in indicator["requiredAreas"]]
	eligible_years = [
		year
		for year in available_years
		if len(values_by_year[year]) >= minimum_default_coverage
		and all(area_id in values_by_year[year] for area_id in required_areas)
	]
	if not eligible_years:
		raise RuntimeError(
			f"ILOSTAT minimum-wage series has no sufficiently complete default year for {indicator['id']}: "
			f"expected at least {minimum_default_coverage} areas and all required areas."
		)
	default_year = eligible_years[-1]
	max_age = int(config["maxDefaultYearAge"])
	if now_year - default_year > max_age:
		raise RuntimeError(
			f"ILOSTAT minimum-wage default year for {indicator['id']} is too old: "
			f"{default_year}, current year {now_year}, allowed age {max_age}."
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
	payload = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": indicator_metadata,
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"sourceDataset": config["sourceDataset"],
			"indicator": config["sourceIndicator"],
			"tableLabel": str(source_metadata.get("indicator.label", "")).strip(),
			"filters": {"classif1": classif1},
			"sourceSeriesCount": len(source_codes),
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourcePage"],
			"apiUrl": source_url,
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": latest_year,
			"areasInLatestYear": len(values_by_year[latest_year]),
			"areasInDefaultYear": len(values_by_year[default_year]),
			"minimumDefaultYearCoverage": minimum_default_coverage,
		},
		"values": sorted_values,
	}

	print(
		f"  {indicator['id']}: mapped={len(areas_with_any_value)} "
		f"years={available_years[0]}-{latest_year} "
		f"defaultYear={default_year} "
		f"defaultCoverage={len(values_by_year[default_year])} "
		f"ignoredCodes={len(ignored_codes)} "
		f"sourceSeries={len(source_codes)} "
		f"futureSkipped={future_records}"
	)
	return payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	gender_pay_gap.validate_config(config)
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	now = common.utc_now()
	source_metadata = load_source_metadata(config, args.timeout)
	rows, source_url = load_source_rows(config, args.timeout)
	print(
		f"ILOSTAT minimum-wage source: {config['sourceDataset']} "
		f"({source_metadata.get('indicator.label')}); rows={len(rows)}"
	)

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload = normalize_indicator(
			config,
			indicator,
			rows,
			area_by_iso3,
			now.year,
			source_url,
			source_metadata,
		)
		indicator_payloads.append((indicator, payload))

	gender_indicator, gender_payload, gender_source_metadata = gender_pay_gap.build_payload(
		config,
		area_by_iso3,
		now.year,
		args.timeout,
	)
	indicator_payloads.append((gender_indicator, gender_payload))

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
	index_indicators = []
	latest_source_year = 0
	for indicator, payload in indicator_payloads:
		filename = f"{indicator['slug']}.json"
		common.write_json(release_dir / filename, payload)
		frequency = str(payload.get("frequency") or payload["indicator"].get("frequency") or "annual")
		payload_source = payload["source"]
		if str(payload_source.get("sourceDataset", "")) == str(config["sourceDataset"]):
			latest_source_year = max(latest_source_year, int(payload["coverage"]["latestYear"]))
		index_indicators.append({
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": frequency,
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"sourceIndicator": payload_source["indicator"],
			"sourceDataset": payload_source["sourceDataset"],
			"filters": payload_source.get("filters", {}),
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
			"sourceDataset": config["sourceDataset"],
			"sourceIndicator": config["sourceIndicator"],
			"tableLabel": str(source_metadata.get("indicator.label", "")).strip(),
			"latestSourceYear": latest_source_year,
			"defaultYearPolicy": "latest-year-meeting-indicator-coverage-and-required-area-checks",
		},
		"additionalDatasets": [
			{
				"sourceDataset": gender_indicator["sourceDataset"],
				"sourceIndicator": gender_indicator["sourceIndicator"],
				"tableLabel": str(gender_source_metadata.get("indicator.label", "")).strip(),
				"latestSourceYear": gender_payload["coverage"]["latestSourceYear"],
				"defaultYearPolicy": "latest-observation-through-year; source year retained per observation",
			}
		],
		"indicators": index_indicators,
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(output_dir / "index.json", common.build_global_index(provider_catalog))

	print(f"Built ILOSTAT wages snapshot {snapshot}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
