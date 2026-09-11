#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import math
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.feather as feather

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "world-bank-pip-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build annual country poverty statistics from the World Bank Poverty and Inequality Platform (PIP)."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=180)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.world-bank-pip-statistics/v1":
		raise ValueError("Invalid World Bank PIP statistics config.")

	api_base = str(payload.get("apiBase", "")).strip().rstrip("/")
	source_page = str(payload.get("sourcePage", "")).strip()
	provider = payload.get("provider")
	ppp_version = payload.get("pppVersion")
	minimum_release = payload.get("minimumReleaseDate")
	poverty_lines = payload.get("povertyLines")
	indicators = payload.get("indicators")
	aliases = payload.get("iso3Aliases", {})

	if not api_base.startswith("https://"):
		raise ValueError("World Bank PIP apiBase must use HTTPS.")
	if not source_page.startswith("https://"):
		raise ValueError("World Bank PIP sourcePage must use HTTPS.")
	if not isinstance(provider, dict) or provider.get("id") != "world-bank-pip":
		raise ValueError("World Bank PIP provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"World Bank PIP provider metadata is missing {key}.")
	if ppp_version != 2021:
		raise ValueError("World Bank PIP builder currently requires 2021 PPP.")
	if not isinstance(minimum_release, int) or minimum_release < 20250101:
		raise ValueError("World Bank PIP minimumReleaseDate is invalid.")
	if not isinstance(poverty_lines, list) or sorted(float(value) for value in poverty_lines) != [3.0, 4.2, 8.3]:
		raise ValueError("World Bank PIP povertyLines must be [3.0, 4.2, 8.3].")
	if not isinstance(aliases, dict):
		raise ValueError("World Bank PIP iso3Aliases must be an object.")
	for source, target in aliases.items():
		if len(str(source)) != 3 or len(str(target)) != 3:
			raise ValueError(f"Invalid World Bank PIP ISO3 alias: {source} -> {target}")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("World Bank PIP config requires indicators.")

	ids: set[str] = set()
	slugs: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("World Bank PIP indicator entries must be objects.")
		for key in ("id", "slug", "title", "description", "povertyLine"):
			if str(indicator.get(key, "")).strip() == "":
				raise ValueError(f"World Bank PIP indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate World Bank PIP indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate World Bank PIP indicator slug: {slug}")
		ids.add(indicator_id)
		slugs.add(slug)

		line = float(indicator["povertyLine"])
		if line not in {3.0, 4.2, 8.3}:
			raise ValueError(f"Unsupported World Bank PIP poverty line for {indicator_id}: {line}")
		field = str(indicator.get("field", "")).strip()
		derive = str(indicator.get("derive", "")).strip()
		if bool(field) == bool(derive):
			raise ValueError(f"World Bank PIP indicator {indicator_id} must define exactly one of field or derive.")
		if derive and derive != "poor-population-millions":
			raise ValueError(f"Unsupported World Bank PIP derivation for {indicator_id}: {derive}")
		if field and field not in {"headcount", "poverty_gap", "mean", "median", "spr", "spl", "pg"}:
			raise ValueError(f"Unsupported World Bank PIP field for {indicator_id}: {field}")
		scale = indicator.get("scale", 1)
		if not isinstance(scale, (int, float)) or not math.isfinite(float(scale)):
			raise ValueError(f"World Bank PIP indicator {indicator_id} has invalid scale.")
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"World Bank PIP indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"World Bank PIP indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or not required_areas:
			raise ValueError(f"World Bank PIP indicator {indicator_id} requires at least one required area.")
	return payload


def fetch_bytes(url: str, timeout: int, accept: str) -> tuple[bytes, str]:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 2, 5, 10), start=1):
		if delay:
			time.sleep(delay)
		request = urllib.request.Request(
			url,
			headers={
				"User-Agent": "kartensammlung-area-statistics-builds/1",
				"Accept": accept,
			},
		)
		try:
			with urllib.request.urlopen(request, timeout=timeout) as response:
				data = response.read()
				content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
				if not data:
					raise RuntimeError(f"Empty response from {url}")
				return data, content_type
		except Exception as exc:
			last_error = exc
			print(f"Request failed ({attempt}/4): {url}: {exc}")
	assert last_error is not None
	raise RuntimeError(f"Request failed after 4 attempts: {url}") from last_error


def fetch_json(url: str, timeout: int) -> Any:
	data, content_type = fetch_bytes(url, timeout, "application/json")
	if content_type != "application/json":
		raise RuntimeError(f"Unexpected JSON content type from {url}: {content_type}")
	return common.json.loads(data.decode("utf-8"))


def select_current_version(config: dict[str, Any], timeout: int) -> dict[str, str]:
	url = f"{str(config['apiBase']).rstrip('/')}/versions?format=json"
	payload = fetch_json(url, timeout)
	if not isinstance(payload, list):
		raise RuntimeError("World Bank PIP versions endpoint returned an unexpected payload.")
	candidates: list[dict[str, str]] = []
	for row in payload:
		if not isinstance(row, dict):
			continue
		version = str(row.get("version", "")).strip()
		release = str(row.get("release_version", "")).strip()
		ppp_version = str(row.get("ppp_version", "")).strip()
		identity = str(row.get("identity", "")).strip().upper()
		if version and release.isdigit() and ppp_version == str(config["pppVersion"]) and identity == "PROD":
			candidates.append({
				"version": version,
				"releaseVersion": release,
				"pppVersion": ppp_version,
				"identity": identity,
			})
	if not candidates:
		raise RuntimeError("No public World Bank PIP PROD version for 2021 PPP was found.")
	selected = max(candidates, key=lambda row: (int(row["releaseVersion"]), row["version"]))
	if int(selected["releaseVersion"]) < int(config["minimumReleaseDate"]):
		raise RuntimeError(
			f"World Bank PIP release is unexpectedly old: {selected['releaseVersion']} "
			f"< {config['minimumReleaseDate']}"
		)
	print(f"World Bank PIP version: {selected['version']}")
	return selected


def poverty_line_text(value: float) -> str:
	if value == 3.0:
		return "3"
	return f"{value:g}"


def pip_url(config: dict[str, Any], version: str, poverty_line: float) -> str:
	params = urllib.parse.urlencode({
		"country": "all",
		"year": "all",
		"ppp_version": str(config["pppVersion"]),
		"fill_gaps": "true",
		"reporting_level": "national",
		"version": version,
		"povline": poverty_line_text(poverty_line),
		"format": "arrow",
	})
	return f"{str(config['apiBase']).rstrip('/')}/pip?{params}"


def read_arrow_rows(data: bytes, source: str) -> list[dict[str, Any]]:
	try:
		table = feather.read_table(pa.BufferReader(data))
	except Exception as exc:
		raise RuntimeError(f"Could not read World Bank PIP Arrow response: {source}") from exc
	required = {
		"country_code",
		"country_name",
		"reporting_year",
		"reporting_level",
		"welfare_type",
		"headcount",
		"poverty_gap",
		"mean",
		"median",
		"reporting_pop",
		"is_interpolated",
		"estimation_type",
		"distribution_type",
		"spl",
		"spr",
		"pg",
		"estimate_type",
	}
	missing = required - set(table.column_names)
	if missing:
		raise RuntimeError(f"World Bank PIP Arrow response is missing columns: {sorted(missing)}")
	rows = table.to_pylist()
	if len(rows) < 5000:
		raise RuntimeError(f"World Bank PIP Arrow response unexpectedly small: {len(rows)} rows")
	return rows


def mapped_iso3(source_code: str, aliases: dict[str, str]) -> str:
	code = source_code.strip().upper()
	return aliases.get(code, code)


def finite_number(value: Any) -> float | None:
	if value is None or value == "":
		return None
	try:
		number = float(value)
	except (TypeError, ValueError):
		return None
	if not math.isfinite(number):
		return None
	return number


def normalize_number(value: float, decimals: int = 8) -> int | float:
	rounded = round(float(value), decimals)
	if abs(rounded - round(rounded)) < 10 ** (-decimals):
		return int(round(rounded))
	return rounded


def collect_rows_by_area_year(
	rows: list[dict[str, Any]],
	area_by_iso3: dict[str, str],
	aliases: dict[str, str],
	current_year: int,
	poverty_line: float,
) -> tuple[dict[tuple[int, str], dict[str, Any]], set[str]]:
	result: dict[tuple[int, str], dict[str, Any]] = {}
	unresolved: set[str] = set()
	for row in rows:
		if str(row.get("reporting_level", "")).strip().lower() != "national":
			continue
		source_code = str(row.get("country_code", "")).strip().upper()
		if not source_code:
			continue
		iso3 = mapped_iso3(source_code, aliases)
		area_id = area_by_iso3.get(iso3)
		if not area_id:
			unresolved.add(source_code)
			continue
		year_value = row.get("reporting_year")
		try:
			year = int(year_value)
		except (TypeError, ValueError):
			continue
		if year < 1900 or year > current_year:
			continue
		line = finite_number(row.get("poverty_line"))
		if line is None or not math.isclose(line, poverty_line, rel_tol=0, abs_tol=1e-9):
			raise RuntimeError(
				f"World Bank PIP poverty line mismatch for {source_code} {year}: {line} != {poverty_line}"
			)
		key = (year, area_id)
		if key in result:
			raise RuntimeError(f"Duplicate World Bank PIP country-year: {source_code} {year} line={poverty_line}")
		result[key] = row
	return result, unresolved


def metadata_for_row(row: dict[str, Any]) -> dict[str, Any]:
	metadata: dict[str, Any] = {}
	for source_key, target_key in (
		("estimate_type", "estimateType"),
		("estimation_type", "estimationType"),
		("welfare_type", "welfareType"),
		("distribution_type", "distributionType"),
	):
		value = str(row.get(source_key, "")).strip()
		if value:
			metadata[target_key] = value
	metadata["isInterpolated"] = bool(row.get("is_interpolated"))
	return metadata


def same_optional_number(left: Any, right: Any) -> bool:
	left_number = finite_number(left)
	right_number = finite_number(right)
	if left_number is None or right_number is None:
		return left_number is None and right_number is None
	return math.isclose(left_number, right_number, rel_tol=1e-9, abs_tol=1e-9)


def validate_cross_line_consistency(
	base: dict[tuple[int, str], dict[str, Any]],
	other: dict[tuple[int, str], dict[str, Any]],
	line: float,
) -> None:
	if set(base) != set(other):
		missing = len(set(base) - set(other))
		extra = len(set(other) - set(base))
		raise RuntimeError(f"World Bank PIP country-year coverage differs for poverty line {line}: missing={missing} extra={extra}")
	for key, base_row in base.items():
		row = other[key]
		for field in ("mean", "median", "reporting_pop", "spl", "spr", "pg"):
			if not same_optional_number(base_row.get(field), row.get(field)):
				raise RuntimeError(f"World Bank PIP field {field} differs across poverty lines for {key}.")
		for field in ("estimate_type", "estimation_type", "welfare_type", "distribution_type", "is_interpolated"):
			if base_row.get(field) != row.get(field):
				raise RuntimeError(f"World Bank PIP metadata {field} differs across poverty lines for {key}.")


def indicator_value(indicator: dict[str, Any], row: dict[str, Any]) -> int | float | None:
	derive = str(indicator.get("derive", "")).strip()
	if derive == "poor-population-millions":
		headcount = finite_number(row.get("headcount"))
		population = finite_number(row.get("reporting_pop"))
		if headcount is None or population is None:
			return None
		if not 0 <= headcount <= 1 or population < 0:
			raise RuntimeError(f"Invalid World Bank PIP poverty/population values: headcount={headcount}, population={population}")
		return normalize_number(headcount * population / 1_000_000)

	field = str(indicator.get("field", "")).strip()
	value = finite_number(row.get(field))
	if value is None:
		return None
	if field in {"headcount", "poverty_gap", "spr"} and not 0 <= value <= 1:
		raise RuntimeError(f"World Bank PIP ratio outside 0..1 for {field}: {value}")
	scale = float(indicator.get("scale", 1))
	return normalize_number(value * scale)


def build_indicator_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	rows_by_line: dict[float, dict[tuple[int, str], dict[str, Any]]],
	metadata_by_key: dict[tuple[int, str], dict[str, Any]],
	area_by_iso3: dict[str, str],
	version_info: dict[str, str],
) -> dict[str, Any]:
	line = float(indicator["povertyLine"])
	rows = rows_by_line[line]
	values_by_year: dict[int, dict[str, int | float]] = defaultdict(dict)
	metadata_by_year: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
	areas_with_any_value: set[str] = set()

	for (year, area_id), row in rows.items():
		value = indicator_value(indicator, row)
		if value is None:
			continue
		values_by_year[year][area_id] = value
		metadata_by_year[year][area_id] = metadata_by_key[(year, area_id)]
		areas_with_any_value.add(area_id)

	if len(areas_with_any_value) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"World Bank PIP indicator {indicator['id']} maps only {len(areas_with_any_value)} areas; "
			f"expected at least {indicator['minAreasWithAnyValue']}."
		)
	available_years = sorted(year for year, values in values_by_year.items() if values)
	if not available_years:
		raise RuntimeError(f"World Bank PIP indicator {indicator['id']} has no values.")

	required_areas = [str(area_id) for area_id in indicator["requiredAreas"]]
	missing_required_any = [area_id for area_id in required_areas if area_id not in areas_with_any_value]
	if missing_required_any:
		raise RuntimeError(f"World Bank PIP indicator {indicator['id']} is missing required areas: {missing_required_any}")

	min_default = int(indicator["minAreasInDefaultYear"])
	default_year = None
	for year in reversed(available_years):
		values = values_by_year[year]
		if len(values) >= min_default and all(area_id in values for area_id in required_areas):
			default_year = year
			break
	if default_year is None:
		raise RuntimeError(
			f"World Bank PIP indicator {indicator['id']} has no year with at least {min_default} areas "
			"and all required areas."
		)

	sorted_values = {
		str(year): {area_id: values_by_year[year][area_id] for area_id in sorted(values_by_year[year])}
		for year in available_years
	}
	sorted_metadata = {
		str(year): {area_id: metadata_by_year[year][area_id] for area_id in sorted(metadata_by_year[year])}
		for year in available_years
	}
	latest_year = available_years[-1]
	provider = config["provider"]
	source = {
		"providerId": provider["id"],
		"providerName": provider["name"],
		"dataset": provider["dataset"],
		"version": version_info["version"],
		"releaseVersion": version_info["releaseVersion"],
		"pppVersion": config["pppVersion"],
		"queryPovertyLine": line,
		"fillGaps": True,
		"reportingLevel": "national",
		"license": provider["license"],
		"licenseUrl": provider["licenseUrl"],
		"attribution": provider["attribution"],
		"url": config["sourcePage"],
	}
	payload = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"areaLevel": "country",
		"frequency": "annual",
		"indicator": {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		},
		"source": source,
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(areas_with_any_value),
			"latestYear": latest_year,
			"areasInLatestYear": len(values_by_year[latest_year]),
			"areasInDefaultYear": len(values_by_year[default_year]),
		},
		"values": sorted_values,
		"observationMetadata": sorted_metadata,
	}
	print(
		f"{indicator['id']}: mapped={len(areas_with_any_value)} "
		f"years={available_years[0]}-{latest_year} "
		f"defaultYear={default_year} defaultCoverage={len(values_by_year[default_year])}"
	)
	return payload


def release_date_iso(release_version: str) -> str:
	try:
		return datetime.strptime(release_version, "%Y%m%d").date().isoformat()
	except ValueError as exc:
		raise RuntimeError(f"Invalid World Bank PIP release version: {release_version}") from exc


def build_dataset_metadata(
	config: dict[str, Any],
	version_info: dict[str, str],
	metadata_by_key: dict[tuple[int, str], dict[str, Any]],
) -> dict[str, Any]:
	status_counts: dict[int, Counter[str]] = defaultdict(Counter)
	for (year, _area_id), metadata in metadata_by_key.items():
		status = str(metadata.get("estimateType", "unknown"))
		status_counts[year][status] += 1

	nowcast_years: list[int] = []
	for year in sorted(status_counts):
		counts = status_counts[year]
		total = sum(counts.values())
		if total and counts.get("nowcast", 0) == total:
			nowcast_years.append(year)

	return {
		"version": version_info["version"],
		"releaseDate": release_date_iso(version_info["releaseVersion"]),
		"pppVersion": config["pppVersion"],
		"povertyLines": config["povertyLines"],
		"annualization": "PIP fill_gaps=true",
		"reportingLevel": "national",
		"observationMetadata": True,
		"nowcastYears": nowcast_years,
		"defaultYearPolicy": "Latest year with broad mapped-country coverage and all required reference countries.",
		"statusCountsByYear": {
			str(year): dict(sorted(counts.items()))
			for year, counts in sorted(status_counts.items())
		},
	}


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError(f"Provider {provider['id']} is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	now = common.utc_now()
	version_info = select_current_version(config, args.timeout)
	aliases = {str(source).upper(): str(target).upper() for source, target in config.get("iso3Aliases", {}).items()}

	rows_by_line: dict[float, dict[tuple[int, str], dict[str, Any]]] = {}
	all_unresolved: set[str] = set()
	for raw_line in config["povertyLines"]:
		line = float(raw_line)
		url = pip_url(config, version_info["version"], line)
		started = time.monotonic()
		data, content_type = fetch_bytes(url, args.timeout, "application/vnd.apache.arrow.file")
		elapsed = time.monotonic() - started
		if content_type != "application/vnd.apache.arrow.file":
			raise RuntimeError(f"Unexpected World Bank PIP Arrow content type: {content_type}")
		rows = read_arrow_rows(data, url)
		mapped, unresolved = collect_rows_by_area_year(rows, area_by_iso3, aliases, now.year, line)
		rows_by_line[line] = mapped
		all_unresolved.update(unresolved)
		print(
			f"PIP line={line:g}: downloaded={len(data)} bytes rows={len(rows)} "
			f"mappedCountryYears={len(mapped)} seconds={elapsed:.2f}"
		)

	base_rows = rows_by_line[3.0]
	for line in (4.2, 8.3):
		validate_cross_line_consistency(base_rows, rows_by_line[line], line)
	if all_unresolved:
		print(f"Unmapped World Bank PIP source country codes: {sorted(all_unresolved)}")
	if len({area_id for _year, area_id in base_rows}) < 160:
		raise RuntimeError("World Bank PIP mapped country coverage is unexpectedly low.")

	metadata_by_key = {key: metadata_for_row(row) for key, row in base_rows.items()}
	indicator_payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		payload = build_indicator_payload(
			config,
			indicator,
			rows_by_line,
			metadata_by_key,
			area_by_iso3,
			version_info,
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
		index_indicator = {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
			"classification": indicator["classification"],
		}
		index_indicators.append(index_indicator)

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
		"dataset": build_dataset_metadata(config, version_info, metadata_by_key),
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"indicators": index_indicators,
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(output_dir / "index.json", common.build_global_index(provider_catalog))

	print(f"Built World Bank PIP snapshot {snapshot}")
	print(f"Version: {version_info['version']}")
	print(f"Provider index: {provider_dir / 'index.json'}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
