#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import time
from typing import Any
import urllib.parse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "undp-hdr-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
MISSING_VALUES = {"", "..", "nan", "na", "n/a"}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build normalized country statistics from UNDP Human Development Reports."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def utc_now() -> datetime:
	return datetime.now(timezone.utc)


def read_json(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.undp-hdr-statistics/v1":
		raise ValueError("Invalid UNDP HDR statistics config.")

	documentation_url = str(payload.get("documentationUrl", "")).strip()
	link_pattern = str(payload.get("downloadLinkPattern", "")).strip()
	minimum_latest = payload.get("minimumSourceLatestYear")
	if not documentation_url.startswith("https://hdr.undp.org/"):
		raise ValueError("UNDP HDR documentationUrl must use hdr.undp.org over HTTPS.")
	if not link_pattern.endswith(".csv"):
		raise ValueError("UNDP HDR downloadLinkPattern must identify a CSV file.")
	if not isinstance(minimum_latest, int) or not 1990 <= minimum_latest <= 2200:
		raise ValueError("UNDP HDR minimumSourceLatestYear is invalid.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "undp-hdr":
		raise ValueError("UNDP HDR provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"UNDP HDR provider metadata is missing {key}.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("UNDP HDR config requires indicators.")

	ids: set[str] = set()
	slugs: set[str] = set()
	prefixes: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("UNDP HDR indicator entries must be objects.")
		for key in ("id", "slug", "sourcePrefix", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"UNDP HDR indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		prefix = str(indicator["sourcePrefix"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate UNDP HDR indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate UNDP HDR indicator slug: {slug}")
		if prefix in prefixes:
			raise ValueError(f"Duplicate UNDP HDR source prefix: {prefix}")
		ids.add(indicator_id)
		slugs.add(slug)
		prefixes.add(prefix)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"UNDP HDR indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))

		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear", "minimumDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"UNDP HDR indicator {indicator_id} has invalid {key}.")
		required = indicator.get("requiredAreas")
		if not isinstance(required, list) or not required:
			raise ValueError(f"UNDP HDR indicator {indicator_id} requires at least one required area.")

		value_range = indicator.get("valueRange")
		if (
			not isinstance(value_range, list)
			or len(value_range) != 2
			or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in value_range)
			or not math.isfinite(float(value_range[0]))
			or not math.isfinite(float(value_range[1]))
			or float(value_range[0]) >= float(value_range[1])
		):
			raise ValueError(f"UNDP HDR indicator {indicator_id} has invalid valueRange.")

	return payload


def fetch_bytes(url: str, timeout: int, accept: str) -> tuple[bytes, dict[str, str]]:
	delays = (0, 5, 15, 30)
	last_error: Exception | None = None
	for attempt, delay in enumerate(delays, start=1):
		if delay:
			time.sleep(delay)
		request = Request(
			url,
			headers={
				"Accept": accept,
				"User-Agent": USER_AGENT,
			},
		)
		try:
			with urlopen(request, timeout=timeout) as response:
				data = response.read()
				headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
			if not data:
				raise RuntimeError(f"Empty response from {url}")
			return data, headers
		except (HTTPError, URLError, TimeoutError, RuntimeError) as error:
			last_error = error
			print(f"UNDP HDR request failed ({attempt}/{len(delays)}): {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"UNDP HDR request failed without exception: {url}")
	raise RuntimeError(f"UNDP HDR request failed after {len(delays)} attempts: {url}") from last_error


def discover_download_url(config: dict[str, Any], timeout: int) -> str:
	documentation_url = str(config["documentationUrl"])
	data, _headers = fetch_bytes(documentation_url, timeout, "text/html,*/*")
	page = data.decode("utf-8", errors="replace")
	pattern = re.escape(str(config["downloadLinkPattern"]))
	matches = re.findall(
		rf'href=["\']([^"\']*{pattern}[^"\']*)["\']',
		page,
		flags=re.IGNORECASE,
	)
	urls = list(
		dict.fromkeys(
			urllib.parse.urljoin(documentation_url, html.unescape(value))
			for value in matches
		)
	)
	if len(urls) != 1:
		raise RuntimeError(f"Expected exactly one UNDP HDR composite time-series CSV link, found {urls}")
	url = urls[0]
	parsed = urllib.parse.urlparse(url)
	if parsed.scheme != "https" or parsed.netloc != "hdr.undp.org":
		raise RuntimeError(f"Unexpected UNDP HDR download host: {url}")
	return url


def decode_csv(data: bytes) -> tuple[str, str]:
	for encoding in ("utf-8-sig", "cp1252", "latin-1"):
		try:
			return data.decode(encoding), encoding
		except UnicodeDecodeError:
			continue
	raise RuntimeError("Could not decode UNDP HDR CSV.")


def is_missing(raw: Any) -> bool:
	return str(raw if raw is not None else "").strip().lower() in MISSING_VALUES


def parse_number(raw: Any, indicator_id: str, iso3: str, year: int) -> int | float:
	text = str(raw).strip()
	try:
		value = common.normalize_number(text)
	except (TypeError, ValueError) as error:
		raise RuntimeError(
			f"Invalid UNDP HDR value for {indicator_id} {iso3} {year}: {text!r}"
		) from error
	if not math.isfinite(float(value)):
		raise RuntimeError(f"Non-finite UNDP HDR value for {indicator_id} {iso3} {year}.")
	return value


def source_years(fields: list[str], prefix: str) -> list[int]:
	pattern = re.compile(rf"{re.escape(prefix)}_([12][0-9]{{3}})")
	years = sorted(
		int(match.group(1))
		for field in fields
		if (match := pattern.fullmatch(field))
	)
	if not years:
		raise RuntimeError(f"UNDP HDR source series is missing: {prefix}")
	expected = list(range(years[0], years[-1] + 1))
	if years != expected:
		raise RuntimeError(f"UNDP HDR source years are not contiguous for {prefix}: {years}")
	return years


def choose_default_year(
	indicator: dict[str, Any],
	available_years: list[int],
	values_by_year: dict[int, dict[str, int | float]],
) -> int:
	minimum = int(indicator["minAreasInDefaultYear"])
	eligible = [year for year in available_years if len(values_by_year[year]) >= minimum]
	if not eligible:
		raise RuntimeError(
			f"UNDP HDR has no sufficiently complete default year for {indicator['id']}: "
			f"expected at least {minimum} mapped areas."
		)
	default_year = eligible[-1]
	if default_year < int(indicator["minimumDefaultYear"]):
		raise RuntimeError(
			f"UNDP HDR default year for {indicator['id']} is unexpectedly old: {default_year}."
		)
	return default_year


def build_indicator_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	rows: list[dict[str, str]],
	fields: list[str],
	area_by_iso3: dict[str, str],
	source_url: str,
) -> tuple[dict[str, Any], tuple[int, int]]:
	indicator_id = str(indicator["id"])
	prefix = str(indicator["sourcePrefix"])
	years = source_years(fields, prefix)
	if years[-1] < int(config["minimumSourceLatestYear"]):
		raise RuntimeError(
			f"UNDP HDR series {prefix} is unexpectedly old: latest source year {years[-1]}."
		)

	min_value, max_value = (float(value) for value in indicator["valueRange"])
	values_by_year: dict[int, dict[str, int | float]] = {}
	areas_with_any_value: set[str] = set()
	unresolved: set[str] = set()

	for year in years:
		column = f"{prefix}_{year}"
		year_values: dict[str, int | float] = {}
		for row in rows:
			raw = row.get(column, "")
			if is_missing(raw):
				continue
			source_code = str(row.get("iso3", "")).strip().upper()
			if not source_code:
				raise RuntimeError(f"UNDP HDR row with {column} value has no iso3 code.")
			if source_code.startswith("ZZ"):
				continue
			area_id = area_by_iso3.get(source_code)
			if not area_id:
				unresolved.add(source_code)
				continue
			value = parse_number(raw, indicator_id, source_code, year)
			numeric = float(value)
			if numeric < min_value or numeric > max_value:
				raise RuntimeError(
					f"UNDP HDR value outside configured range for {indicator_id} "
					f"{source_code} {year}: {value} not in {indicator['valueRange']}"
				)
			if area_id in year_values:
				raise RuntimeError(f"Duplicate UNDP HDR value for {indicator_id} {year} {area_id}.")
			year_values[area_id] = value
			areas_with_any_value.add(area_id)
		if year_values:
			values_by_year[year] = year_values

	if unresolved:
		raise RuntimeError(f"Unexpected unmapped UNDP HDR country codes for {indicator_id}: {sorted(unresolved)}")
	if len(areas_with_any_value) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"UNDP HDR indicator {indicator_id} maps only {len(areas_with_any_value)} areas; "
			f"expected at least {indicator['minAreasWithAnyValue']}."
		)
	if not values_by_year:
		raise RuntimeError(f"UNDP HDR returned no mapped values for {indicator_id}.")

	available_years = sorted(values_by_year)
	default_year = choose_default_year(indicator, available_years, values_by_year)
	for area_id in indicator["requiredAreas"]:
		if area_id not in values_by_year[default_year]:
			raise RuntimeError(
				f"Required area {area_id} has no UNDP HDR value for {indicator_id} in default year {default_year}."
			)

	sorted_values = {
		str(year): {
			area_id: values_by_year[year][area_id]
			for area_id in sorted(values_by_year[year])
		}
		for year in available_years
	}

	provider = config["provider"]
	indicator_metadata: dict[str, Any] = {
		"id": indicator_id,
		"title": indicator["title"],
		"description": indicator["description"],
		"areaLevel": "country",
		"frequency": "annual",
		"unit": indicator["unit"],
	}
	if isinstance(indicator.get("classification"), dict):
		indicator_metadata["classification"] = indicator["classification"]

	payload = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": indicator_metadata,
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"indicator": prefix,
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": source_url,
			"documentationUrl": config["documentationUrl"],
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": available_years[-1],
			"areasInLatestYear": len(values_by_year[available_years[-1]]),
			"areasInDefaultYear": len(values_by_year[default_year]),
		},
		"values": sorted_values,
	}

	print(
		f"{indicator_id}: mapped={len(areas_with_any_value)} "
		f"years={available_years[0]}-{available_years[-1]} "
		f"defaultYear={default_year} defaultCoverage={len(values_by_year[default_year])}"
	)
	return payload, (years[0], years[-1])


def canonical_bytes(payload: Any) -> bytes:
	return json.dumps(
		payload,
		ensure_ascii=False,
		sort_keys=True,
		separators=(",", ":"),
	).encode("utf-8")


def write_json(path: Path, payload: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		json.dumps(payload, ensure_ascii=False, indent="\t") + "\n",
		encoding="utf-8",
	)


def main() -> None:
	args = parse_args()
	config = validate_config(read_json(args.config))
	provider_catalog = common.validate_provider_catalog(read_json(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	source_url = discover_download_url(config, args.timeout)
	data, headers = fetch_bytes(source_url, args.timeout, "text/csv,*/*")
	text, encoding = decode_csv(data)
	reader = csv.DictReader(io.StringIO(text))
	fields = reader.fieldnames or []
	rows = list(reader)
	required_identity = {"iso3", "country", "hdicode", "region"}
	if not required_identity.issubset(fields):
		raise RuntimeError(
			f"UNDP HDR CSV schema changed: missing identity fields {sorted(required_identity - set(fields))}."
		)
	if len(rows) < 190:
		raise RuntimeError(f"UNDP HDR CSV unexpectedly small: {len(rows)} rows.")
	source_codes = [str(row.get("iso3", "")).strip().upper() for row in rows]
	nonempty_codes = [code for code in source_codes if code]
	if len(nonempty_codes) != len(set(nonempty_codes)):
		raise RuntimeError("UNDP HDR CSV contains duplicate non-empty iso3 rows.")

	print(
		f"UNDP HDR source: url={source_url} bytes={len(data)} rows={len(rows)} "
		f"columns={len(fields)} encoding={encoding}"
	)

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	source_ranges: dict[str, dict[str, int]] = {}
	for indicator in config["indicators"]:
		payload, (source_start, source_latest) = build_indicator_payload(
			config,
			indicator,
			rows,
			fields,
			area_by_iso3,
			source_url,
		)
		indicator_payloads.append((indicator, payload))
		source_ranges[str(indicator["sourcePrefix"])] = {
			"sourceStartYear": source_start,
			"sourceLatestYear": source_latest,
		}

	hasher = hashlib.sha256()
	for indicator, payload in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	output_dir = args.output_dir
	provider_dir = output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []

	for indicator, payload in indicator_payloads:
		filename = f"{indicator['slug']}.json"
		write_json(release_dir / filename, payload)
		item: dict[str, Any] = {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"sourceIndicator": indicator["sourcePrefix"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		}
		if isinstance(indicator.get("classification"), dict):
			item["classification"] = indicator["classification"]
		index_indicators.append(item)

	registry_source: dict[str, Any] = {
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_iso3),
	}
	if args.registry.startswith(("https://", "http://")):
		registry_source["url"] = args.registry

	dataset: dict[str, Any] = {
		"documentationUrl": config["documentationUrl"],
		"sourceUrl": source_url,
		"encoding": encoding,
		"bytes": len(data),
		"sourceSeries": source_ranges,
	}
	if headers.get("last-modified"):
		dataset["lastModified"] = headers["last-modified"]
	if headers.get("etag"):
		dataset["etag"] = headers["etag"]

	now = utc_now()
	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"dataset": dataset,
		"indicators": index_indicators,
	}
	write_json(provider_dir / "index.json", provider_index)
	write_json(output_dir / "index.json", common.build_global_index(provider_catalog))

	print(f"Built UNDP HDR snapshot {snapshot}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
