#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import io
import math
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "unesco-uis-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
EXPECTED_EXPORT_FIELDS = [
	"indicator_id",
	"country_id",
	"year",
	"value",
	"magnitude",
	"qualifier",
	"indicator_label_en",
	"country_name_en",
	"footnotes",
]


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized country education statistics from UNESCO UIS DataHub.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=180)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.unesco-uis-statistics/v1":
		raise ValueError("Invalid UNESCO UIS statistics config.")
	api_base = str(payload.get("apiBase", "")).strip()
	if not api_base.startswith("https://"):
		raise ValueError("UNESCO UIS apiBase must use HTTPS.")
	minimum_latest = payload.get("minimumSourceLatestYear")
	if not isinstance(minimum_latest, int) or not 1900 <= minimum_latest <= 2200:
		raise ValueError("UNESCO UIS minimumSourceLatestYear is invalid.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "unesco-uis":
		raise ValueError("UNESCO UIS provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"UNESCO UIS provider metadata is missing {key}.")

	datasets = payload.get("datasets")
	if not isinstance(datasets, dict) or not datasets:
		raise ValueError("UNESCO UIS config requires datasets.")
	for dataset_id, dataset in datasets.items():
		if not str(dataset_id).strip() or not isinstance(dataset, dict):
			raise ValueError("UNESCO UIS dataset metadata is invalid.")
		for key in ("name", "sourceUrl"):
			if not str(dataset.get(key, "")).strip():
				raise ValueError(f"UNESCO UIS dataset {dataset_id} is missing {key}.")
		if not str(dataset["sourceUrl"]).startswith("https://"):
			raise ValueError(f"UNESCO UIS dataset {dataset_id} sourceUrl must use HTTPS.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("UNESCO UIS config requires indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	source_keys: set[tuple[str, str]] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("UNESCO UIS indicator entries must be objects.")
		for key in ("id", "slug", "dataset", "sourceIndicator", "sourceLabel", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"UNESCO UIS indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		dataset_id = str(indicator["dataset"])
		source_indicator = str(indicator["sourceIndicator"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate UNESCO UIS indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate UNESCO UIS indicator slug: {slug}")
		if dataset_id not in datasets:
			raise ValueError(f"UNESCO UIS indicator {indicator_id} references unknown dataset {dataset_id}.")
		if (dataset_id, source_indicator) in source_keys:
			raise ValueError(f"Duplicate UNESCO UIS source series: {dataset_id}/{source_indicator}")
		ids.add(indicator_id)
		slugs.add(slug)
		source_keys.add((dataset_id, source_indicator))

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"UNESCO UIS indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"UNESCO UIS indicator {indicator_id} has invalid {key}.")
	return payload


def build_export_url(api_base: str, dataset_id: str, source_indicators: list[str]) -> str:
	quoted = ",".join(f'"{indicator}"' for indicator in source_indicators)
	params = urlencode({
		"where": f"indicator_id in ({quoted})",
		"select": ",".join(EXPECTED_EXPORT_FIELDS),
		"delimiter": ",",
	})
	return f"{api_base.rstrip('/')}/{dataset_id}/exports/csv?{params}"


def fetch_csv(url: str, timeout: int) -> tuple[list[dict[str, str]], int]:
	delays = (0, 5, 15, 30)
	last_error: Exception | None = None
	for attempt, delay in enumerate(delays, start=1):
		if delay:
			time.sleep(delay)
		request = Request(url, headers={"Accept": "text/csv,*/*", "User-Agent": USER_AGENT})
		try:
			with urlopen(request, timeout=timeout) as response:
				data = response.read()
			text = data.decode("utf-8-sig")
			reader = csv.DictReader(io.StringIO(text))
			if reader.fieldnames != EXPECTED_EXPORT_FIELDS:
				raise RuntimeError(f"UNESCO UIS CSV schema changed: {reader.fieldnames}")
			rows = list(reader)
			if not rows:
				raise RuntimeError(f"UNESCO UIS CSV export is empty: {url}")
			return rows, len(data)
		except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, csv.Error, RuntimeError) as error:
			last_error = error
			print(f"UNESCO UIS request failed ({attempt}/{len(delays)}): {error}")
	if last_error is None:
		raise RuntimeError(f"UNESCO UIS request failed without exception: {url}")
	raise RuntimeError(f"UNESCO UIS request failed after {len(delays)} attempts: {url}") from last_error


def parse_value(raw: str) -> int | float:
	value = common.normalize_number(raw)
	number = float(value)
	if not math.isfinite(number):
		raise RuntimeError(f"Non-finite UNESCO UIS value: {raw!r}")
	return value


def choose_default_year(
	indicator: dict[str, Any],
	available_years: list[int],
	year_values: dict[int, dict[str, int | float]],
) -> int:
	minimum = int(indicator["minAreasInDefaultYear"])
	eligible = [year for year in available_years if len(year_values[year]) >= minimum]
	if not eligible:
		raise RuntimeError(
			f"UNESCO UIS has no sufficiently complete default year for {indicator['id']}: "
			f"expected at least {minimum} areas."
		)
	return eligible[-1]


def load_dataset(
	config: dict[str, Any],
	dataset_id: str,
	indicators: list[dict[str, Any]],
	area_by_iso3: dict[str, str],
	timeout: int,
) -> tuple[
	dict[str, dict[int, dict[str, int | float]]],
	dict[str, set[str]],
	dict[str, int],
	set[str],
	int,
	int,
	str,
]:
	source_codes = [str(indicator["sourceIndicator"]) for indicator in indicators]
	export_url = build_export_url(str(config["apiBase"]), dataset_id, source_codes)
	rows, byte_count = fetch_csv(export_url, timeout)
	print(f"UNESCO UIS {dataset_id}: downloaded={byte_count} bytes rows={len(rows)} indicators={len(source_codes)}")

	indicator_by_source = {str(indicator["sourceIndicator"]): indicator for indicator in indicators}
	values: dict[str, dict[int, dict[str, int | float]]] = {
		str(indicator["id"]): defaultdict(dict)
		for indicator in indicators
	}
	qualifiers: dict[str, set[str]] = {str(indicator["id"]): set() for indicator in indicators}
	footnote_rows: dict[str, int] = {str(indicator["id"]): 0 for indicator in indicators}
	ignored_iso3: set[str] = set()
	all_years: set[int] = set()
	seen_sources: set[str] = set()

	for row in rows:
		source_code = str(row.get("indicator_id", "")).strip()
		indicator = indicator_by_source.get(source_code)
		if indicator is None:
			raise RuntimeError(f"UNESCO UIS export returned unexpected indicator {source_code!r} for {dataset_id}.")
		seen_sources.add(source_code)
		label = str(row.get("indicator_label_en", "")).strip()
		if label != str(indicator["sourceLabel"]):
			raise RuntimeError(
				f"UNESCO UIS label changed for {dataset_id}/{source_code}: {label!r}; "
				f"expected {indicator['sourceLabel']!r}."
			)

		year_text = str(row.get("year", "")).strip()
		value_text = str(row.get("value", "")).strip()
		if not year_text.isdigit() or len(year_text) != 4 or not value_text:
			continue
		year = int(year_text)
		all_years.add(year)
		iso3 = str(row.get("country_id", "")).strip().upper()
		if iso3 not in area_by_iso3:
			if iso3:
				ignored_iso3.add(iso3)
			continue
		area_id = area_by_iso3[iso3]
		indicator_id = str(indicator["id"])
		year_values = values[indicator_id][year]
		if area_id in year_values:
			raise RuntimeError(f"Duplicate UNESCO UIS value for {indicator_id} {year} {area_id}.")
		year_values[area_id] = parse_value(value_text)

		magnitude = str(row.get("magnitude", "")).strip()
		if magnitude:
			raise RuntimeError(f"Unexpected UNESCO UIS magnitude for {indicator_id} {year} {iso3}: {magnitude!r}")
		qualifier = str(row.get("qualifier", "")).strip()
		if qualifier:
			qualifiers[indicator_id].add(qualifier)
		if str(row.get("footnotes", "")).strip():
			footnote_rows[indicator_id] += 1

	missing_sources = set(source_codes) - seen_sources
	if missing_sources:
		raise RuntimeError(f"UNESCO UIS export {dataset_id} is missing configured series: {sorted(missing_sources)}")
	if not all_years:
		raise RuntimeError(f"UNESCO UIS export {dataset_id} contained no annual values.")
	source_start = min(all_years)
	source_latest = max(all_years)
	if source_latest < int(config["minimumSourceLatestYear"]):
		raise RuntimeError(
			f"UNESCO UIS dataset {dataset_id} is unexpectedly old: latest selected-source year {source_latest}."
		)
	return values, qualifiers, footnote_rows, ignored_iso3, source_start, source_latest, export_url


def build_payloads(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_id: dict[str, dict[int, dict[str, int | float]]],
	qualifiers_by_id: dict[str, set[str]],
	footnote_rows_by_id: dict[str, int],
	export_urls: dict[str, str],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
	provider = config["provider"]
	result: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		year_values = values_by_id.get(indicator_id, {})
		available_years = sorted(year for year, mapped in year_values.items() if mapped)
		if not available_years:
			raise RuntimeError(f"UNESCO UIS returned no mapped values for {indicator_id}.")
		mapped_areas = {area_id for mapped in year_values.values() for area_id in mapped}
		minimum_any = int(indicator["minAreasWithAnyValue"])
		if len(mapped_areas) < minimum_any:
			raise RuntimeError(
				f"UNESCO UIS coverage too small for {indicator_id}: {len(mapped_areas)} areas, "
				f"expected at least {minimum_any}."
			)
		default_year = choose_default_year(indicator, available_years, year_values)
		latest_year = available_years[-1]
		dataset_id = str(indicator["dataset"])
		dataset = config["datasets"][dataset_id]

		indicator_metadata = {
			"id": indicator_id,
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		}
		source_metadata = {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": dataset["name"],
			"datasetId": dataset_id,
			"indicator": indicator["sourceIndicator"],
			"indicatorName": indicator["sourceLabel"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": dataset["sourceUrl"],
			"downloadUrl": export_urls[dataset_id],
			"qualifiersObserved": sorted(qualifiers_by_id.get(indicator_id, set())),
			"rowsWithSourceFootnotes": int(footnote_rows_by_id.get(indicator_id, 0)),
		}
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
				"areasInLatestYear": len(year_values[latest_year]),
				"areasInDefaultYear": len(year_values[default_year]),
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
			f"latestCoverage={len(year_values[latest_year])} defaultYear={default_year} "
			f"defaultCoverage={len(year_values[default_year])} "
			f"qualifiers={sorted(qualifiers_by_id.get(indicator_id, set())) or '(none)'}"
		)
		result.append((indicator, payload))
	return result


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("UNESCO UIS is missing from statistics-providers.json.")
	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)

	indicators_by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for indicator in config["indicators"]:
		indicators_by_dataset[str(indicator["dataset"])].append(indicator)

	values_by_id: dict[str, dict[int, dict[str, int | float]]] = {}
	qualifiers_by_id: dict[str, set[str]] = {}
	footnote_rows_by_id: dict[str, int] = {}
	export_urls: dict[str, str] = {}
	dataset_stats: dict[str, dict[str, Any]] = {}
	ignored_iso3: set[str] = set()

	for dataset_id in sorted(indicators_by_dataset):
		(
			dataset_values,
			dataset_qualifiers,
			dataset_footnote_rows,
			dataset_ignored,
			source_start,
			source_latest,
			export_url,
		) = load_dataset(config, dataset_id, indicators_by_dataset[dataset_id], area_by_iso3, args.timeout)
		values_by_id.update(dataset_values)
		qualifiers_by_id.update(dataset_qualifiers)
		footnote_rows_by_id.update(dataset_footnote_rows)
		export_urls[dataset_id] = export_url
		ignored_iso3.update(dataset_ignored)
		dataset_stats[dataset_id] = {
			"name": config["datasets"][dataset_id]["name"],
			"sourceUrl": config["datasets"][dataset_id]["sourceUrl"],
			"exportUrl": export_url,
			"sourceStartYear": source_start,
			"sourceLatestYear": source_latest,
			"selectedIndicators": sorted(str(indicator["sourceIndicator"]) for indicator in indicators_by_dataset[dataset_id]),
		}

	indicator_payloads = build_payloads(
		config,
		area_by_iso3,
		values_by_id,
		qualifiers_by_id,
		footnote_rows_by_id,
		export_urls,
	)
	now = datetime.now(timezone.utc)

	hasher = hashlib.sha256()
	for indicator, payload in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8") + b"\0" + common.canonical_bytes(payload) + b"\0")
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
			"sourceDataset": indicator["dataset"],
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
		"datasets": dataset_stats,
		"indicators": index_indicators,
		"notes": [
			"Country-level education statistics are fetched from current UNESCO DataHub filtered CSV exports.",
			"The newest source year can be only partially reported; each indicator defaults to the newest year that reaches its configured country-coverage threshold.",
			"UIS qualifiers are preserved as observed qualifier codes in source metadata; detailed country-specific source footnotes remain available at UNESCO DataHub and are not duplicated into the map payload.",
			"Gross enrolment ratios can exceed 100 percent because learners outside the official age group are included in the numerator.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Ignored UNESCO UIS ISO3 codes: {sorted(ignored_iso3) or '(none)'}")
	print(f"Built UNESCO UIS snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
