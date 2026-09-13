#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_CONFIG = ROOT / "config" / "iea-sdg7-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build renewable-energy share statistics directly from the IEA SDG 7.2 indicator API."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.iea-sdg7-statistics/v1":
		raise ValueError("Invalid IEA SDG7 statistics config.")
	for key in ("sourceUrl", "apiUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"IEA SDG7 {key} must use HTTPS.")
	if payload.get("sourceIndicator") != "SDG72":
		raise ValueError("IEA SDG7 sourceIndicator must remain SDG72.")
	if payload.get("expectedFlow") != "MRENEW":
		raise ValueError("IEA SDG7 expectedFlow must remain MRENEW.")
	if payload.get("expectedFlowLabel") != "Share of renewables":
		raise ValueError("Unexpected IEA SDG7 flow label.")
	if payload.get("expectedUnit") != "%":
		raise ValueError("IEA SDG7 expectedUnit must remain percent.")
	if payload.get("minYear") != 1990:
		raise ValueError("IEA SDG7 minYear must remain 1990.")
	minimum_latest = payload.get("minimumSourceLatestYear")
	if not isinstance(minimum_latest, int) or minimum_latest < 2022:
		raise ValueError("IEA SDG7 minimumSourceLatestYear must be at least 2022.")

	aliases = payload.get("countryAliases")
	if not isinstance(aliases, dict) or len(aliases) < 70:
		raise ValueError("IEA SDG7 countryAliases are incomplete.")
	for source, target in aliases.items():
		if not str(source).strip() or len(str(target).strip()) != 3:
			raise ValueError(f"Invalid IEA SDG7 country alias: {source!r} -> {target!r}")

	allowed_ignored = payload.get("allowedIgnoredCodes")
	if not isinstance(allowed_ignored, list) or "WORLD" not in allowed_ignored or "EU27_2020" not in allowed_ignored:
		raise ValueError("IEA SDG7 allowedIgnoredCodes are incomplete.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "iea-sdg7":
		raise ValueError("IEA SDG7 provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"IEA SDG7 provider metadata is missing {key}.")
	if provider.get("license") != "CC BY 4.0":
		raise ValueError("IEA SDG7 provider licence must remain CC BY 4.0.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 1:
		raise ValueError("IEA SDG7 config requires exactly one indicator.")
	indicator = indicators[0]
	if not isinstance(indicator, dict):
		raise ValueError("IEA SDG7 indicator must be an object.")
	for key in ("id", "slug", "sourceIndicator", "title", "description"):
		if not str(indicator.get(key, "")).strip():
			raise ValueError(f"IEA SDG7 indicator is missing {key}.")
	if indicator["id"] != "energy.renewable-final-consumption-percent":
		raise ValueError("IEA SDG7 must preserve the existing renewable-energy indicator ID.")
	if indicator["sourceIndicator"] != "SDG72":
		raise ValueError("IEA SDG7 indicator must use SDG72, not SDG72modern.")
	unit = indicator.get("unit")
	if not isinstance(unit, dict) or unit.get("id") != "percent":
		raise ValueError("IEA SDG7 target unit must remain percent.")
	common.validate_classification(str(indicator["id"]), indicator.get("classification"))
	for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
		value = indicator.get(key)
		if not isinstance(value, int) or value <= 0:
			raise ValueError(f"IEA SDG7 indicator has invalid {key}.")
	required_areas = indicator.get("requiredAreas")
	if not isinstance(required_areas, list) or not required_areas:
		raise ValueError("IEA SDG7 indicator requires requiredAreas.")
	return payload


def fetch_json(url: str, timeout: int) -> Any:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 3, 10, 20, 40), start=1):
		if delay:
			time.sleep(delay)
		try:
			request = Request(
				url,
				headers={
					"User-Agent": USER_AGENT,
					"Accept": "application/json, */*",
				},
			)
			with urlopen(request, timeout=timeout) as response:
				data = response.read()
			if not data:
				raise RuntimeError(f"Empty response from {url}")
			return json.loads(data.decode("utf-8"))
		except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, json.JSONDecodeError) as error:
			last_error = error
			print(f"IEA SDG7 request failed ({attempt}/5): {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"IEA SDG7 request failed without exception: {url}")
	raise RuntimeError(f"IEA SDG7 request failed after 5 attempts: {url}") from last_error


def load_direct_values(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	timeout: int,
) -> tuple[
	dict[int, dict[str, int | float]],
	set[str],
	set[str],
	int,
	int,
	int,
	int,
]:
	payload = fetch_json(str(config["apiUrl"]), timeout)
	if not isinstance(payload, list) or not payload:
		raise RuntimeError("IEA SDG7 API returned no rows.")

	aliases = {
		str(source).strip().upper(): str(target).strip().upper()
		for source, target in config["countryAliases"].items()
	}
	allowed_ignored = {str(code).strip().upper() for code in config["allowedIgnoredCodes"]}
	min_year = int(config["minYear"])
	current_year = datetime.now(timezone.utc).year
	values: dict[int, dict[str, int | float]] = defaultdict(dict)
	ignored_codes: set[str] = set()
	used_aliases: set[str] = set()
	source_years: set[int] = set()
	source_rows = 0
	retained_rows = 0

	for row in payload:
		if not isinstance(row, dict):
			raise RuntimeError("IEA SDG7 API returned a non-object row.")
		country_code = str(row.get("country") or "").strip().upper()
		year_text = str(row.get("year") or "").strip()
		value_raw = row.get("value")
		if not country_code or not year_text or value_raw is None:
			continue
		if str(row.get("flow") or "").strip() != str(config["expectedFlow"]):
			raise RuntimeError(f"Unexpected IEA SDG7 flow: {row.get('flow')!r}")
		if str(row.get("flowLabel") or "").strip() != str(config["expectedFlowLabel"]):
			raise RuntimeError(f"Unexpected IEA SDG7 flowLabel: {row.get('flowLabel')!r}")
		if str(row.get("seriesLabel") or "").strip() != str(config["expectedFlowLabel"]):
			raise RuntimeError(f"Unexpected IEA SDG7 seriesLabel: {row.get('seriesLabel')!r}")
		if str(row.get("units") or "").strip() != str(config["expectedUnit"]):
			raise RuntimeError(f"Unexpected IEA SDG7 unit: {row.get('units')!r}")
		try:
			year = int(year_text)
			value = float(value_raw)
		except (TypeError, ValueError) as error:
			raise RuntimeError(f"Invalid IEA SDG7 value/year: {country_code} {year_text} {value_raw!r}") from error
		if not math.isfinite(value) or value < 0 or value > 100:
			raise RuntimeError(f"Invalid IEA SDG7 percentage: {country_code} {year} {value_raw!r}")
		source_rows += 1
		source_years.add(year)
		if year < min_year or year > current_year:
			continue

		if country_code in area_by_iso3:
			iso3 = country_code
		else:
			iso3 = aliases.get(country_code, "")
			if iso3:
				used_aliases.add(f"{country_code}->{iso3}")

		if not iso3 or iso3 not in area_by_iso3:
			ignored_codes.add(country_code)
			if country_code not in allowed_ignored:
				raise RuntimeError(f"Unexpected unmapped IEA SDG7 geography code: {country_code}")
			continue

		area_id = area_by_iso3[iso3]
		if area_id in values[year]:
			raise RuntimeError(f"Duplicate IEA SDG7 value for {year} {area_id}.")
		values[year][area_id] = common.normalize_number(str(value_raw))
		retained_rows += 1

	if not source_years or not values:
		raise RuntimeError("IEA SDG7 API returned no usable country observations.")
	source_start_year = min(source_years)
	source_latest_year = max(source_years)
	if source_start_year > min_year:
		raise RuntimeError(f"IEA SDG7 source no longer reaches {min_year}: starts at {source_start_year}.")
	if source_latest_year < int(config["minimumSourceLatestYear"]):
		raise RuntimeError(
			f"IEA SDG7 source latest year regressed to {source_latest_year}; "
			f"expected at least {config['minimumSourceLatestYear']}."
		)
	return (
		values,
		ignored_codes,
		used_aliases,
		source_start_year,
		source_latest_year,
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
			f"IEA SDG7 has no sufficiently complete default year: expected at least {minimum} areas."
		)
	return eligible[-1]


def build_payload(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	values: dict[int, dict[str, int | float]],
) -> tuple[dict[str, Any], dict[str, Any]]:
	indicator = config["indicators"][0]
	provider = config["provider"]
	available_years = sorted(year for year, mapped in values.items() if mapped)
	mapped_areas = {area_id for mapped in values.values() for area_id in mapped}
	if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"IEA SDG7 coverage too small: {len(mapped_areas)} areas, "
			f"expected at least {indicator['minAreasWithAnyValue']}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in mapped_areas:
			raise RuntimeError(f"IEA SDG7 is missing required area {area_id}.")

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
		"indicator": config["sourceIndicator"],
		"flow": config["expectedFlow"],
		"flowLabel": config["expectedFlowLabel"],
		"sourceUnit": config["expectedUnit"],
		"targetUnit": indicator["unit"]["label"],
		"normalization": {
			"valueMultiplier": 1,
			"note": "Direct IEA SDG 7.2 percentage values; no conversion or WDI fallback is applied.",
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
		raise RuntimeError("IEA SDG7 is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	print(f"Fetching IEA SDG7 data from {config['apiUrl']}")
	(
		values,
		ignored_codes,
		used_aliases,
		source_start_year,
		source_latest_year,
		source_rows,
		retained_rows,
	) = load_direct_values(config, area_by_iso3, args.timeout)
	indicator, payload = build_payload(config, area_by_iso3, values)

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
			"sourceIndicator": config["sourceIndicator"],
			"flow": config["expectedFlow"],
			"flowLabel": config["expectedFlowLabel"],
			"unit": config["expectedUnit"],
			"sourceStartYear": source_start_year,
			"sourceLatestYear": source_latest_year,
			"retainedStartYear": int(config["minYear"]),
			"sourceRows": source_rows,
			"retainedRows": retained_rows,
			"countryAliases": config["countryAliases"],
			"ignoredCodes": sorted(ignored_codes),
		},
		"indicators": [index_indicator],
		"notes": [
			"Direct IEA SDG 7.2 series for the renewable share of total final energy consumption.",
			"The source indicator is SDG72 / MRENEW. It is not SDG72modern, which excludes traditional bioenergy and is a different statistic.",
			"The IEA API mixes ISO3 codes with legacy IEA/UNSD geography codes; audited aliases are mapped explicitly to the country registry.",
			"The latest source year can be partial. The default year is the latest year meeting the configured minimum country coverage.",
			"No World Bank WDI fallback is mixed into this provider.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"IEA SDG7 source years: {source_start_year}-{source_latest_year}")
	print(f"Used IEA geography aliases: {len(used_aliases)}")
	print(f"Ignored IEA geography codes: {sorted(ignored_codes) or '(none)'}")
	print(f"Built IEA SDG7 snapshot {snapshot}")
	print("Indicators: 1")


if __name__ == "__main__":
	main()
