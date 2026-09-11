#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import build_un_wpp as base

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "un-wpp-indicators.json"
DEFAULT_AGE_CONFIG = ROOT / "config" / "un-wpp-age-indicators.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Extend UN WPP country statistics with population age structure.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--age-config", type=Path, default=DEFAULT_AGE_CONFIG)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=90)
	return parser.parse_args()


def validate_age_range(definition: Any, indicator_id: str) -> None:
	if not isinstance(definition, dict):
		raise ValueError(f"Age indicator {indicator_id} has invalid age range.")
	start = definition.get("start")
	end = definition.get("end")
	if not isinstance(start, int) or start < 0:
		raise ValueError(f"Age indicator {indicator_id} has invalid range start.")
	if end is not None and (not isinstance(end, int) or end <= start):
		raise ValueError(f"Age indicator {indicator_id} has invalid range end.")
	if start % 5 != 0 or (end is not None and end % 5 != 0):
		raise ValueError(f"Age indicator {indicator_id} ranges must align to WPP five-year age groups.")


def validate_age_config(payload: Any, main_config: dict[str, Any]) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.un-wpp-age-statistics/v1":
		raise ValueError("Invalid UN WPP age statistics config.")
	if not str(payload.get("downloadUrl", "")).startswith("https://"):
		raise ValueError("UN WPP age downloadUrl must use HTTPS.")
	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or not indicators:
		raise ValueError("UN WPP age config requires indicators.")
	ids = {str(indicator["id"]) for indicator in main_config["indicators"]}
	slugs = {str(indicator["slug"]) for indicator in main_config["indicators"]}
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("UN WPP age indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"UN WPP age indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		if indicator_id in ids or slug in slugs:
			raise ValueError(f"Duplicate UN WPP indicator id or slug: {indicator_id}.")
		ids.add(indicator_id)
		slugs.add(slug)
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not unit.get("id") or not unit.get("label"):
			raise ValueError(f"Indicator {indicator_id} has invalid unit metadata.")
		if not isinstance(indicator.get("minAreasWithAnyValue"), int) or indicator["minAreasWithAnyValue"] <= 0:
			raise ValueError(f"Indicator {indicator_id} has invalid minAreasWithAnyValue.")
		base.validate_classification(indicator)
		calculation = indicator.get("calculation")
		if not isinstance(calculation, dict):
			raise ValueError(f"Age indicator {indicator_id} requires calculation metadata.")
		calculation_type = str(calculation.get("type", ""))
		if calculation_type in ("age-range-count", "age-range-percent"):
			validate_age_range(calculation, indicator_id)
			if str(calculation.get("sex", "total")) not in ("total", "male", "female"):
				raise ValueError(f"Age indicator {indicator_id} has invalid sex.")
		elif calculation_type == "age-range-ratio":
			for key in ("numerator", "denominator"):
				ranges = calculation.get(key)
				if not isinstance(ranges, list) or not ranges:
					raise ValueError(f"Age indicator {indicator_id} requires {key} ranges.")
				for range_definition in ranges:
					validate_age_range(range_definition, indicator_id)
			multiplier = float(calculation.get("multiplier", 100))
			if not math.isfinite(multiplier) or multiplier <= 0:
				raise ValueError(f"Age indicator {indicator_id} has invalid ratio multiplier.")
		else:
			raise ValueError(f"Age indicator {indicator_id} has unsupported calculation type: {calculation_type}.")
	return payload


def parse_float(raw: str) -> float | None:
	text = raw.strip()
	if not text or text in ("..", "..."):
		return None
	value = float(text)
	return value if math.isfinite(value) else None


def apply_transform(value: float, indicator: dict[str, Any]) -> int | float:
	transform = indicator.get("transform") or {}
	value *= float(transform.get("multiplier", 1))
	if "round" in transform:
		value = round(value, int(transform["round"]))
	if value == 0:
		value = 0.0
	return int(value) if value.is_integer() else value


def in_age_range(age_start: int, definition: dict[str, Any]) -> bool:
	start = int(definition["start"])
	end = definition.get("end")
	return age_start >= start and (end is None or age_start < int(end))


def selected_population(row: dict[str, str], sex: str) -> float | None:
	column = {"total": "PopTotal", "male": "PopMale", "female": "PopFemale"}[sex]
	return parse_float(str(row.get(column, "")))


def add_nested(store: dict[str, dict[int, dict[str, float]]], indicator_id: str, year: int, area_id: str, value: float) -> None:
	year_values = store[indicator_id].setdefault(year, {})
	year_values[area_id] = year_values.get(area_id, 0.0) + value


def read_age_values(path: Path, config: dict[str, Any], age_config: dict[str, Any], area_by_iso3: dict[str, str]) -> tuple[dict[str, dict[int, dict[str, int | float]]], set[str]]:
	indicators = age_config["indicators"]
	accumulated = {str(indicator["id"]): {} for indicator in indicators}
	denominators = {
		str(indicator["id"]): {}
		for indicator in indicators
		if indicator["calculation"]["type"] == "age-range-ratio"
	}
	total_population: dict[int, dict[str, float]] = {}
	ignored_codes: set[str] = set()
	required_columns = {"ISO3_code", "LocTypeName", "Variant", "Time", "AgeGrpStart", "PopMale", "PopFemale", "PopTotal"}
	with gzip.open(path, "rb") as compressed, io.TextIOWrapper(compressed, encoding="utf-8-sig", newline="") as text:
		reader = csv.DictReader(text)
		missing = sorted(required_columns - set(reader.fieldnames or []))
		if missing:
			raise RuntimeError(f"UN WPP age CSV is missing required columns: {', '.join(missing)}")
		for row in reader:
			if str(row.get("LocTypeName", "")).strip() not in ("", "Country/Area"):
				continue
			iso3 = str(row.get("ISO3_code", "")).strip().upper()
			if iso3 not in area_by_iso3:
				if iso3:
					ignored_codes.add(iso3)
				continue
			raw_year = str(row.get("Time", "")).strip()
			raw_age = str(row.get("AgeGrpStart", "")).strip()
			if len(raw_year) != 4 or not raw_year.isdigit() or not raw_age.isdigit():
				continue
			year = int(raw_year)
			variant = str(row.get("Variant", "")).strip()
			if year <= int(config["estimateEndYear"]):
				if variant and variant != "Estimates":
					continue
			elif variant and variant != str(config["projectionVariant"]):
				continue
			age_start = int(raw_age)
			area_id = area_by_iso3[iso3]
			pop_total = selected_population(row, "total")
			if pop_total is not None:
				year_totals = total_population.setdefault(year, {})
				year_totals[area_id] = year_totals.get(area_id, 0.0) + pop_total
			for indicator in indicators:
				indicator_id = str(indicator["id"])
				calculation = indicator["calculation"]
				calculation_type = str(calculation["type"])
				if calculation_type in ("age-range-count", "age-range-percent"):
					if not in_age_range(age_start, calculation):
						continue
					population = selected_population(row, str(calculation.get("sex", "total")))
					if population is not None:
						add_nested(accumulated, indicator_id, year, area_id, population)
				elif calculation_type == "age-range-ratio":
					if pop_total is None:
						continue
					if any(in_age_range(age_start, item) for item in calculation["numerator"]):
						add_nested(accumulated, indicator_id, year, area_id, pop_total)
					if any(in_age_range(age_start, item) for item in calculation["denominator"]):
						add_nested(denominators, indicator_id, year, area_id, pop_total)

	values: dict[str, dict[int, dict[str, int | float]]] = {str(indicator["id"]): {} for indicator in indicators}
	for indicator in indicators:
		indicator_id = str(indicator["id"])
		calculation = indicator["calculation"]
		calculation_type = str(calculation["type"])
		for year, year_values in accumulated[indicator_id].items():
			for area_id, numerator in year_values.items():
				if calculation_type == "age-range-count":
					base_value = numerator * float(calculation.get("sourceMultiplier", 1000))
				elif calculation_type == "age-range-percent":
					denominator = total_population.get(year, {}).get(area_id)
					if not denominator or denominator <= 0:
						continue
					base_value = numerator / denominator * 100
				else:
					denominator = denominators[indicator_id].get(year, {}).get(area_id)
					if not denominator or denominator <= 0:
						continue
					base_value = numerator / denominator * float(calculation.get("multiplier", 100))
				values[indicator_id].setdefault(year, {})[area_id] = apply_transform(base_value, indicator)
	return values, ignored_codes


def build_age_payload(config: dict[str, Any], age_config: dict[str, Any], indicator: dict[str, Any], values_by_year: dict[int, dict[str, int | float]], area_count: int) -> dict[str, Any]:
	indicator_id = str(indicator["id"])
	areas = {area_id for year_values in values_by_year.values() for area_id in year_values}
	if len(areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(f"Coverage too small for {indicator_id}: {len(areas)} areas.")
	for area_id in config["requiredAreas"]:
		if area_id not in areas:
			raise RuntimeError(f"Required area {area_id} has no values for {indicator_id}.")
	available_years = sorted(values_by_year)
	if not available_years:
		raise RuntimeError(f"UN WPP returned no mapped values for {indicator_id}.")
	estimate_end_year = int(config["estimateEndYear"])
	broad_threshold = max(1, math.ceil(len(areas) * float(config["broadCoverageFraction"])))
	broad_estimates = [year for year in available_years if year <= estimate_end_year and len(values_by_year[year]) >= broad_threshold]
	if not broad_estimates:
		raise RuntimeError(f"No estimate year reaches broad coverage for {indicator_id}.")
	default_year = broad_estimates[-1]
	if datetime.now(timezone.utc).year - default_year > 5:
		raise RuntimeError(f"Latest broadly covered estimate year for {indicator_id} is unexpectedly old: {default_year}.")
	latest_year = available_years[-1]
	provider = config["provider"]
	return {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": {
			"id": indicator_id,
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"projection": {"startYear": estimate_end_year + 1, "endYear": latest_year, "variant": config["projectionVariant"]},
		},
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"datasetId": f"WPP{config['revision']}",
			"indicator": indicator["sourceIndicator"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": "https://population.un.org/wpp/",
			"downloadUrl": age_config["downloadUrl"],
			"derivedFrom": {"dataset": "WPP2024_PopulationByAge5GroupSex_Medium", "calculation": indicator["calculation"]},
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": area_count,
			"areasWithAnyValue": len(areas),
			"latestYear": latest_year,
			"areasInLatestYear": len(values_by_year[latest_year]),
			"latestEstimateYear": default_year,
			"areasInLatestEstimateYear": len(values_by_year[default_year]),
			"broadCoverageThreshold": broad_threshold,
			"areasInDefaultYear": len(values_by_year[default_year]),
		},
		"values": {str(year): {area_id: values_by_year[year][area_id] for area_id in sorted(values_by_year[year])} for year in available_years},
	}


def main() -> None:
	args = parse_args()
	config = base.validate_config(base.read_json(args.config))
	age_config = validate_age_config(base.read_json(args.age_config), config)
	provider = config["provider"]
	provider_dir = args.output_dir / provider["id"]
	provider_index_path = provider_dir / "index.json"
	if not provider_index_path.is_file():
		raise RuntimeError("UN WPP base provider index does not exist; run build_un_wpp.py first.")
	provider_index = base.read_json(provider_index_path)
	if provider_index.get("schema") != "kartensammlung.statistics-provider-index/v1":
		raise RuntimeError("UN WPP base provider index has an unexpected schema.")
	old_snapshot = str(provider_index["activeSnapshot"])
	old_release_dir = provider_dir / "releases" / old_snapshot
	if not old_release_dir.is_dir():
		raise RuntimeError(f"UN WPP base release is missing: {old_snapshot}")

	area_by_iso3, _ = base.load_registry(args.registry, args.timeout)
	print(f"Downloading {provider['dataset']} population by age and sex")
	path = base.download(str(age_config["downloadUrl"]), args.timeout)
	try:
		print(f"Downloaded population by age and sex: {path.stat().st_size} bytes")
		age_values, age_ignored_codes = read_age_values(path, config, age_config, area_by_iso3)
	finally:
		path.unlink(missing_ok=True)

	payloads: dict[str, dict[str, Any]] = {}
	filenames: dict[str, str] = {}
	for entry in provider_index["indicators"]:
		indicator_id = str(entry["id"])
		filename = Path(str(entry["path"])).name
		payloads[indicator_id] = base.read_json(old_release_dir / filename)
		filenames[indicator_id] = filename

	age_entries: list[dict[str, Any]] = []
	for indicator in age_config["indicators"]:
		indicator_id = str(indicator["id"])
		payload = build_age_payload(config, age_config, indicator, age_values[indicator_id], len(area_by_iso3))
		payloads[indicator_id] = payload
		filenames[indicator_id] = f"{indicator['slug']}.json"
		coverage = payload["coverage"]
		print(f"{indicator_id}: mapped={coverage['areasWithAnyValue']} years={payload['availableYears'][0]}-{payload['availableYears'][-1]} defaultYear={payload['defaultYear']} defaultCoverage={coverage['areasInDefaultYear']}")
		age_entries.append({
			"id": indicator_id,
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"projection": payload["indicator"]["projection"],
			"sourceIndicator": indicator["sourceIndicator"],
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		})

	hasher = hashlib.sha256()
	for indicator_id in sorted(payloads):
		hasher.update(indicator_id.encode("utf-8") + b"\0" + base.canonical_bytes(payloads[indicator_id]) + b"\0")
	new_snapshot = hasher.hexdigest()[:16]
	new_release_dir = provider_dir / "releases" / new_snapshot
	new_release_dir.mkdir(parents=True, exist_ok=True)
	for indicator_id in sorted(payloads):
		base.write_json(new_release_dir / filenames[indicator_id], payloads[indicator_id])

	combined_entries: list[dict[str, Any]] = []
	for entry in provider_index["indicators"]:
		copy = dict(entry)
		copy["path"] = f"releases/{new_snapshot}/{Path(str(entry['path'])).name}"
		combined_entries.append(copy)
	for entry in age_entries:
		copy = dict(entry)
		copy["path"] = f"releases/{new_snapshot}/{filenames[str(entry['id'])]}"
		combined_entries.append(copy)

	provider_index["activeSnapshot"] = new_snapshot
	provider_index["indicators"] = combined_entries
	provider_index["ignoredIso3Codes"] = sorted(set(provider_index.get("ignoredIso3Codes", [])) | age_ignored_codes)
	provider_index["dataset"]["projectionEndYear"] = max(entry["availableYears"][-1] for entry in combined_entries)
	base.write_json(provider_index_path, provider_index)
	if old_release_dir != new_release_dir:
		shutil.rmtree(old_release_dir)

	print(f"Extended UN WPP snapshot {old_snapshot} -> {new_snapshot}")
	print(f"Age indicators: {len(age_entries)}")
	print(f"Total indicators: {len(combined_entries)}")
	print(f"Ignored ISO3 codes: {', '.join(provider_index['ignoredIso3Codes']) or '(none)'}")


if __name__ == "__main__":
	main()
