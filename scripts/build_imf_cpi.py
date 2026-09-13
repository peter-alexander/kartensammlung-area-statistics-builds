#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "imf-cpi-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build annual country inflation statistics directly from the IMF CPI SDMX API."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.imf-cpi-statistics/v1":
		raise ValueError("Invalid IMF CPI statistics config.")
	for key in ("sourceUrl", "apiUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"IMF CPI {key} must use HTTPS.")
	for key in ("dataflow", "indexType", "coicop", "transformation", "frequency"):
		if not str(payload.get(key, "")).strip():
			raise ValueError(f"IMF CPI config is missing {key}.")
	if payload.get("dataflow") != "IMF.STA:CPI":
		raise ValueError("Unexpected IMF CPI dataflow.")
	if payload.get("indexType") != "CPI" or payload.get("coicop") != "_T":
		raise ValueError("IMF CPI config must use the all-items headline CPI series.")
	if payload.get("transformation") != "YOY_PCH_PA_PT" or payload.get("frequency") != "A":
		raise ValueError("IMF CPI config must use the direct annual year-on-year percentage-change series.")
	min_year = payload.get("minYear")
	if not isinstance(min_year, int) or min_year != 1960:
		raise ValueError("IMF CPI minYear must remain 1960 for compatibility with the migrated WDI series.")

	aliases = payload.get("countryAliases")
	if aliases != {"KOS": "XKX", "WBG": "PSE"}:
		raise ValueError("IMF CPI countryAliases changed unexpectedly.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "imf-cpi":
		raise ValueError("IMF CPI provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"IMF CPI provider metadata is missing {key}.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 1:
		raise ValueError("IMF CPI config requires exactly one indicator.")
	indicator = indicators[0]
	if not isinstance(indicator, dict):
		raise ValueError("IMF CPI indicator must be an object.")
	for key in ("id", "slug", "sourceIndicator", "title", "description"):
		if not str(indicator.get(key, "")).strip():
			raise ValueError(f"IMF CPI indicator is missing {key}.")
	if indicator["id"] != "inflation.cpi-annual-percent":
		raise ValueError("IMF CPI must preserve the existing inflation indicator ID.")
	if indicator["sourceIndicator"] != "CPI._T.YOY_PCH_PA_PT.A":
		raise ValueError("Unexpected IMF CPI source indicator.")
	unit = indicator.get("unit")
	if not isinstance(unit, dict) or unit.get("id") != "percent":
		raise ValueError("IMF CPI target unit must remain percent.")
	common.validate_classification(str(indicator["id"]), indicator.get("classification"))
	for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
		value = indicator.get(key)
		if not isinstance(value, int) or value <= 0:
			raise ValueError(f"IMF CPI indicator has invalid {key}.")
	required_areas = indicator.get("requiredAreas")
	if not isinstance(required_areas, list) or not required_areas:
		raise ValueError("IMF CPI indicator requires requiredAreas.")
	return payload


def fetch_bytes(url: str, timeout: int) -> bytes:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 3, 10, 20, 40), start=1):
		if delay:
			time.sleep(delay)
		try:
			request = Request(
				url,
				headers={
					"User-Agent": USER_AGENT,
					"Accept": "text/csv, */*",
				},
			)
			with urlopen(request, timeout=timeout) as response:
				data = response.read()
			if not data:
				raise RuntimeError(f"Empty response from {url}")
			return data
		except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
			last_error = error
			print(f"IMF CPI request failed ({attempt}/5): {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"IMF CPI request failed without exception: {url}")
	raise RuntimeError(f"IMF CPI request failed after 5 attempts: {url}") from last_error


def load_direct_values(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	timeout: int,
) -> tuple[
	dict[int, dict[str, int | float]],
	set[str],
	set[str],
	set[str],
	int,
	int,
	int,
	int,
]:
	raw = fetch_bytes(str(config["apiUrl"]), timeout)
	reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
	fields = set(reader.fieldnames or [])
	required_fields = {
		"STRUCTURE_ID",
		"COUNTRY",
		"INDEX_TYPE",
		"COICOP_1999",
		"TYPE_OF_TRANSFORMATION",
		"FREQUENCY",
		"TIME_PERIOD",
		"OBS_VALUE",
		"IFS_FLAG",
	}
	missing = sorted(required_fields - fields)
	if missing:
		raise RuntimeError("IMF CPI response is missing columns: " + ", ".join(missing))

	aliases = {
		str(source).strip().upper(): str(target).strip().upper()
		for source, target in config["countryAliases"].items()
	}
	min_year = int(config["minYear"])
	current_year = datetime.now(timezone.utc).year
	values: dict[int, dict[str, int | float]] = defaultdict(dict)
	ignored_codes: set[str] = set()
	used_aliases: set[str] = set()
	structure_ids: set[str] = set()
	source_years: set[int] = set()
	source_rows = 0
	retained_rows = 0
	pre_min_year_rows = 0
	future_rows = 0

	for row in reader:
		raw_iso3 = str(row.get("COUNTRY") or "").strip().upper()
		year_text = str(row.get("TIME_PERIOD") or "").strip()
		value_text = str(row.get("OBS_VALUE") or "").strip()
		if not raw_iso3 or not year_text or not value_text:
			continue
		if str(row.get("INDEX_TYPE") or "").strip() != str(config["indexType"]):
			raise RuntimeError(f"Unexpected IMF CPI INDEX_TYPE: {row.get('INDEX_TYPE')!r}")
		if str(row.get("COICOP_1999") or "").strip() != str(config["coicop"]):
			raise RuntimeError(f"Unexpected IMF CPI COICOP_1999: {row.get('COICOP_1999')!r}")
		if str(row.get("TYPE_OF_TRANSFORMATION") or "").strip() != str(config["transformation"]):
			raise RuntimeError(
				f"Unexpected IMF CPI TYPE_OF_TRANSFORMATION: {row.get('TYPE_OF_TRANSFORMATION')!r}"
			)
		if str(row.get("FREQUENCY") or "").strip() != str(config["frequency"]):
			raise RuntimeError(f"Unexpected IMF CPI FREQUENCY: {row.get('FREQUENCY')!r}")
		if str(row.get("IFS_FLAG") or "").strip().lower() != "true":
			raise RuntimeError(f"IMF CPI row is not marked as an IFS series: {raw_iso3} {year_text}")

		structure_id = str(row.get("STRUCTURE_ID") or "").strip()
		if not structure_id.startswith(str(config["dataflow"]) + "("):
			raise RuntimeError(f"Unexpected IMF CPI structure ID: {structure_id!r}")
		structure_ids.add(structure_id)
		source_rows += 1

		try:
			year = int(year_text)
			value = float(value_text)
		except ValueError as error:
			raise RuntimeError(f"Invalid IMF CPI value/year: {raw_iso3} {year_text} {value_text!r}") from error
		if not math.isfinite(value):
			raise RuntimeError(f"Non-finite IMF CPI value: {raw_iso3} {year} {value_text!r}")
		source_years.add(year)
		if year < min_year:
			pre_min_year_rows += 1
			continue
		if year > current_year:
			future_rows += 1
			continue

		iso3 = aliases.get(raw_iso3, raw_iso3)
		if iso3 != raw_iso3:
			used_aliases.add(f"{raw_iso3}->{iso3}")
		if iso3 not in area_by_iso3:
			ignored_codes.add(raw_iso3)
			continue
		area_id = area_by_iso3[iso3]
		if area_id in values[year]:
			raise RuntimeError(f"Duplicate IMF CPI value for {year} {area_id}.")
		values[year][area_id] = common.normalize_number(value_text)
		retained_rows += 1

	if not source_years or not values:
		raise RuntimeError("IMF CPI API returned no usable annual observations.")
	if len(structure_ids) != 1:
		raise RuntimeError(f"Unexpected IMF CPI structure IDs: {sorted(structure_ids)}")
	return (
		values,
		ignored_codes,
		used_aliases,
		structure_ids,
		min(source_years),
		max(source_years),
		source_rows,
		retained_rows,
	)


def choose_default_year(
	indicator: dict[str, Any],
	available_years: list[int],
	values: dict[int, dict[str, int | float]],
) -> int:
	minimum = int(indicator["minAreasInDefaultYear"])
	eligible = [year for year in available_years if len(values[year]) >= minimum]
	if not eligible:
		raise RuntimeError(
			f"IMF CPI has no sufficiently complete default year: expected at least {minimum} areas."
		)
	return eligible[-1]


def build_payload(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	values: dict[int, dict[str, int | float]],
	structure_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
	indicator = config["indicators"][0]
	provider = config["provider"]
	available_years = sorted(year for year, mapped in values.items() if mapped)
	mapped_areas = {area_id for mapped in values.values() for area_id in mapped}
	if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"IMF CPI coverage too small: {len(mapped_areas)} areas, "
			f"expected at least {indicator['minAreasWithAnyValue']}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in mapped_areas:
			raise RuntimeError(f"IMF CPI is missing required area {area_id}.")

	default_year = choose_default_year(indicator, available_years, values)
	latest_year = available_years[-1]
	indicator_metadata = {
		"id": indicator["id"],
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
		"dataset": provider["dataset"],
		"license": provider["license"],
		"licenseUrl": provider["licenseUrl"],
		"attribution": provider["attribution"],
		"url": config["sourceUrl"],
		"apiUrl": config["apiUrl"],
		"dataflow": config["dataflow"],
		"structureId": structure_id,
		"indicator": indicator["sourceIndicator"],
		"indexType": config["indexType"],
		"coicop": config["coicop"],
		"transformation": config["transformation"],
		"sourceFrequency": config["frequency"],
		"sourceUnit": "percent",
		"targetUnit": indicator["unit"]["label"],
		"normalization": {
			"valueMultiplier": 1,
			"note": "Direct IMF annual percentage-change values; no rate is derived from the CPI index.",
		},
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
			"areasInLatestYear": len(values[latest_year]),
			"areasInDefaultYear": len(values[default_year]),
		},
		"values": {
			str(year): {
				area_id: values[year][area_id]
				for area_id in sorted(values[year])
			}
			for year in available_years
		},
	}
	print(
		f"{indicator['id']}: mapped={len(mapped_areas)} years={available_years[0]}-{latest_year} "
		f"latestCoverage={len(values[latest_year])} defaultYear={default_year} "
		f"defaultCoverage={len(values[default_year])}"
	)
	return indicator, payload


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("IMF CPI is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	print(f"Fetching IMF CPI data from {config['apiUrl']}")
	(
		values,
		ignored_codes,
		used_aliases,
		structure_ids,
		source_start_year,
		source_latest_year,
		source_rows,
		retained_rows,
	) = load_direct_values(config, area_by_iso3, args.timeout)
	structure_id = next(iter(structure_ids))
	indicator, payload = build_payload(config, area_by_iso3, values, structure_id)

	hasher = hashlib.sha256()
	hasher.update(str(indicator["id"]).encode("utf-8"))
	hasher.update(b"\0")
	hasher.update(common.canonical_bytes(payload))
	hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	now = datetime.now(timezone.utc)
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	filename = f"{indicator['slug']}.json"
	common.write_json(release_dir / filename, payload)

	index_indicator = {
		"id": indicator["id"],
		"title": indicator["title"],
		"description": indicator["description"],
		"areaLevel": "country",
		"frequency": "annual",
		"unit": indicator["unit"],
		"classification": indicator["classification"],
		"sourceIndicator": indicator["sourceIndicator"],
		"path": f"releases/{snapshot}/{filename}",
		"availableYears": payload["availableYears"],
		"defaultYear": payload["defaultYear"],
		"coverage": payload["coverage"],
	}

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
			"apiUrl": config["apiUrl"],
			"dataflow": config["dataflow"],
			"structureId": structure_id,
			"sourceStartYear": source_start_year,
			"sourceLatestYear": source_latest_year,
			"retainedStartYear": int(config["minYear"]),
			"sourceRows": source_rows,
			"retainedRows": retained_rows,
			"countryAliases": config["countryAliases"],
		},
		"indicators": [index_indicator],
		"notes": [
			"Direct annual all-items consumer-price inflation from the IMF Consumer Price Index (CPI) SDMX dataflow.",
			"The source series uses TYPE_OF_TRANSFORMATION=YOY_PCH_PA_PT and FREQUENCY=A; values are used directly and are not derived from the CPI index.",
			"IMF country codes KOS and WBG are mapped to the statistics-registry ISO3 codes XKX and PSE.",
			"Observations before 1960 are deliberately excluded to preserve the time range of the migrated WDI indicator.",
			"No World Bank WDI fallback is mixed into this provider.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"IMF CPI structure: {structure_id}")
	print(f"IMF CPI source years: {source_start_year}-{source_latest_year}")
	print(f"Used IMF country aliases: {sorted(used_aliases) or '(none)'}")
	print(f"Ignored IMF country codes: {sorted(ignored_codes) or '(none)'}")
	print(f"Built IMF CPI snapshot {snapshot}")
	print("Indicators: 1")


if __name__ == "__main__":
	main()
