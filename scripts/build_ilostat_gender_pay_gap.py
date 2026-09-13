#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from typing import Any

import build_ilostat as ilo_common
import build_world_bank as common

EXPECTED_DATASET = "EAR_GGAP_OCU_RT_A"
EXPECTED_INDICATOR = "EAR_GGAP_OCU_RT"
EXPECTED_TABLE_LABEL = "Gender wage gap by occupation (%)"
EXPECTED_CLASSIFICATION = "OCU_SKILL_TOTAL"
EXPECTED_FREQUENCY = "latest-observation-through-year"


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
	indicator = config.get("genderPayGap")
	if not isinstance(indicator, dict):
		raise ValueError("ILOSTAT wages config is missing genderPayGap metadata.")

	for key in ("id", "slug", "sourceDataset", "sourceIndicator", "sourceTableLabel", "filterClassif1", "title", "description", "frequency"):
		if not str(indicator.get(key, "")).strip():
			raise ValueError(f"ILOSTAT gender pay gap config is missing {key}.")
	if indicator["sourceDataset"] != EXPECTED_DATASET:
		raise ValueError(f"ILOSTAT gender pay gap sourceDataset must be {EXPECTED_DATASET}.")
	if indicator["sourceIndicator"] != EXPECTED_INDICATOR:
		raise ValueError(f"ILOSTAT gender pay gap sourceIndicator must be {EXPECTED_INDICATOR}.")
	if indicator["sourceTableLabel"] != EXPECTED_TABLE_LABEL:
		raise ValueError(f"ILOSTAT gender pay gap sourceTableLabel must be {EXPECTED_TABLE_LABEL!r}.")
	if indicator["filterClassif1"] != EXPECTED_CLASSIFICATION:
		raise ValueError(f"ILOSTAT gender pay gap filterClassif1 must be {EXPECTED_CLASSIFICATION}.")
	if indicator["frequency"] != EXPECTED_FREQUENCY:
		raise ValueError(f"ILOSTAT gender pay gap frequency must be {EXPECTED_FREQUENCY}.")

	unit = indicator.get("unit")
	if not isinstance(unit, dict) or unit.get("id") != "percent" or not str(unit.get("label", "")).strip():
		raise ValueError("ILOSTAT gender pay gap unit must be percent.")
	common.validate_classification(str(indicator["id"]), indicator.get("classification"))

	for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
		value = indicator.get(key)
		if not isinstance(value, int) or value <= 0:
			raise ValueError(f"ILOSTAT gender pay gap has invalid {key}.")
	required_areas = indicator.get("requiredAreas")
	if not isinstance(required_areas, list) or not required_areas:
		raise ValueError("ILOSTAT gender pay gap requires at least one required area.")
	for forbidden in ("country:DEU", "country:POL", "country:JPN"):
		if forbidden in required_areas:
			raise ValueError(f"{forbidden} is not present in the official ILOSTAT gender-pay-gap series.")
	return indicator


def load_source_metadata(config: dict[str, Any], indicator: dict[str, Any], timeout: int) -> dict[str, str]:
	data = ilo_common.fetch_bytes(str(config["tocUrl"]), timeout)
	rows = ilo_common.read_csv_bytes(data, str(config["tocUrl"]))
	by_id = {
		str(row.get("id", "")).strip(): row
		for row in rows
		if str(row.get("id", "")).strip()
	}
	if len(by_id) < 1000:
		raise RuntimeError(f"ILOSTAT table of contents unexpectedly small: {len(by_id)} datasets.")

	dataset_id = str(indicator["sourceDataset"])
	row = by_id.get(dataset_id)
	if row is None:
		raise RuntimeError(f"ILOSTAT ToC is missing gender-pay-gap dataset {dataset_id}.")
	label = str(row.get("indicator.label", "")).strip()
	freq = str(row.get("freq", "")).strip()
	subject = str(row.get("subject", "")).strip()
	if label != str(indicator["sourceTableLabel"]):
		raise RuntimeError(f"Unexpected ILOSTAT gender-pay-gap table label: {label!r}")
	if freq != "A":
		raise RuntimeError(f"ILOSTAT gender-pay-gap dataset is not annual: freq={freq!r}")
	if subject and subject != "EAR":
		raise RuntimeError(f"Unexpected ILOSTAT gender-pay-gap subject: {subject!r}")
	return row


def load_source_rows(
	config: dict[str, Any],
	indicator: dict[str, Any],
	timeout: int,
) -> tuple[list[dict[str, str]], str]:
	url = ilo_common.dataset_url(str(config["apiBase"]), str(indicator["sourceDataset"]))
	data = ilo_common.fetch_bytes(url, timeout)
	rows = ilo_common.read_csv_bytes(data, url)
	if len(rows) < 10000:
		raise RuntimeError(f"ILOSTAT gender-pay-gap dataset unexpectedly small: {len(rows)} rows.")

	required_fields = {"ref_area", "source", "indicator", "classif1", "time", "obs_value"}
	missing = required_fields - set(rows[0])
	if missing:
		raise RuntimeError(f"ILOSTAT gender-pay-gap CSV is missing fields: {sorted(missing)}")
	indicators = {
		str(row.get("indicator", "")).strip()
		for row in rows
		if str(row.get("indicator", "")).strip()
	}
	if indicators != {str(indicator["sourceIndicator"])}:
		raise RuntimeError(f"Unexpected ILOSTAT gender-pay-gap indicator codes: {sorted(indicators)}")
	classifications = {
		str(row.get("classif1", "")).strip()
		for row in rows
		if str(row.get("classif1", "")).strip()
	}
	if str(indicator["filterClassif1"]) not in classifications:
		raise RuntimeError(
			f"ILOSTAT gender-pay-gap classification is missing {indicator['filterClassif1']}."
		)
	return rows, url


def observation_metadata(row: dict[str, str], source_year: int, target_year: int) -> dict[str, Any]:
	metadata: dict[str, Any] = {
		"sourceYear": source_year,
		"dataAgeYears": target_year - source_year,
		"carriedForward": target_year != source_year,
	}
	for source_key, target_key in (
		("source", "sourceCode"),
		("obs_status", "observationStatus"),
		("note_indicator", "indicatorNoteCodes"),
		("note_source", "sourceNoteCodes"),
	):
		value = str(row.get(source_key, "")).strip()
		if value:
			metadata[target_key] = value
	if target_year == source_year:
		metadata["sourceNote"] = (
			f"ILOSTAT-Datenjahr {source_year}; veröffentlichter Originalwert, nicht interpoliert."
		)
	else:
		metadata["sourceNote"] = (
			f"ILOSTAT-Datenjahr {source_year}; letzter bis einschließlich {target_year} verfügbarer "
			"veröffentlichter Wert, unverändert fortgeführt und nicht interpoliert."
		)
	return metadata


def build_payload(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	current_year: int,
	timeout: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
	indicator = validate_config(config)
	source_metadata = load_source_metadata(config, indicator, timeout)
	rows, source_url = load_source_rows(config, indicator, timeout)
	provider = config["provider"]
	classif1 = str(indicator["filterClassif1"])

	observations_by_area: dict[str, list[tuple[int, int | float, dict[str, str]]]] = defaultdict(list)
	ignored_codes: set[str] = set()
	future_records = 0
	seen: set[tuple[int, str]] = set()
	for row in rows:
		if str(row.get("classif1", "")).strip() != classif1:
			continue
		value_text = str(row.get("obs_value", "")).strip()
		if not value_text:
			continue
		iso3 = str(row.get("ref_area", "")).strip().upper()
		if iso3 not in area_by_iso3:
			if iso3:
				ignored_codes.add(iso3)
			continue
		year_text = str(row.get("time", "")).strip()
		if len(year_text) != 4 or not year_text.isdigit():
			continue
		source_year = int(year_text)
		if source_year > current_year:
			future_records += 1
			continue
		area_id = area_by_iso3[iso3]
		key = (source_year, area_id)
		if key in seen:
			raise RuntimeError(f"Duplicate official ILOSTAT gender-pay-gap value for {area_id} {source_year}.")
		seen.add(key)
		value = common.normalize_number(value_text)
		observations_by_area[area_id].append((source_year, value, row))

	for observations in observations_by_area.values():
		observations.sort(key=lambda item: item[0])
	minimum_any = int(indicator["minAreasWithAnyValue"])
	if len(observations_by_area) < minimum_any:
		raise RuntimeError(
			f"ILOSTAT gender-pay-gap coverage too small: {len(observations_by_area)} areas, "
			f"expected at least {minimum_any}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in observations_by_area:
			raise RuntimeError(f"Required area {area_id} has no official ILOSTAT gender-pay-gap values.")
	if not seen:
		raise RuntimeError("ILOSTAT gender-pay-gap series has no mapped observations.")

	first_source_year = min(year for year, _area_id in seen)
	last_source_year = max(year for year, _area_id in seen)
	if current_year < last_source_year:
		raise RuntimeError(
			f"Current year {current_year} precedes latest ILOSTAT gender-pay-gap source year {last_source_year}."
		)
	cutoff_years = list(range(first_source_year, current_year + 1))
	values_by_year: dict[int, dict[str, int | float]] = defaultdict(dict)
	metadata_by_year: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)

	for target_year in cutoff_years:
		for area_id, observations in observations_by_area.items():
			latest: tuple[int, int | float, dict[str, str]] | None = None
			for observation in observations:
				if observation[0] > target_year:
					break
				latest = observation
			if latest is None:
				continue
			source_year, value, row = latest
			values_by_year[target_year][area_id] = value
			metadata_by_year[target_year][area_id] = observation_metadata(row, source_year, target_year)

	cutoff_years = [year for year in cutoff_years if values_by_year[year]]
	default_year = cutoff_years[-1]
	default_values = values_by_year[default_year]
	minimum_default = int(indicator["minAreasInDefaultYear"])
	if len(default_values) < minimum_default:
		raise RuntimeError(
			f"ILOSTAT gender-pay-gap default cutoff {default_year} has {len(default_values)} areas; "
			f"expected at least {minimum_default}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in default_values:
			raise RuntimeError(f"Required area {area_id} is missing from ILOSTAT gender-pay-gap default cutoff.")

	sorted_values = {
		str(year): {
			area_id: values_by_year[year][area_id]
			for area_id in sorted(values_by_year[year])
		}
		for year in cutoff_years
	}
	sorted_metadata = {
		str(year): {
			area_id: metadata_by_year[year][area_id]
			for area_id in sorted(metadata_by_year[year])
		}
		for year in cutoff_years
	}

	payload = {
		"schema": "kartensammlung.statistics-indicator/v1",
		"areaLevel": "country",
		"frequency": indicator["frequency"],
		"indicator": {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		},
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"sourceDataset": indicator["sourceDataset"],
			"indicator": indicator["sourceIndicator"],
			"tableLabel": str(source_metadata.get("indicator.label", "")).strip(),
			"filters": {"classif1": classif1},
			"selectionPolicy": "Official ILOSTAT total skill-level series (OCU_SKILL_TOTAL); no cross-provider fallback.",
			"temporalDisplayPolicy": (
				"Each cutoff year shows the latest official ILOSTAT observation with source year less than or "
				"equal to that cutoff; values are carried forward unchanged and never interpolated."
			),
			"sourceYearRange": [first_source_year, last_source_year],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourcePage"],
			"apiUrl": source_url,
		},
		"availableYears": cutoff_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(observations_by_area),
			"latestYear": cutoff_years[-1],
			"latestSourceYear": last_source_year,
			"areasInLatestYear": len(values_by_year[cutoff_years[-1]]),
			"areasInDefaultYear": len(default_values),
		},
		"values": sorted_values,
		"observationMetadata": sorted_metadata,
	}

	print(
		f"  {indicator['id']}: mapped={len(observations_by_area)} "
		f"sourceYears={first_source_year}-{last_source_year} "
		f"cutoffs={cutoff_years[0]}-{cutoff_years[-1]} "
		f"defaultYear={default_year} defaultCoverage={len(default_values)} "
		f"ignoredCodes={len(ignored_codes)} futureSkipped={future_records}"
	)
	return indicator, payload, source_metadata
