#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import build_unesco_uis as builder

LATEST_OBSERVATION_FREQUENCY = "latest-observation-through-year"
MAGNITUDES_BY_SOURCE: dict[str, set[str]] = defaultdict(set)
LATEST_OBSERVATION_IDS: set[str] = set()
_ORIGINAL_FETCH_CSV = builder.fetch_csv
_ORIGINAL_BUILD_PAYLOADS = builder.build_payloads
_ORIGINAL_CHOOSE_DEFAULT_YEAR = builder.choose_default_year
_ORIGINAL_WRITE_JSON = builder.common.write_json


def configured_frequency(indicator: dict[str, Any]) -> str:
	return str(indicator.get("frequency", "annual")).strip() or "annual"


def fetch_csv_with_magnitudes(url: str, timeout: int) -> tuple[list[dict[str, str]], int]:
	rows, byte_count = _ORIGINAL_FETCH_CSV(url, timeout)
	for row in rows:
		source_indicator = str(row.get("indicator_id", "")).strip()
		magnitude = str(row.get("magnitude", "")).strip()
		if source_indicator and magnitude:
			MAGNITUDES_BY_SOURCE[source_indicator].add(magnitude)
		# build_unesco_uis validates this field as empty. Magnitude is metadata,
		# not a numeric scale factor; it is reattached to the payload below.
		row["magnitude"] = ""
	return rows, byte_count


def choose_default_year_with_temporal_modes(
	indicator: dict[str, Any],
	available_years: list[int],
	year_values: dict[int, dict[str, int | float]],
) -> int:
	if configured_frequency(indicator) == LATEST_OBSERVATION_FREQUENCY:
		if not available_years:
			raise RuntimeError(f"UNESCO UIS has no source years for {indicator['id']}.")
		return available_years[-1]
	return _ORIGINAL_CHOOSE_DEFAULT_YEAR(indicator, available_years, year_values)


def build_latest_observation_payload(
	indicator: dict[str, Any],
	payload: dict[str, Any],
) -> None:
	indicator_id = str(indicator["id"])
	raw_values = payload.get("values")
	if not isinstance(raw_values, dict) or not raw_values:
		raise RuntimeError(f"UNESCO UIS latest-observation indicator {indicator_id} has no source values.")

	direct_by_year: dict[int, dict[str, int | float]] = {}
	areas_with_any_value: set[str] = set()
	for year_text, mapped in raw_values.items():
		if not str(year_text).isdigit() or not isinstance(mapped, dict) or not mapped:
			continue
		year = int(year_text)
		direct_by_year[year] = {str(area_id): value for area_id, value in mapped.items()}
		areas_with_any_value.update(str(area_id) for area_id in mapped)
	if not direct_by_year:
		raise RuntimeError(f"UNESCO UIS latest-observation indicator {indicator_id} has no usable source years.")

	minimum_any = int(indicator["minAreasWithAnyValue"])
	if len(areas_with_any_value) < minimum_any:
		raise RuntimeError(
			f"UNESCO UIS latest-observation coverage too small for {indicator_id}: "
			f"{len(areas_with_any_value)} areas, expected at least {minimum_any}."
		)

	first_year = min(direct_by_year)
	last_year = max(direct_by_year)
	available_years = list(range(first_year, last_year + 1))
	current_values: dict[str, int | float] = {}
	current_source_years: dict[str, int] = {}
	values_by_year: dict[str, dict[str, int | float]] = {}
	metadata_by_year: dict[str, dict[str, dict[str, Any]]] = {}

	for target_year in available_years:
		for area_id, value in direct_by_year.get(target_year, {}).items():
			current_values[area_id] = value
			current_source_years[area_id] = target_year
		if not current_values:
			continue
		values_by_year[str(target_year)] = {
			area_id: current_values[area_id]
			for area_id in sorted(current_values)
		}
		metadata_by_year[str(target_year)] = {
			area_id: {
				"sourceYear": current_source_years[area_id],
				"dataAgeYears": target_year - current_source_years[area_id],
				"carriedForward": target_year != current_source_years[area_id],
			}
			for area_id in sorted(current_values)
		}

	default_year = last_year
	default_coverage = len(values_by_year[str(default_year)])
	minimum_default = int(indicator["minAreasInDefaultYear"])
	if default_coverage < minimum_default:
		raise RuntimeError(
			f"UNESCO UIS latest-observation default cutoff {default_year} for {indicator_id} "
			f"has only {default_coverage} areas; expected at least {minimum_default}."
		)
	if default_coverage != len(areas_with_any_value):
		raise RuntimeError(
			f"UNESCO UIS latest-observation cutoff {default_year} for {indicator_id} does not retain all "
			f"mapped areas: {default_coverage} != {len(areas_with_any_value)}."
		)

	direct_observations = sum(len(mapped) for mapped in direct_by_year.values())
	payload["frequency"] = LATEST_OBSERVATION_FREQUENCY
	payload["indicator"]["frequency"] = LATEST_OBSERVATION_FREQUENCY
	payload["availableYears"] = available_years
	payload["defaultYear"] = default_year
	payload["coverage"] = {
		"registryAreas": int(payload["coverage"]["registryAreas"]),
		"areasWithAnyValue": len(areas_with_any_value),
		"latestYear": last_year,
		"areasInLatestYear": default_coverage,
		"areasInDefaultYear": default_coverage,
	}
	payload["values"] = values_by_year
	payload["observationMetadata"] = metadata_by_year
	payload["source"]["sourceYearRange"] = [first_year, last_year]
	payload["source"]["sourceObservationCount"] = direct_observations
	payload["source"]["temporalDisplayPolicy"] = (
		"Each cutoff year shows the latest published UNESCO UIS observation with source year less than or "
		"equal to that cutoff. Values are carried forward unchanged and are never interpolated."
	)

	for target_year in available_years:
		key = str(target_year)
		for area_id, metadata in metadata_by_year[key].items():
			source_year = int(metadata["sourceYear"])
			if source_year > target_year:
				raise RuntimeError(
					f"UNESCO UIS source year lies after cutoff for {indicator_id} {target_year} {area_id}: "
					f"{source_year}."
				)
			source_value = values_by_year[str(source_year)].get(area_id)
			if source_value != values_by_year[key][area_id]:
				raise RuntimeError(
					f"UNESCO UIS carried value changed for {indicator_id} {target_year} {area_id}: "
					f"sourceYear={source_year}."
				)

	LATEST_OBSERVATION_IDS.add(indicator_id)
	print(
		f"{indicator_id}: latest-observation sourceYears={first_year}-{last_year} "
		f"sourceObservations={direct_observations} mapped={len(areas_with_any_value)} "
		f"defaultCoverage={default_coverage}"
	)


def build_payloads_with_magnitudes_and_temporal_modes(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_id: dict[str, dict[int, dict[str, int | float]]],
	qualifiers_by_id: dict[str, set[str]],
	footnote_rows_by_id: dict[str, int],
	export_urls: dict[str, str],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
	result = _ORIGINAL_BUILD_PAYLOADS(
		config,
		area_by_iso3,
		values_by_id,
		qualifiers_by_id,
		footnote_rows_by_id,
		export_urls,
	)
	for indicator, payload in result:
		frequency = configured_frequency(indicator)
		if frequency not in {"annual", LATEST_OBSERVATION_FREQUENCY}:
			raise RuntimeError(f"Unsupported UNESCO UIS frequency for {indicator['id']}: {frequency}")
		if frequency == LATEST_OBSERVATION_FREQUENCY:
			build_latest_observation_payload(indicator, payload)
		source_indicator = str(indicator["sourceIndicator"])
		payload["source"]["magnitudesObserved"] = sorted(MAGNITUDES_BY_SOURCE.get(source_indicator, set()))
	return result


def write_json_with_temporal_modes(path: Path, payload: Any) -> None:
	if (
		isinstance(payload, dict)
		and payload.get("schema") == "kartensammlung.statistics-provider-index/v1"
		and isinstance(payload.get("provider"), dict)
		and payload["provider"].get("id") == "unesco-uis"
	):
		indexed_latest_ids: set[str] = set()
		for indicator in payload.get("indicators", []):
			indicator_id = str(indicator.get("id", ""))
			if indicator_id in LATEST_OBSERVATION_IDS:
				indicator["frequency"] = LATEST_OBSERVATION_FREQUENCY
				indexed_latest_ids.add(indicator_id)
		if indexed_latest_ids != LATEST_OBSERVATION_IDS:
			raise RuntimeError(
				"UNESCO UIS provider index lost latest-observation indicators: "
				f"expected={sorted(LATEST_OBSERVATION_IDS)} indexed={sorted(indexed_latest_ids)}"
			)
		notes = payload.setdefault("notes", [])
		notes.append(
			"Literacy indicators use the latest published UIS observation through each cutoff year. "
			"Carried values are unchanged, never interpolated, and retain the actual source year in observationMetadata."
		)
	_ORIGINAL_WRITE_JSON(path, payload)


builder.fetch_csv = fetch_csv_with_magnitudes
builder.choose_default_year = choose_default_year_with_temporal_modes
builder.build_payloads = build_payloads_with_magnitudes_and_temporal_modes
builder.common.write_json = write_json_with_temporal_modes


if __name__ == "__main__":
	builder.main()
