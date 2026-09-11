#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pycountry

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "who-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build normalized country statistics from WHO World Health Data Hub CSV files.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=60)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.who-statistics/v1":
		raise ValueError("Invalid WHO statistics config.")
	provider = payload.get("provider")
	if not isinstance(provider, dict):
		raise ValueError("WHO provider metadata is required.")
	for key in ("id", "name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"WHO provider metadata is missing {key}.")
	if provider.get("id") != "who":
		raise ValueError("WHO provider id must be 'who'.")
	expected_year = payload.get("expectedReferenceYear")
	if not isinstance(expected_year, int) or not 1900 <= expected_year <= 2200:
		raise ValueError("WHO expectedReferenceYear is invalid.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("WHO config requires indicators.")
	ids: set[str] = set()
	slugs: set[str] = set()
	source_codes: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("WHO indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "sourceUuid", "sourceUrl", "downloadUrl", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"WHO indicator entry is missing {key}.")
		if not str(indicator["sourceUrl"]).startswith("https://") or not str(indicator["downloadUrl"]).startswith("https://"):
			raise ValueError(f"WHO indicator {indicator['id']} source URLs must use HTTPS.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		source_code = str(indicator["sourceIndicator"])
		if indicator_id in ids or slug in slugs or source_code in source_codes:
			raise ValueError(f"Duplicate WHO indicator metadata: {indicator_id}.")
		ids.add(indicator_id)
		slugs.add(slug)
		source_codes.add(source_code)
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"WHO indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		if not isinstance(indicator.get("minAreasWithAnyValue"), int) or int(indicator["minAreasWithAnyValue"]) <= 0:
			raise ValueError(f"WHO indicator {indicator_id} has invalid minAreasWithAnyValue.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"WHO indicator {indicator_id} requires requiredAreas.")
	return payload


def normalize_m49(value: Any) -> str:
	text = str(value if value is not None else "").strip()
	if not text:
		return ""
	try:
		number = int(float(text))
	except ValueError:
		return ""
	return str(number)


def load_registry_by_m49(source: str, timeout: int) -> tuple[dict[str, str], dict[str, Any]]:
	area_by_iso3, payload = common.load_registry(source, timeout)
	area_by_m49: dict[str, str] = {}
	for country in pycountry.countries:
		iso3 = str(getattr(country, "alpha_3", "")).strip().upper()
		m49 = normalize_m49(getattr(country, "numeric", ""))
		if not iso3 or not m49 or iso3 not in area_by_iso3:
			continue
		if m49 in area_by_m49:
			raise ValueError(f"Duplicate M49 code from ISO-3166 mapping: {m49}")
		area_by_m49[m49] = area_by_iso3[iso3]
	if len(area_by_m49) < 245:
		raise RuntimeError(f"ISO-3166/M49 mapping unexpectedly small: {len(area_by_m49)} country areas.")
	for required in ("40", "276", "840", "356"):
		if required not in area_by_m49:
			raise RuntimeError(f"M49 sanity check failed: {required} is missing.")
	return area_by_m49, payload


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
			rows = list(csv.DictReader(io.StringIO(text)))
			if not rows:
				raise RuntimeError(f"WHO CSV is empty: {url}")
			return rows, len(data)
		except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, csv.Error, RuntimeError) as error:
			last_error = error
			print(f"WHO request failed ({attempt}/{len(delays)}): {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"WHO request failed without exception: {url}")
	raise RuntimeError(f"WHO request failed after {len(delays)} attempts: {url}") from last_error


def parse_number(value: Any) -> int | float:
	if value is None or str(value).strip() == "":
		raise ValueError("Missing WHO numeric value.")
	number = float(str(value).strip())
	if not math.isfinite(number):
		raise ValueError("WHO numeric value is not finite.")
	if number.is_integer():
		return int(number)
	return number


def normalize_indicator(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_m49: dict[str, str],
) -> dict[str, Any]:
	rows, byte_count = fetch_csv(str(indicator["downloadUrl"]), 90)
	print(f"WHO {indicator['sourceIndicator']}: downloaded={byte_count} bytes rows={len(rows)}")
	required_fields = {
		"IND_CODE", "IND_UUID", "DIM_TIME", "DIM_TIME_TYPE", "DIM_GEO_CODE_M49",
		"DIM_GEO_CODE_TYPE", "DIM_PUBLISH_STATE_CODE", "IND_NAME", "GEO_NAME_SHORT",
		"RATE_PER_100_N", "RATE_PER_100_NL", "RATE_PER_100_NU",
	}
	missing_fields = required_fields - set(rows[0])
	if missing_fields:
		raise RuntimeError(f"WHO CSV schema changed for {indicator['id']}: missing {sorted(missing_fields)}")

	expected_year = int(config["expectedReferenceYear"])
	values: dict[str, int | float] = {}
	intervals: dict[str, dict[str, int | float]] = {}
	ignored_m49: set[str] = set()
	for row in rows:
		if str(row.get("IND_CODE", "")).strip() != str(indicator["sourceIndicator"]):
			raise RuntimeError(f"WHO indicator code mismatch in {indicator['id']}.")
		if str(row.get("IND_UUID", "")).strip() != str(indicator["sourceUuid"]):
			raise RuntimeError(f"WHO indicator UUID mismatch in {indicator['id']}.")
		if str(row.get("DIM_TIME_TYPE", "")).strip() != "YEAR":
			continue
		if str(row.get("DIM_GEO_CODE_TYPE", "")).strip() != "COUNTRY":
			continue
		if str(row.get("DIM_PUBLISH_STATE_CODE", "")).strip() != "PUBLISHED":
			continue
		year_text = str(row.get("DIM_TIME", "")).strip()
		if not year_text.isdigit() or int(year_text) != expected_year:
			raise RuntimeError(f"WHO reference year changed for {indicator['id']}: {year_text!r}, expected {expected_year}.")
		m49 = normalize_m49(row.get("DIM_GEO_CODE_M49"))
		if m49 not in area_by_m49:
			if m49:
				ignored_m49.add(m49)
			continue
		area_id = area_by_m49[m49]
		value = parse_number(row.get("RATE_PER_100_N"))
		lower = parse_number(row.get("RATE_PER_100_NL"))
		upper = parse_number(row.get("RATE_PER_100_NU"))
		if not 0 <= float(lower) <= float(value) <= float(upper) <= 100:
			raise RuntimeError(f"WHO confidence interval is invalid for {indicator['id']} {area_id}: {lower}, {value}, {upper}")
		if area_id in values:
			raise RuntimeError(f"Duplicate WHO country value for {indicator['id']} {area_id}.")
		values[area_id] = value
		intervals[area_id] = {"lower": lower, "upper": upper}

	minimum = int(indicator["minAreasWithAnyValue"])
	if len(values) < minimum:
		raise RuntimeError(f"WHO coverage too small for {indicator['id']}: {len(values)} areas, expected at least {minimum}.")
	for area_id in indicator["requiredAreas"]:
		if area_id not in values:
			raise RuntimeError(f"Required area {area_id} has no WHO value for {indicator['id']}.")

	indicator_metadata = {
		"id": indicator["id"],
		"title": indicator["title"],
		"description": indicator["description"],
		"areaLevel": "country",
		"frequency": "reference-year",
		"unit": indicator["unit"],
		"classification": indicator["classification"],
		"confidenceIntervals": {
			"available": True,
			"lowerField": "RATE_PER_100_NL",
			"upperField": "RATE_PER_100_NU",
		},
	}
	provider = config["provider"]
	payload = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": indicator_metadata,
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"indicator": indicator["sourceIndicator"],
			"indicatorUuid": indicator["sourceUuid"],
			"indicatorName": next((str(row.get("IND_NAME", "")).strip() for row in rows if str(row.get("IND_NAME", "")).strip()), None),
			"provenance": "WHO official modeled estimate",
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": indicator["sourceUrl"],
			"downloadUrl": indicator["downloadUrl"],
			"referenceYear": expected_year,
		},
		"availableYears": [expected_year],
		"defaultYear": expected_year,
		"coverage": {
			"registryAreas": len(area_by_m49),
			"areasWithAnyValue": len(values),
			"latestYear": expected_year,
			"areasInLatestYear": len(values),
			"areasInDefaultYear": len(values),
		},
		"values": {
			str(expected_year): {area_id: values[area_id] for area_id in sorted(values)},
		},
		"confidenceIntervals": {
			"values": {
				str(expected_year): {area_id: intervals[area_id] for area_id in sorted(intervals)},
			},
		},
	}
	print(
		f"{indicator['id']}: mapped={len(values)} year={expected_year} "
		f"ignoredM49={sorted(ignored_m49) or '(none)'}"
	)
	return payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("WHO is missing from statistics-providers.json.")
	area_by_m49, registry_payload = load_registry_by_m49(args.registry, args.timeout)
	now = datetime.now(timezone.utc)
	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload = normalize_indicator(config, indicator, area_by_m49)
		indicator_payloads.append((indicator, payload))

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
			"frequency": "reference-year",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"sourceIndicator": indicator["sourceIndicator"],
			"sourceUuid": indicator["sourceUuid"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
			"confidenceIntervals": True,
		})

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_m49),
	}
	if registry_source["url"] is None:
		registry_source.pop("url")
	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"indicators": index_indicators,
		"notes": [
			"The current WHO World Health Data Hub machine-readable IPV indicators use reference year 2018.",
			"Confidence intervals are preserved in each indicator payload.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built WHO snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
