#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "unhcr-refugee-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
EXPECTED_BREAKS = [100, 1000, 10000, 100000, 1000000, 5000000]
EXPECTED_EXCLUDED_CODES = {"UNK", "TIB", "XXA"}
EXPECTED_INDICATORS = {
	"displacement.refugees-host": ("host", "refugees", 1951),
	"displacement.refugees-origin": ("origin", "refugees", 1960),
	"displacement.asylum-seekers-host": ("host", "asylum_seekers", 2000),
	"displacement.asylum-seekers-origin": ("origin", "asylum_seekers", 2000),
	"displacement.other-international-protection-host": ("host", "oip", 2018),
	"displacement.other-international-protection-origin": ("origin", "oip", 2018),
	"displacement.idps-unhcr-assisted": ("host", "idps", 1993),
	"displacement.stateless-host": ("host", "stateless", 2004),
}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build normalized country refugee, asylum, IDP and statelessness statistics from UNHCR."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=90)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.unhcr-refugee-statistics/v1":
		raise ValueError("Invalid UNHCR refugee statistics config.")

	for key in ("apiBase", "sourceUrl", "methodologyUrl", "apiDocumentationUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"UNHCR {key} must use HTTPS.")
	if payload.get("release") != "2025 annual statistics":
		raise ValueError("UNHCR release must remain the audited 2025 annual statistics.")
	if payload.get("releaseDate") != "2026-06-11":
		raise ValueError("UNHCR releaseDate must remain 2026-06-11 until a later release is audited.")
	if payload.get("latestYear") != 2025:
		raise ValueError("UNHCR latestYear must remain 2025 until a later release is audited.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "unhcr":
		raise ValueError("UNHCR provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"UNHCR provider metadata is missing {key}.")
	if provider.get("license") != "CC BY 4.0":
		raise ValueError("UNHCR license changed unexpectedly.")

	excluded_codes = payload.get("excludedNonCountryCodes")
	if not isinstance(excluded_codes, list) or set(excluded_codes) != EXPECTED_EXCLUDED_CODES:
		raise ValueError(
			f"UNHCR excludedNonCountryCodes must remain {sorted(EXPECTED_EXCLUDED_CODES)}."
		)

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != len(EXPECTED_INDICATORS):
		raise ValueError("UNHCR config requires exactly eight indicators.")

	seen_ids: set[str] = set()
	seen_slugs: set[str] = set()
	actual: dict[str, tuple[str, str, int]] = {}
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("UNHCR indicator entries must be objects.")
		for key in ("id", "slug", "dimension", "sourceField", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"UNHCR indicator entry is missing {key}.")

		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		dimension = str(indicator["dimension"])
		source_field = str(indicator["sourceField"])
		first_year = indicator.get("firstYear")
		if indicator_id in seen_ids:
			raise ValueError(f"Duplicate UNHCR indicator id: {indicator_id}")
		if slug in seen_slugs:
			raise ValueError(f"Duplicate UNHCR indicator slug: {slug}")
		if dimension not in {"host", "origin"}:
			raise ValueError(f"UNHCR indicator {indicator_id} has invalid dimension {dimension}.")
		if not isinstance(first_year, int):
			raise ValueError(f"UNHCR indicator {indicator_id} has invalid firstYear.")
		seen_ids.add(indicator_id)
		seen_slugs.add(slug)
		actual[indicator_id] = (dimension, source_field, first_year)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or unit.get("id") != "people":
			raise ValueError(f"UNHCR indicator {indicator_id} must use the people unit.")

		common.validate_classification(indicator_id, indicator.get("classification"))
		classification = indicator["classification"]
		if classification.get("scale") != "logarithmic" or classification.get("breaks") != EXPECTED_BREAKS:
			raise ValueError(
				f"UNHCR indicator {indicator_id} must use shared logarithmic breaks {EXPECTED_BREAKS}."
			)

		minimum = indicator.get("minPositiveAreasInLatestYear")
		if not isinstance(minimum, int) or minimum <= 0:
			raise ValueError(f"UNHCR indicator {indicator_id} has invalid latest-year coverage minimum.")

	if actual != EXPECTED_INDICATORS:
		raise ValueError(
			f"Unexpected UNHCR indicator definitions: {actual!r}; expected {EXPECTED_INDICATORS!r}."
		)
	return payload


def fetch_pages(
	api_base: str,
	path: str,
	params: dict[str, Any],
	timeout: int,
) -> tuple[list[dict[str, Any]], int]:
	rows: list[dict[str, Any]] = []
	page = 1
	max_pages: int | None = None
	while True:
		query = dict(params)
		query["limit"] = 1000
		query["page"] = page
		url = f"{api_base.rstrip('/')}/{path.strip('/')}/?{urlencode(query)}"
		payload = common.fetch_json(url, timeout)
		if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
			raise RuntimeError(f"Unexpected UNHCR payload shape: {url}")

		payload_page = int(payload.get("page", page))
		if payload_page != page:
			raise RuntimeError(f"UNHCR pagination mismatch for {path}: expected {page}, got {payload_page}.")

		current_max = int(payload.get("maxPages", 1))
		if current_max < 1:
			raise RuntimeError(f"UNHCR returned invalid maxPages={current_max}: {url}")
		if max_pages is None:
			max_pages = current_max
		elif current_max != max_pages:
			raise RuntimeError(f"UNHCR maxPages changed while paging {path}: {max_pages} -> {current_max}.")

		rows.extend(row for row in payload["items"] if isinstance(row, dict))
		if page >= max_pages:
			break
		page += 1

	print(f"Fetched UNHCR {path}: rows={len(rows)} pages={max_pages} params={params}")
	return rows, int(max_pages or 1)


def parse_population(value: Any) -> int | float | None:
	if value is None:
		return None
	if isinstance(value, bool):
		raise ValueError("Boolean is not a UNHCR population value.")
	if isinstance(value, (int, float)):
		number = float(value)
	else:
		text = str(value).strip().replace(",", "")
		if text in {"", "-"}:
			return None
		number = float(text)
	if not math.isfinite(number) or number < 0:
		raise ValueError(f"Invalid UNHCR population value: {value!r}")
	return int(number) if number.is_integer() else number


def build_series(
	config: dict[str, Any],
	indicator: dict[str, Any],
	rows: list[dict[str, Any]],
	area_by_iso3: dict[str, str],
) -> tuple[dict[int, dict[str, int | float]], dict[str, Any]]:
	dimension = str(indicator["dimension"])
	code_field = "coa_iso" if dimension == "host" else "coo_iso"
	source_field = str(indicator["sourceField"])
	first_year = int(indicator["firstYear"])
	latest_year = int(config["latestYear"])
	excluded_codes = set(str(value) for value in config["excludedNonCountryCodes"])

	values_by_year: dict[int, dict[str, int | float]] = {}
	numeric_areas: set[str] = set()
	positive_areas: set[str] = set()
	excluded_observations: dict[str, int] = defaultdict(int)
	excluded_totals: dict[str, float] = defaultdict(float)
	missing_code_rows = 0
	missing_value_rows = 0
	retained_observations = 0

	for row in rows:
		raw_year = row.get("year")
		try:
			year = int(raw_year)
		except (TypeError, ValueError):
			continue
		if year < first_year or year > latest_year:
			continue

		code = str(row.get(code_field) or "").strip().upper()
		if not code or code == "-":
			missing_code_rows += 1
			continue

		number = parse_population(row.get(source_field))
		if number is None:
			missing_value_rows += 1
			continue

		if code in excluded_codes:
			excluded_observations[code] += 1
			excluded_totals[code] += float(number)
			continue
		if code not in area_by_iso3:
			raise RuntimeError(
				f"Unexpected unmapped UNHCR code for {indicator['id']}: {code} "
				f"({year}, {dimension}, {source_field})."
			)

		area_id = area_by_iso3[code]
		year_values = values_by_year.setdefault(year, {})
		if area_id in year_values:
			raise RuntimeError(f"Duplicate UNHCR value for {indicator['id']} {area_id} {year}.")
		year_values[area_id] = number
		numeric_areas.add(area_id)
		if float(number) > 0:
			positive_areas.add(area_id)
		retained_observations += 1

	positive_years = sorted(
		year
		for year, mapped in values_by_year.items()
		if any(float(value) > 0 for value in mapped.values())
	)
	if not positive_years:
		raise RuntimeError(f"UNHCR returned no positive mapped observations for {indicator['id']}.")
	if positive_years[0] != first_year:
		raise RuntimeError(
			f"UNHCR positive history for {indicator['id']} starts at {positive_years[0]}, "
			f"expected {first_year}."
		)

	available_years = sorted(values_by_year)
	if not available_years or available_years[-1] != latest_year:
		raise RuntimeError(
			f"UNHCR mapped history for {indicator['id']} ends at "
			f"{available_years[-1] if available_years else None}, expected {latest_year}."
		)

	latest = values_by_year[latest_year]
	latest_positive = {
		area_id: value
		for area_id, value in latest.items()
		if float(value) > 0
	}
	minimum_positive = int(indicator["minPositiveAreasInLatestYear"])
	if len(latest_positive) < minimum_positive:
		raise RuntimeError(
			f"UNHCR latest-year positive coverage too small for {indicator['id']}: "
			f"{len(latest_positive)}, expected at least {minimum_positive}."
		)

	return values_by_year, {
		"sourceRows": len(rows),
		"retainedObservations": retained_observations,
		"areasWithAnyNumericValue": len(numeric_areas),
		"areasWithAnyPositiveValue": len(positive_areas),
		"firstPositiveYear": positive_years[0],
		"latestYear": latest_year,
		"latestNumericAreas": len(latest),
		"latestPositiveAreas": len(latest_positive),
		"latestSum": int(sum(float(value) for value in latest.values())),
		"missingCodeRows": missing_code_rows,
		"missingValueRows": missing_value_rows,
		"excludedNonCountryObservations": {
			code: excluded_observations.get(code, 0)
			for code in sorted(excluded_codes)
		},
		"excludedNonCountryTotals": {
			code: int(excluded_totals.get(code, 0.0))
			for code in sorted(excluded_codes)
		},
	}


def build_indicator_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_year: dict[int, dict[str, int | float]],
	diagnostics: dict[str, Any],
) -> dict[str, Any]:
	provider = config["provider"]
	available_years = sorted(values_by_year)
	default_year = int(config["latestYear"])
	dimension = str(indicator["dimension"])
	source_field = str(indicator["sourceField"])
	dimension_param = "coa_all" if dimension == "host" else "coo_all"
	api_query = {
		"yearFrom": int(indicator["firstYear"]),
		"yearTo": int(config["latestYear"]),
		dimension_param: "true",
		"cf_type": "ISO",
	}
	api_url = f"{str(config['apiBase']).rstrip('/')}/population/?{urlencode(api_query)}"

	payload = {
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
			"release": config["release"],
			"releaseDate": config["releaseDate"],
			"indicator": source_field,
			"dimension": dimension,
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourceUrl"],
			"methodologyUrl": config["methodologyUrl"],
			"apiDocumentationUrl": config["apiDocumentationUrl"],
			"apiUrl": api_url,
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": diagnostics["areasWithAnyNumericValue"],
			"areasWithAnyPositiveValue": diagnostics["areasWithAnyPositiveValue"],
			"latestYear": default_year,
			"areasInLatestYear": diagnostics["latestNumericAreas"],
			"positiveAreasInLatestYear": diagnostics["latestPositiveAreas"],
			"latestYearSum": diagnostics["latestSum"],
			"observations": diagnostics["retainedObservations"],
		},
		"values": {
			str(year): {
				area_id: values_by_year[year][area_id]
				for area_id in sorted(values_by_year[year])
			}
			for year in available_years
		},
	}

	print(
		f"{indicator['id']}: observations={diagnostics['retainedObservations']} "
		f"positiveHistory={diagnostics['firstPositiveYear']}-{default_year} "
		f"latestNumeric={diagnostics['latestNumericAreas']} "
		f"latestPositive={diagnostics['latestPositiveAreas']} "
		f"latestSum={diagnostics['latestSum']}"
	)
	return payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("UNHCR is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	api_base = str(config["apiBase"]).rstrip("/")
	latest_year = int(config["latestYear"])

	host_rows, host_pages = fetch_pages(
		api_base,
		"population",
		{
			"yearFrom": 1951,
			"yearTo": latest_year,
			"coa_all": "true",
			"cf_type": "ISO",
		},
		args.timeout,
	)
	origin_rows, origin_pages = fetch_pages(
		api_base,
		"population",
		{
			"yearFrom": 1951,
			"yearTo": latest_year,
			"coo_all": "true",
			"cf_type": "ISO",
		},
		args.timeout,
	)

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		rows = host_rows if indicator["dimension"] == "host" else origin_rows
		values_by_year, diagnostics = build_series(config, indicator, rows, area_by_iso3)
		payload = build_indicator_payload(config, indicator, area_by_iso3, values_by_year, diagnostics)
		indicator_payloads.append((indicator, payload, diagnostics))

	hasher = hashlib.sha256()
	for indicator, payload, _diagnostics in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(common.canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	now = datetime.now(timezone.utc)
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []
	dataset_indicators: dict[str, Any] = {}

	for indicator, payload, diagnostics in indicator_payloads:
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
			"sourceIndicator": indicator["sourceField"],
			"sourceDimension": indicator["dimension"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		})
		dataset_indicators[str(indicator["id"])] = diagnostics

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
			"url": config["sourceUrl"],
			"methodologyUrl": config["methodologyUrl"],
			"apiDocumentationUrl": config["apiDocumentationUrl"],
			"apiBase": config["apiBase"],
			"release": config["release"],
			"releaseDate": config["releaseDate"],
			"latestYear": latest_year,
			"excludedNonCountryCodes": config["excludedNonCountryCodes"],
			"fetch": {
				"hostRows": len(host_rows),
				"hostPages": host_pages,
				"originRows": len(origin_rows),
				"originPages": origin_pages,
			},
			"indicators": dataset_indicators,
		},
		"indicators": index_indicators,
		"notes": [
			"UNHCR categories are published separately; refugees, asylum-seekers and other people in need of international protection are not merged into one artificial time series.",
			"The IDP indicator covers only internally displaced people to whom UNHCR provides protection and/or assistance; it is not a global IDP total.",
			"UNHCR may round small population counts for confidentiality. Published source values are retained as provided.",
			"UNK, TIB and XXA are non-country source codes and are excluded from the country layer; they are never reassigned to a country.",
			"No fallback, interpolation or extrapolation is used.",
		],
	}

	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built UNHCR snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
