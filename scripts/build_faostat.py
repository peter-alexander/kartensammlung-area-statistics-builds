#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "faostat-food-security-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
EXPECTED_DATA_FILE = "Food_Security_Data_E_All_Data_(Normalized).csv"
EXPECTED_AREA_FILE = "Food_Security_Data_E_AreaCodes.csv"
EXPECTED_FLAG_FILE = "Food_Security_Data_E_Flags.csv"
REQUIRED_FIELDS = {
	"Area Code (M49)",
	"Area",
	"Item Code",
	"Item",
	"Element",
	"Year",
	"Unit",
	"Value",
	"Flag",
	"Note",
}
PERIOD_RE = re.compile(r"^([12]\d{3})-([12]\d{3})$")
CENSORED_RE = re.compile(r"^\s*([<>])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$")


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build normalized country statistics from FAOSTAT Suite of Food Security Indicators."
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
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.faostat-food-security-statistics/v1":
		raise ValueError("Invalid FAOSTAT food-security statistics config.")

	documentation_url = str(payload.get("documentationUrl", "")).strip()
	bulk_url = str(payload.get("bulkUrl", "")).strip()
	terms_url = str(payload.get("termsUrl", "")).strip()
	if not documentation_url.startswith("https://www.fao.org/faostat/"):
		raise ValueError("FAOSTAT documentationUrl must use www.fao.org/faostat over HTTPS.")
	if not bulk_url.startswith("https://bulks-faostat.fao.org/production/") or not bulk_url.endswith(".zip"):
		raise ValueError("FAOSTAT bulkUrl must point to the production bulk ZIP.")
	if not terms_url.startswith("https://www.fao.org/"):
		raise ValueError("FAOSTAT termsUrl must use fao.org over HTTPS.")

	minimum_latest = payload.get("minimumLatestPeriodEndYear")
	if not isinstance(minimum_latest, int) or not 2000 <= minimum_latest <= 2200:
		raise ValueError("FAOSTAT minimumLatestPeriodEndYear is invalid.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "faostat":
		raise ValueError("FAOSTAT provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"FAOSTAT provider metadata is missing {key}.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("FAOSTAT config requires indicators.")

	ids: set[str] = set()
	slugs: set[str] = set()
	source_codes: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("FAOSTAT indicator entries must be objects.")
		for key in ("id", "slug", "sourceItemCode", "title", "description", "sourceUnit"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"FAOSTAT indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		source_code = str(indicator["sourceItemCode"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate FAOSTAT indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate FAOSTAT indicator slug: {slug}")
		if source_code in source_codes:
			raise ValueError(f"Duplicate FAOSTAT source item code: {source_code}")
		ids.add(indicator_id)
		slugs.add(slug)
		source_codes.add(source_code)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"FAOSTAT indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))

		for key in ("minAreasWithAnyValue", "minAreasInDefaultPeriod", "minimumDefaultPeriodEndYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"FAOSTAT indicator {indicator_id} has invalid {key}.")
		required = indicator.get("requiredAreas")
		if not isinstance(required, list) or not required:
			raise ValueError(f"FAOSTAT indicator {indicator_id} requires at least one required area.")

		value_range = indicator.get("valueRange")
		if (
			not isinstance(value_range, list)
			or len(value_range) != 2
			or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in value_range)
			or not math.isfinite(float(value_range[0]))
			or not math.isfinite(float(value_range[1]))
			or float(value_range[0]) >= float(value_range[1])
		):
			raise ValueError(f"FAOSTAT indicator {indicator_id} has invalid valueRange.")

	return payload


def fetch_bytes(url: str, timeout: int) -> tuple[bytes, dict[str, str]]:
	delays = (0, 5, 15, 30)
	last_error: Exception | None = None
	for attempt, delay in enumerate(delays, start=1):
		if delay:
			time.sleep(delay)
		request = Request(
			url,
			headers={
				"Accept": "application/zip,application/octet-stream,*/*",
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
			print(f"FAOSTAT request failed ({attempt}/{len(delays)}): {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"FAOSTAT request failed without exception: {url}")
	raise RuntimeError(f"FAOSTAT request failed after {len(delays)} attempts: {url}") from last_error


def decode_csv(data: bytes) -> tuple[str, str]:
	for encoding in ("utf-8-sig", "cp1252", "latin-1"):
		try:
			return data.decode(encoding), encoding
		except UnicodeDecodeError:
			continue
	raise RuntimeError("Could not decode FAOSTAT CSV.")


def read_csv_from_archive(archive: zipfile.ZipFile, name: str) -> tuple[list[dict[str, str]], list[str], str]:
	if name not in archive.namelist():
		raise RuntimeError(f"FAOSTAT ZIP is missing {name}.")
	text, encoding = decode_csv(archive.read(name))
	reader = csv.DictReader(io.StringIO(text))
	fields = reader.fieldnames or []
	return list(reader), fields, encoding


def normalize_m49(raw: Any) -> str:
	text = str(raw if raw is not None else "").strip().lstrip("'")
	if not text:
		return ""
	if not text.isdigit():
		raise RuntimeError(f"Invalid FAOSTAT M49 code: {raw!r}")
	text = text.zfill(3)
	if len(text) != 3:
		raise RuntimeError(f"Invalid FAOSTAT M49 code width: {raw!r}")
	return text


def load_registry_by_m49(source: str, timeout: int) -> tuple[dict[str, str], dict[str, Any], int]:
	payload = common.load_json_source(source, timeout)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.area-registry/v1":
		raise ValueError("Invalid area registry.")
	areas = payload.get("areas")
	if not isinstance(areas, list) or not areas:
		raise ValueError("Area registry has no areas.")

	area_by_m49: dict[str, str] = {}
	country_count = 0
	for area in areas:
		if not isinstance(area, dict) or area.get("level") != "country":
			continue
		country_count += 1
		area_id = str(area.get("area_id", "")).strip()
		codes = area.get("codes")
		if not isinstance(codes, dict):
			continue
		m49 = str(codes.get("m49", "")).strip()
		if not m49:
			continue
		if not re.fullmatch(r"\d{3}", m49):
			raise RuntimeError(f"Invalid M49 code in area registry for {area_id}: {m49!r}")
		if m49 in area_by_m49:
			raise RuntimeError(f"Duplicate M49 code in area registry: {m49}")
		area_by_m49[m49] = area_id

	if country_count < 240:
		raise RuntimeError(f"Area registry unexpectedly small: {country_count} country areas.")
	if len(area_by_m49) < 240:
		raise RuntimeError(f"Area registry has unexpectedly few M49-coded countries: {len(area_by_m49)}.")
	for required in ("040", "276", "840", "356", "156"):
		if required not in area_by_m49:
			raise RuntimeError(f"Area registry M49 sanity check failed: {required} is missing.")
	return area_by_m49, payload, country_count


def parse_period(raw: Any) -> tuple[str, int]:
	text = str(raw if raw is not None else "").strip()
	match = PERIOD_RE.fullmatch(text)
	if match is None:
		raise RuntimeError(f"Expected a three-year FAOSTAT period, got {text!r}.")
	start = int(match.group(1))
	end = int(match.group(2))
	if end - start != 2:
		raise RuntimeError(f"Expected a three-year FAOSTAT period, got {text!r}.")
	return text, end


def parse_value(
	raw: Any,
	indicator_id: str,
	m49: str,
	period: str,
) -> tuple[int | float | None, dict[str, Any]]:
	text = str(raw if raw is not None else "").strip()
	if not text:
		return None, {}

	metadata: dict[str, Any] = {}
	censored = CENSORED_RE.fullmatch(text)
	if censored:
		operator = censored.group(1)
		value = common.normalize_number(censored.group(2))
		metadata["valueQualifier"] = "less-than" if operator == "<" else "greater-than"
		metadata["displayValue"] = f"{operator}{censored.group(2)}"
		if operator == "<":
			metadata["upperBound"] = value
		else:
			metadata["lowerBound"] = value
	else:
		try:
			value = common.normalize_number(text)
		except (TypeError, ValueError) as error:
			raise RuntimeError(
				f"Invalid FAOSTAT value for {indicator_id} M49={m49} {period}: {text!r}"
			) from error

	if not math.isfinite(float(value)):
		raise RuntimeError(f"Non-finite FAOSTAT value for {indicator_id} M49={m49} {period}.")
	return value, metadata


def choose_default_year(
	indicator: dict[str, Any],
	available_years: list[int],
	values_by_year: dict[int, dict[str, int | float]],
) -> int:
	minimum = int(indicator["minAreasInDefaultPeriod"])
	eligible = [year for year in available_years if len(values_by_year[year]) >= minimum]
	if not eligible:
		raise RuntimeError(
			f"FAOSTAT has no sufficiently complete default period for {indicator['id']}: "
			f"expected at least {minimum} mapped areas."
		)
	default_year = eligible[-1]
	if default_year < int(indicator["minimumDefaultPeriodEndYear"]):
		raise RuntimeError(
			f"FAOSTAT default period for {indicator['id']} is unexpectedly old: endpoint {default_year}."
		)
	return default_year


def flag_descriptions(rows: list[dict[str, str]], fields: list[str]) -> dict[str, str]:
	if not rows:
		return {}
	flag_field = "Flag" if "Flag" in fields else fields[0] if fields else ""
	description_candidates = [
		"Description",
		"Flag Description",
		"Meaning",
	]
	description_field = next((name for name in description_candidates if name in fields), "")
	if not flag_field or not description_field:
		return {}
	result: dict[str, str] = {}
	for row in rows:
		code = str(row.get(flag_field, "")).strip()
		description = str(row.get(description_field, "")).strip()
		if code and description:
			result[code] = description
	return dict(sorted(result.items()))


def build_indicator_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	rows: list[dict[str, str]],
	area_by_m49: dict[str, str],
	source_url: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
	indicator_id = str(indicator["id"])
	source_code = str(indicator["sourceItemCode"])
	source_rows = [
		row
		for row in rows
		if str(row.get("Item Code", "")).strip() == source_code
		and str(row.get("Element", "")).strip() == "Value"
	]
	if not source_rows:
		raise RuntimeError(f"FAOSTAT source item is missing: {source_code} ({indicator_id}).")

	values_by_year: dict[int, dict[str, int | float]] = defaultdict(dict)
	metadata_by_year: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
	period_labels: dict[int, str] = {}
	areas_with_any_value: set[str] = set()
	source_names: set[str] = set()
	ignored_source_areas: dict[str, str] = {}
	censored_count = 0
	missing_count = 0
	source_units: set[str] = set()

	min_value, max_value = (float(value) for value in indicator["valueRange"])
	for row in source_rows:
		unit = str(row.get("Unit", "")).strip()
		source_units.add(unit)
		if unit != str(indicator["sourceUnit"]):
			raise RuntimeError(
				f"Unexpected FAOSTAT unit for {indicator_id}: {unit!r}; expected {indicator['sourceUnit']!r}."
			)

		period, end_year = parse_period(row.get("Year"))
		existing_period = period_labels.get(end_year)
		if existing_period is not None and existing_period != period:
			raise RuntimeError(
				f"Conflicting FAOSTAT periods for endpoint {end_year}: {existing_period!r} vs {period!r}."
			)
		period_labels[end_year] = period

		m49 = normalize_m49(row.get("Area Code (M49)"))
		if not m49:
			raise RuntimeError(f"FAOSTAT row with {indicator_id} value is missing M49.")
		area_name = str(row.get("Area", "")).strip()
		area_id = area_by_m49.get(m49)
		if not area_id:
			ignored_source_areas[m49] = area_name
			continue

		value, observation = parse_value(row.get("Value"), indicator_id, m49, period)
		if value is None:
			missing_count += 1
			continue
		numeric = float(value)
		if numeric < min_value or numeric > max_value:
			raise RuntimeError(
				f"FAOSTAT value outside configured range for {indicator_id} "
				f"M49={m49} {period}: {value} not in {indicator['valueRange']}"
			)
		if area_id in values_by_year[end_year]:
			raise RuntimeError(f"Duplicate FAOSTAT value for {indicator_id} {period} {area_id}.")
		values_by_year[end_year][area_id] = value
		areas_with_any_value.add(area_id)
		source_names.add(str(row.get("Item", "")).strip())

		flag = str(row.get("Flag", "")).strip()
		note = str(row.get("Note", "")).strip()
		if observation.get("valueQualifier"):
			censored_count += 1
		if flag:
			observation["sourceFlag"] = flag
		if note:
			observation["sourceNote"] = note
		if observation:
			metadata_by_year[end_year][area_id] = observation

	if len(source_names) != 1:
		raise RuntimeError(f"FAOSTAT item name changed or is ambiguous for {source_code}: {sorted(source_names)}")
	if len(areas_with_any_value) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"FAOSTAT indicator {indicator_id} maps only {len(areas_with_any_value)} areas; "
			f"expected at least {indicator['minAreasWithAnyValue']}."
		)
	if not values_by_year:
		raise RuntimeError(f"FAOSTAT returned no mapped values for {indicator_id}.")

	available_years = sorted(values_by_year)
	if available_years[-1] < int(config["minimumLatestPeriodEndYear"]):
		raise RuntimeError(
			f"FAOSTAT indicator {indicator_id} is unexpectedly old: latest endpoint {available_years[-1]}."
		)
	default_year = choose_default_year(indicator, available_years, values_by_year)
	for area_id in indicator["requiredAreas"]:
		if area_id not in values_by_year[default_year]:
			raise RuntimeError(
				f"Required area {area_id} has no FAOSTAT value for {indicator_id} "
				f"in default period {period_labels[default_year]}."
			)

	sorted_values = {
		str(year): {
			area_id: values_by_year[year][area_id]
			for area_id in sorted(values_by_year[year])
		}
		for year in available_years
	}
	sorted_metadata = {
		str(year): {
			area_id: metadata_by_year[year][area_id]
			for area_id in sorted(metadata_by_year[year])
		}
		for year in sorted(metadata_by_year)
		if metadata_by_year[year]
	}
	sorted_period_labels = {
		str(year): period_labels[year]
		for year in sorted(period_labels)
		if year in values_by_year
	}

	provider = config["provider"]
	indicator_metadata: dict[str, Any] = {
		"id": indicator_id,
		"title": indicator["title"],
		"description": indicator["description"],
		"areaLevel": "country",
		"frequency": "three-year-average",
		"unit": indicator["unit"],
	}
	if isinstance(indicator.get("classification"), dict):
		indicator_metadata["classification"] = indicator["classification"]

	payload: dict[str, Any] = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": indicator_metadata,
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"indicator": source_code,
			"sourceIndicatorName": next(iter(source_names)),
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": source_url,
			"documentationUrl": config["documentationUrl"],
			"termsUrl": config["termsUrl"],
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"periodLabels": sorted_period_labels,
		"coverage": {
			"registryAreas": len(area_by_m49),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": available_years[-1],
			"latestPeriod": period_labels[available_years[-1]],
			"areasInLatestYear": len(values_by_year[available_years[-1]]),
			"defaultPeriod": period_labels[default_year],
			"areasInDefaultYear": len(values_by_year[default_year]),
		},
		"values": sorted_values,
	}
	if sorted_metadata:
		payload["observationMetadata"] = sorted_metadata

	diagnostics = {
		"sourceRows": len(source_rows),
		"mappedAreas": len(areas_with_any_value),
		"firstPeriod": period_labels[available_years[0]],
		"latestPeriod": period_labels[available_years[-1]],
		"defaultPeriod": period_labels[default_year],
		"defaultCoverage": len(values_by_year[default_year]),
		"latestCoverage": len(values_by_year[available_years[-1]]),
		"censoredValues": censored_count,
		"missingMappedRows": missing_count,
		"ignoredSourceAreas": dict(sorted(ignored_source_areas.items())),
		"sourceUnits": sorted(source_units),
	}
	print(
		f"{indicator_id}: mapped={len(areas_with_any_value)} "
		f"periods={period_labels[available_years[0]]}..{period_labels[available_years[-1]]} "
		f"default={period_labels[default_year]} defaultCoverage={len(values_by_year[default_year])} "
		f"censored={censored_count} missingMappedRows={missing_count}"
	)
	return payload, diagnostics


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

	area_by_m49, registry_payload, registry_country_count = load_registry_by_m49(args.registry, args.timeout)
	source_url = str(config["bulkUrl"])
	data, headers = fetch_bytes(source_url, args.timeout)

	with zipfile.ZipFile(io.BytesIO(data)) as archive:
		rows, fields, encoding = read_csv_from_archive(archive, EXPECTED_DATA_FILE)
		flag_rows, flag_fields, _flag_encoding = read_csv_from_archive(archive, EXPECTED_FLAG_FILE)
		if EXPECTED_AREA_FILE not in archive.namelist():
			raise RuntimeError(f"FAOSTAT ZIP is missing {EXPECTED_AREA_FILE}.")

	missing_fields = sorted(REQUIRED_FIELDS - set(fields))
	if missing_fields:
		raise RuntimeError(f"FAOSTAT CSV schema changed: missing fields {missing_fields}.")
	if len(rows) < 250000:
		raise RuntimeError(f"FAOSTAT food-security CSV unexpectedly small: {len(rows)} rows.")

	print(
		f"FAOSTAT source: url={source_url} bytes={len(data)} rows={len(rows)} "
		f"columns={len(fields)} encoding={encoding} registryCountries={registry_country_count} "
		f"registryM49={len(area_by_m49)}"
	)

	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload, diagnostics = build_indicator_payload(
			config,
			indicator,
			rows,
			area_by_m49,
			source_url,
		)
		indicator_payloads.append((indicator, payload, diagnostics))

	hasher = hashlib.sha256()
	for indicator, payload, _diagnostics in sorted(indicator_payloads, key=lambda item: item[0]["id"]):
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	output_dir = args.output_dir
	provider_dir = output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []
	diagnostic_indicators: dict[str, Any] = {}

	for indicator, payload, diagnostics in indicator_payloads:
		filename = f"{indicator['slug']}.json"
		write_json(release_dir / filename, payload)
		item: dict[str, Any] = {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "three-year-average",
			"unit": indicator["unit"],
			"sourceIndicator": indicator["sourceItemCode"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"periodLabels": payload["periodLabels"],
			"coverage": payload["coverage"],
		}
		if isinstance(indicator.get("classification"), dict):
			item["classification"] = indicator["classification"]
		index_indicators.append(item)
		diagnostic_indicators[str(indicator["id"])] = diagnostics

	registry_source: dict[str, Any] = {
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": registry_country_count,
		"m49AreaCount": len(area_by_m49),
	}
	if args.registry.startswith(("https://", "http://")):
		registry_source["url"] = args.registry

	dataset: dict[str, Any] = {
		"documentationUrl": config["documentationUrl"],
		"sourceUrl": source_url,
		"termsUrl": config["termsUrl"],
		"encoding": encoding,
		"bytes": len(data),
		"periodType": "three-year-average",
		"flagDescriptions": flag_descriptions(flag_rows, flag_fields),
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
	write_json(
		provider_dir / "diagnostics.json",
		{
			"schema": "kartensammlung.faostat-build-diagnostics/v1",
			"snapshot": snapshot,
			"registryCountryAreas": registry_country_count,
			"registryM49Areas": len(area_by_m49),
			"indicators": diagnostic_indicators,
		},
	)

	print(f"Built FAOSTAT snapshot {snapshot}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
