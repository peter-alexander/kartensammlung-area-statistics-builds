#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "ilostat-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"

EDITION_RE = re.compile(
	r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{4})\b",
	re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build country labour-market statistics from ILOSTAT ILO modelled estimates."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def fetch_bytes(url: str, timeout: int) -> bytes:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 2, 5, 10, 20), start=1):
		if delay:
			time.sleep(delay)
		request = urllib.request.Request(
			url,
			headers={"User-Agent": "kartensammlung-area-statistics-builds/1"},
		)
		try:
			with urllib.request.urlopen(request, timeout=timeout) as response:
				data = response.read()
				if not data:
					raise RuntimeError(f"Empty response from {url}")
				return data
		except Exception as exc:
			last_error = exc
			print(f"Request failed ({attempt}/5): {url}: {exc}")
	assert last_error is not None
	raise RuntimeError(f"Request failed after 5 attempts: {url}") from last_error


def read_csv_bytes(data: bytes, source: str) -> list[dict[str, str]]:
	reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
	if not reader.fieldnames:
		raise RuntimeError(f"CSV has no header: {source}")
	return [dict(row) for row in reader]


def validate_filter_map(value: Any, context: str) -> dict[str, str]:
	if not isinstance(value, dict):
		raise ValueError(f"{context} must be an object.")
	result: dict[str, str] = {}
	for key, raw_value in value.items():
		key_text = str(key).strip()
		value_text = str(raw_value).strip()
		if not key_text or not value_text:
			raise ValueError(f"{context} contains an empty filter.")
		result[key_text] = value_text
	return result


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.ilostat-statistics/v1":
		raise ValueError("Invalid ILOSTAT statistics config.")
	api_base = str(payload.get("apiBase", "")).strip().rstrip("/")
	toc_url = str(payload.get("tocUrl", "")).strip()
	source_page = str(payload.get("sourcePage", "")).strip()
	provider = payload.get("provider")
	indicators = payload.get("indicators")
	aliases = payload.get("iso3Aliases", {})
	minimum_edition_year = payload.get("minimumEditionYear")

	for name, url in (("apiBase", api_base), ("tocUrl", toc_url), ("sourcePage", source_page)):
		if not url.startswith("https://"):
			raise ValueError(f"ILOSTAT {name} must use HTTPS.")
	if not isinstance(provider, dict) or provider.get("id") != "ilostat":
		raise ValueError("ILOSTAT provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"ILOSTAT provider metadata is missing {key}.")
	if not isinstance(minimum_edition_year, int) or minimum_edition_year < 2025:
		raise ValueError("ILOSTAT minimumEditionYear is invalid.")
	if not isinstance(aliases, dict):
		raise ValueError("ILOSTAT iso3Aliases must be an object.")
	for source, target in aliases.items():
		if len(str(source)) != 3 or len(str(target)) != 3:
			raise ValueError(f"Invalid ILOSTAT ISO3 alias: {source} -> {target}")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("ILOSTAT config requires indicators.")

	ids: set[str] = set()
	slugs: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("ILOSTAT indicator entries must be objects.")
		for key in ("id", "slug", "sourceDataset", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"ILOSTAT indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate ILOSTAT indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate ILOSTAT indicator slug: {slug}")
		ids.add(indicator_id)
		slugs.add(slug)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"ILOSTAT indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"ILOSTAT indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"ILOSTAT indicator {indicator_id} requires at least one required area.")

		derivation = indicator.get("derivation")
		if derivation is None:
			validate_filter_map(indicator.get("filters", {}), f"ILOSTAT indicator {indicator_id} filters")
		else:
			if not isinstance(derivation, dict) or derivation.get("type") != "share":
				raise ValueError(f"ILOSTAT indicator {indicator_id} has unsupported derivation.")
			validate_filter_map(derivation.get("baseFilters", {}), f"{indicator_id} baseFilters")
			validate_filter_map(derivation.get("numeratorFilter", {}), f"{indicator_id} numeratorFilter")
			validate_filter_map(derivation.get("denominatorFilter", {}), f"{indicator_id} denominatorFilter")
	return payload


def load_toc(config: dict[str, Any], timeout: int) -> dict[str, dict[str, str]]:
	data = fetch_bytes(str(config["tocUrl"]), timeout)
	rows = read_csv_bytes(data, str(config["tocUrl"]))
	by_id: dict[str, dict[str, str]] = {}
	for row in rows:
		dataset_id = str(row.get("id", "")).strip()
		if dataset_id:
			if dataset_id in by_id:
				raise RuntimeError(f"Duplicate ILOSTAT ToC dataset id: {dataset_id}")
			by_id[dataset_id] = row
	if len(by_id) < 1000:
		raise RuntimeError(f"ILOSTAT table of contents unexpectedly small: {len(by_id)} datasets.")
	return by_id


def parse_edition_year(label: str) -> int:
	match = EDITION_RE.search(label)
	if not match:
		raise RuntimeError(f"Could not parse ILOEST edition year from label: {label}")
	return int(match.group(1))


def validate_source_datasets(
	config: dict[str, Any],
	toc: dict[str, dict[str, str]],
) -> tuple[dict[str, dict[str, str]], int, str]:
	used_ids = sorted({str(indicator["sourceDataset"]) for indicator in config["indicators"]})
	metadata: dict[str, dict[str, str]] = {}
	edition_years: set[int] = set()
	edition_labels: set[str] = set()
	for dataset_id in used_ids:
		row = toc.get(dataset_id)
		if row is None:
			raise RuntimeError(f"ILOSTAT ToC is missing configured dataset {dataset_id}.")
		label = str(row.get("indicator.label", "")).strip()
		freq = str(row.get("freq", "")).strip()
		if "ilo modelled estimates" not in label.lower():
			raise RuntimeError(f"Configured ILOSTAT dataset is not an ILO modelled-estimates series: {dataset_id}: {label}")
		if freq != "A":
			raise RuntimeError(f"Configured ILOSTAT dataset is not annual: {dataset_id}: freq={freq}")
		edition_year = parse_edition_year(label)
		edition_years.add(edition_year)
		match = re.search(r"ILO modelled estimates,\s*([^()]+?)(?:\s*\(|$)", label, re.IGNORECASE)
		if match:
			edition_labels.add(match.group(1).strip())
		metadata[dataset_id] = row
	if len(edition_years) != 1:
		raise RuntimeError(f"ILOSTAT source datasets have inconsistent edition years: {sorted(edition_years)}")
	edition_year = next(iter(edition_years))
	if edition_year < int(config["minimumEditionYear"]):
		raise RuntimeError(
			f"ILOSTAT edition is unexpectedly old: {edition_year}, expected at least {config['minimumEditionYear']}."
		)
	edition_label = sorted(edition_labels)[0] if len(edition_labels) == 1 else str(edition_year)
	return metadata, edition_year, edition_label


def dataset_url(api_base: str, dataset_id: str) -> str:
	params = urllib.parse.urlencode({
		"id": dataset_id,
		"type": "code",
		"format": ".csv",
		"channel": "ilostat",
	})
	return f"{api_base.rstrip('/')}/data/indicator/?{params}"


def load_source_rows(
	config: dict[str, Any],
	timeout: int,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, str]]:
	api_base = str(config["apiBase"]).rstrip("/")
	used_ids = sorted({str(indicator["sourceDataset"]) for indicator in config["indicators"]})
	rows_by_dataset: dict[str, list[dict[str, str]]] = {}
	urls: dict[str, str] = {}
	for dataset_id in used_ids:
		url = dataset_url(api_base, dataset_id)
		data = fetch_bytes(url, timeout)
		rows = read_csv_bytes(data, url)
		if not rows:
			raise RuntimeError(f"ILOSTAT dataset is empty: {dataset_id}")
		required_fields = {"ref_area", "indicator", "time", "obs_value"}
		missing = required_fields - set(rows[0])
		if missing:
			raise RuntimeError(f"ILOSTAT dataset {dataset_id} is missing fields {sorted(missing)}")
		rows_by_dataset[dataset_id] = rows
		urls[dataset_id] = url
		print(f"ILOSTAT {dataset_id}: downloaded={len(data)} bytes rows={len(rows)}")
	return rows_by_dataset, urls


def matches_filters(row: dict[str, str], filters: dict[str, str]) -> bool:
	return all(str(row.get(key, "")).strip() == expected for key, expected in filters.items())


def mapped_iso3(source_code: str, aliases: dict[str, str]) -> str:
	code = source_code.strip().upper()
	return aliases.get(code, code)


def collect_direct_values(
	indicator: dict[str, Any],
	rows: list[dict[str, str]],
	area_by_iso3: dict[str, str],
	aliases: dict[str, str],
) -> tuple[dict[int, dict[str, int | float]], set[str], set[str]]:
	filters = validate_filter_map(indicator.get("filters", {}), f"{indicator['id']} filters")
	values_by_year: dict[int, dict[str, int | float]] = defaultdict(dict)
	unresolved: set[str] = set()
	statuses: set[str] = set()
	for row in rows:
		if not matches_filters(row, filters):
			continue
		source_code = str(row.get("ref_area", "")).strip().upper()
		if not source_code:
			continue
		iso3 = mapped_iso3(source_code, aliases)
		if iso3 not in area_by_iso3:
			if not source_code.startswith("X"):
				unresolved.add(source_code)
			continue
		year_text = str(row.get("time", "")).strip()
		value_text = str(row.get("obs_value", "")).strip()
		if not year_text.isdigit() or not value_text:
			continue
		year = int(year_text)
		number = common.normalize_number(value_text)
		if not math.isfinite(float(number)):
			raise RuntimeError(f"Non-finite ILOSTAT value: {indicator['id']} {source_code} {year}")
		if str(indicator["unit"].get("id", "")) == "percent" and not 0 <= float(number) <= 100:
			raise RuntimeError(f"ILOSTAT percentage outside 0..100: {indicator['id']} {source_code} {year}: {number}")
		area_id = area_by_iso3[iso3]
		if area_id in values_by_year[year]:
			raise RuntimeError(f"Duplicate ILOSTAT value: {indicator['id']} {year} {area_id}")
		values_by_year[year][area_id] = number
		status = str(row.get("obs_status", "")).strip()
		if status:
			statuses.add(status)
	return dict(values_by_year), unresolved, statuses


def collect_filtered_numbers(
	rows: list[dict[str, str]],
	filters: dict[str, str],
	area_by_iso3: dict[str, str],
	aliases: dict[str, str],
) -> tuple[dict[int, dict[str, float]], set[str], set[str]]:
	result: dict[int, dict[str, float]] = defaultdict(dict)
	unresolved: set[str] = set()
	statuses: set[str] = set()
	for row in rows:
		if not matches_filters(row, filters):
			continue
		source_code = str(row.get("ref_area", "")).strip().upper()
		if not source_code:
			continue
		iso3 = mapped_iso3(source_code, aliases)
		if iso3 not in area_by_iso3:
			if not source_code.startswith("X"):
				unresolved.add(source_code)
			continue
		year_text = str(row.get("time", "")).strip()
		value_text = str(row.get("obs_value", "")).strip()
		if not year_text.isdigit() or not value_text:
			continue
		year = int(year_text)
		value = float(common.normalize_number(value_text))
		if not math.isfinite(value):
			raise RuntimeError(f"Non-finite ILOSTAT source value: {source_code} {year}")
		area_id = area_by_iso3[iso3]
		if area_id in result[year]:
			raise RuntimeError(f"Duplicate ILOSTAT source value: {year} {area_id} filters={filters}")
		result[year][area_id] = value
		status = str(row.get("obs_status", "")).strip()
		if status:
			statuses.add(status)
	return dict(result), unresolved, statuses


def collect_derived_share(
	indicator: dict[str, Any],
	rows: list[dict[str, str]],
	area_by_iso3: dict[str, str],
	aliases: dict[str, str],
) -> tuple[dict[int, dict[str, int | float]], set[str], set[str]]:
	derivation = indicator["derivation"]
	base = validate_filter_map(derivation.get("baseFilters", {}), f"{indicator['id']} baseFilters")
	numerator_filters = {**base, **validate_filter_map(derivation["numeratorFilter"], f"{indicator['id']} numeratorFilter")}
	denominator_filters = {**base, **validate_filter_map(derivation["denominatorFilter"], f"{indicator['id']} denominatorFilter")}
	numerator, unresolved_num, statuses_num = collect_filtered_numbers(
		rows, numerator_filters, area_by_iso3, aliases
	)
	denominator, unresolved_den, statuses_den = collect_filtered_numbers(
		rows, denominator_filters, area_by_iso3, aliases
	)
	values_by_year: dict[int, dict[str, int | float]] = {}
	for year in sorted(set(numerator) & set(denominator)):
		year_values: dict[str, int | float] = {}
		for area_id, value in numerator[year].items():
			denom = denominator[year].get(area_id)
			if denom is None or denom <= 0:
				continue
			share = 100.0 * value / denom
			if not -1e-8 <= share <= 100.00000001:
				raise RuntimeError(f"Derived ILOSTAT share outside 0..100: {indicator['id']} {area_id} {year}: {share}")
			year_values[area_id] = common.normalize_number(round(max(0.0, min(100.0, share)), 6))
		if year_values:
			values_by_year[year] = year_values
	return values_by_year, unresolved_num | unresolved_den, statuses_num | statuses_den


def build_indicator_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	rows: list[dict[str, str]],
	area_by_iso3: dict[str, str],
	aliases: dict[str, str],
	source_meta: dict[str, str],
	source_url: str,
	projection_start_year: int,
) -> dict[str, Any]:
	if indicator.get("derivation") is None:
		values_by_year, unresolved, statuses = collect_direct_values(indicator, rows, area_by_iso3, aliases)
	else:
		values_by_year, unresolved, statuses = collect_derived_share(indicator, rows, area_by_iso3, aliases)
	if unresolved:
		raise RuntimeError(f"Unresolved ILOSTAT country codes for {indicator['id']}: {', '.join(sorted(unresolved))}")
	if not values_by_year:
		raise RuntimeError(f"ILOSTAT returned no mapped values for {indicator['id']}.")

	areas_with_any_value = set().union(*(set(values) for values in values_by_year.values()))
	minimum_any = int(indicator["minAreasWithAnyValue"])
	if len(areas_with_any_value) < minimum_any:
		raise RuntimeError(
			f"ILOSTAT coverage too small for {indicator['id']}: {len(areas_with_any_value)} areas, expected at least {minimum_any}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in areas_with_any_value:
			raise RuntimeError(f"Required area {area_id} has no ILOSTAT values for {indicator['id']}.")

	available_years = sorted(values_by_year)
	minimum_default_coverage = int(indicator["minAreasInDefaultYear"])
	eligible_default_years = [
		year for year in available_years
		if year < projection_start_year and len(values_by_year[year]) >= minimum_default_coverage
	]
	if not eligible_default_years:
		raise RuntimeError(
			f"ILOSTAT has no sufficiently complete pre-projection year for {indicator['id']}: expected at least {minimum_default_coverage} areas."
		)
	default_year = eligible_default_years[-1]
	if projection_start_year - default_year > 2:
		raise RuntimeError(f"ILOSTAT default year for {indicator['id']} is unexpectedly old: {default_year}.")

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
	source = {
		"providerId": config["provider"]["id"],
		"providerName": config["provider"]["name"],
		"dataset": config["provider"]["dataset"],
		"indicator": source_meta.get("indicator", ""),
		"sourceDataset": indicator["sourceDataset"],
		"sourceLabel": source_meta.get("indicator.label", ""),
		"license": config["provider"]["license"],
		"licenseUrl": config["provider"]["licenseUrl"],
		"attribution": config["provider"]["attribution"],
		"url": config["sourcePage"],
		"apiUrl": source_url,
		"observationStatusesObserved": sorted(statuses),
	}
	if indicator.get("derivation") is None:
		source["filters"] = indicator.get("filters", {})
	else:
		source["derivation"] = indicator["derivation"]

	payload = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": indicator_metadata,
		"source": source,
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": available_years[-1],
			"areasInLatestYear": len(values_by_year[available_years[-1]]),
			"areasInDefaultYear": len(values_by_year[default_year]),
			"projectionStartYear": projection_start_year,
		},
		"values": sorted_values,
	}
	print(
		f"{indicator['id']}: mapped={len(areas_with_any_value)} "
		f"years={available_years[0]}-{available_years[-1]} "
		f"defaultYear={default_year} defaultCoverage={len(values_by_year[default_year])}"
	)
	return payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	aliases = {
		str(source).strip().upper(): str(target).strip().upper()
		for source, target in config.get("iso3Aliases", {}).items()
	}
	toc = load_toc(config, args.timeout)
	source_metadata, edition_year, edition_label = validate_source_datasets(config, toc)
	projection_start_year = edition_year + 1
	rows_by_dataset, source_urls = load_source_rows(config, args.timeout)
	now = common.utc_now()

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		dataset_id = str(indicator["sourceDataset"])
		payload = build_indicator_payload(
			config,
			indicator,
			rows_by_dataset[dataset_id],
			area_by_iso3,
			aliases,
			source_metadata[dataset_id],
			source_urls[dataset_id],
			projection_start_year,
		)
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
		index_indicators.append({
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"sourceIndicator": source_metadata[str(indicator["sourceDataset"])].get("indicator", ""),
			"sourceDataset": indicator["sourceDataset"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
			"classification": indicator["classification"],
		})

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_iso3),
	}
	if registry_source["url"] is None:
		registry_source.pop("url")

	dataset_summaries = []
	for dataset_id in sorted(source_metadata):
		row = source_metadata[dataset_id]
		dataset_summaries.append({
			"id": dataset_id,
			"label": row.get("indicator.label", ""),
			"dataStart": int(row["data.start"]) if str(row.get("data.start", "")).isdigit() else row.get("data.start"),
			"dataEnd": int(row["data.end"]) if str(row.get("data.end", "")).isdigit() else row.get("data.end"),
			"lastUpdate": row.get("last.update", ""),
		})

	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"dataset": {
			"sourcePage": config["sourcePage"],
			"apiBase": config["apiBase"],
			"tocUrl": config["tocUrl"],
			"edition": edition_label,
			"editionYear": edition_year,
			"projectionStartYear": projection_start_year,
			"projectionLabel": "ILOEST",
			"defaultYearPolicy": "Latest sufficiently covered year before the ILOEST projection period.",
			"sourceDatasets": dataset_summaries,
		},
		"indicators": index_indicators,
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(output_dir / "index.json", common.build_global_index(provider_catalog))

	print(f"Built ILOSTAT snapshot {snapshot}")
	print(f"Edition: {edition_label}; projectionStartYear={projection_start_year}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
