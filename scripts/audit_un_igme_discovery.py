#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from typing import Any
from urllib.request import Request, urlopen

import pycountry

UNICEF_BASE = "https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/UNICEF,GLOBAL_DATAFLOW,1.0"
UNICEF_URL = f"{UNICEF_BASE}/.CME_MRM0+CME_MRY0+CME_MRY0T4._T?format=sdmx-json"
WDI_BASE = "https://api.worldbank.org/v2"
USER_AGENT = "kartensammlung-area-statistics-builds/1"

SERIES = {
	"CME_MRM0": ("neonatal", "SH.DYN.NMRT"),
	"CME_MRY0": ("infant", "SP.DYN.IMRT.IN"),
	"CME_MRY0T4": ("under5", "SH.DYN.MORT"),
}


def fetch_json(url: str, timeout: int = 120) -> Any:
	last_error: Exception | None = None
	for delay in (0, 3, 10, 20):
		if delay:
			time.sleep(delay)
		request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
		try:
			with urlopen(request, timeout=timeout) as response:
				return json.load(response)
		except Exception as error:
			last_error = error
			print(f"retry {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"Request failed: {url}")
	raise last_error


def valid_iso3(code: str) -> bool:
	return code == "XKX" or pycountry.countries.get(alpha_3=code) is not None


def dimension_values(structure: dict[str, Any], level: str, dimension_id: str) -> list[dict[str, Any]]:
	for dimension in structure.get("dimensions", {}).get(level, []):
		if dimension.get("id") == dimension_id:
			return list(dimension.get("values") or [])
	raise RuntimeError(f"Missing {level} dimension {dimension_id}")


def attribute_index(structure: dict[str, Any], attribute_id: str) -> tuple[int, list[dict[str, Any]]]:
	for index, attribute in enumerate(structure.get("attributes", {}).get("observation", [])):
		if attribute.get("id") == attribute_id:
			return index + 1, list(attribute.get("values") or [])
	raise RuntimeError(f"Missing observation attribute {attribute_id}")


def decode_attribute(observation: list[Any], position: int, values: list[dict[str, Any]]) -> float | None:
	if position >= len(observation) or observation[position] is None:
		return None
	index = int(observation[position])
	if not 0 <= index < len(values):
		raise RuntimeError(f"Attribute index out of range: {index}/{len(values)}")
	value = values[index].get("id")
	try:
		parsed = float(value)
	except (TypeError, ValueError):
		return None
	return parsed if math.isfinite(parsed) else None


def fetch_unicef() -> dict[str, dict[tuple[str, int], tuple[float, float | None, float | None]]]:
	payload = fetch_json(UNICEF_URL)
	data = payload.get("data") or payload
	structure = data.get("structure") or {}
	data_sets = data.get("dataSets") or []
	if len(data_sets) != 1:
		raise RuntimeError(f"Unexpected UNICEF dataset count: {len(data_sets)}")

	series_dimensions = structure.get("dimensions", {}).get("series", [])
	series_dimension_ids = [str(item.get("id")) for item in series_dimensions]
	if series_dimension_ids != ["REF_AREA", "INDICATOR", "SEX"]:
		raise RuntimeError(f"Unexpected UNICEF series dimensions: {series_dimension_ids}")
	areas = dimension_values(structure, "series", "REF_AREA")
	indicators = dimension_values(structure, "series", "INDICATOR")
	sexes = dimension_values(structure, "series", "SEX")
	times = dimension_values(structure, "observation", "TIME_PERIOD")
	lower_position, lower_values = attribute_index(structure, "LOWER_BOUND")
	upper_position, upper_values = attribute_index(structure, "UPPER_BOUND")

	result: dict[str, dict[tuple[str, int], tuple[float, float | None, float | None]]] = {
		code: {} for code in SERIES
	}
	for series_key, series_payload in (data_sets[0].get("series") or {}).items():
		indices = [int(item) for item in series_key.split(":")]
		if len(indices) != 3:
			raise RuntimeError(f"Unexpected UNICEF series key: {series_key}")
		iso3 = str(areas[indices[0]].get("id") or "").strip().upper()
		indicator = str(indicators[indices[1]].get("id") or "").strip()
		sex = str(sexes[indices[2]].get("id") or "").strip()
		if indicator not in SERIES or sex != "_T" or not valid_iso3(iso3):
			continue
		for observation_key, observation in (series_payload.get("observations") or {}).items():
			time_index = int(observation_key)
			if not 0 <= time_index < len(times):
				raise RuntimeError(f"UNICEF time index out of range: {time_index}/{len(times)}")
			year_text = str(times[time_index].get("id") or times[time_index].get("name") or "")
			if not year_text.isdigit():
				continue
			year = int(year_text)
			try:
				value = float(observation[0])
			except (TypeError, ValueError, IndexError):
				continue
			if not math.isfinite(value):
				continue
			lower = decode_attribute(observation, lower_position, lower_values)
			upper = decode_attribute(observation, upper_position, upper_values)
			if lower is not None and upper is not None and not lower <= value <= upper:
				raise RuntimeError(f"Invalid UNICEF interval {indicator} {iso3} {year}: {lower}, {value}, {upper}")
			key = (iso3, year)
			if key in result[indicator]:
				raise RuntimeError(f"Duplicate UNICEF value {indicator} {iso3} {year}")
			result[indicator][key] = (value, lower, upper)
	return result


def fetch_wdi(code: str) -> dict[tuple[str, int], float]:
	payload = fetch_json(f"{WDI_BASE}/country/all/indicator/{code}?format=json&per_page=20000")
	if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
		raise RuntimeError(f"Unexpected WDI response for {code}")
	values: dict[tuple[str, int], float] = {}
	for row in payload[1]:
		if row.get("value") is None:
			continue
		iso3 = str(row.get("countryiso3code") or "").strip().upper()
		if not valid_iso3(iso3):
			continue
		try:
			year = int(row.get("date"))
			value = float(row.get("value"))
		except (TypeError, ValueError):
			continue
		if math.isfinite(value):
			values[(iso3, year)] = value
	return values


def summarize(label: str, values: dict[tuple[str, int], Any]) -> None:
	years = sorted({year for _, year in values})
	countries = {iso3 for iso3, _ in values}
	print(f"{label}: observations={len(values)} countries={len(countries)} years={years[0]}-{years[-1]}")
	for year in years[-6:]:
		print(f"  {label} {year}: {sum(1 for _, row_year in values if row_year == year)} countries")


def compare(indicator: str, direct: dict[tuple[str, int], tuple[float, float | None, float | None]], wdi: dict[tuple[str, int], float]) -> None:
	name, wdi_code = SERIES[indicator]
	common = sorted(set(direct) & set(wdi))
	direct_only = sorted(set(direct) - set(wdi))
	wdi_only = sorted(set(wdi) - set(direct))
	diffs = [abs(direct[key][0] - wdi[key]) for key in common]
	rounded_tenth = sum(abs(round(direct[key][0], 1) - wdi[key]) <= 1e-12 for key in common)
	within_005 = sum(diff <= 0.0500000001 for diff in diffs)
	interval_count = sum(1 for value, lower, upper in direct.values() if lower is not None and upper is not None)
	print(f"\n=== {name}: {indicator} vs {wdi_code} ===")
	summarize("UN IGME", direct)
	summarize("WDI", wdi)
	print(f"UN IGME intervals={interval_count}/{len(direct)}")
	print(f"common={len(common)} round-direct-to-0.1-equals-WDI={rounded_tenth}/{len(common)} within-0.05={within_005}/{len(common)}")
	print(
		f"median_abs_diff={statistics.median(diffs):.12g} mean_abs_diff={statistics.fmean(diffs):.12g} "
		f"max_abs_diff={max(diffs):.12g}"
	)
	print(f"direct_only_pairs={len(direct_only)} direct_only_countries={len({iso3 for iso3, _ in direct_only})}")
	print(f"wdi_only_pairs={len(wdi_only)} wdi_only_countries={len({iso3 for iso3, _ in wdi_only})}")
	print(f"direct_only_country_codes={sorted({iso3 for iso3, _ in direct_only})}")
	print(f"wdi_only_country_codes={sorted({iso3 for iso3, _ in wdi_only})}")
	for key in sorted(common, key=lambda item: abs(direct[item][0] - wdi[item]), reverse=True)[:15]:
		value, lower, upper = direct[key]
		print(f"DIFF {key[0]} {key[1]} IGME={value:.12g} WDI={wdi[key]:.12g} abs={abs(value-wdi[key]):.12g} interval={lower},{upper}")
	for year in sorted({year for _, year in common})[-5:]:
		keys = [key for key in common if key[1] == year]
		year_diffs = [abs(direct[key][0] - wdi[key]) for key in keys]
		print(
			f"COMMON_YEAR {year}: n={len(keys)} rounded_tenth={sum(abs(round(direct[key][0], 1)-wdi[key]) <= 1e-12 for key in keys)} "
			f"median_abs={statistics.median(year_diffs):.12g} max_abs={max(year_diffs):.12g}"
		)


def main() -> None:
	direct = fetch_unicef()
	for indicator, (_, wdi_code) in SERIES.items():
		compare(indicator, direct[indicator], fetch_wdi(wdi_code))


if __name__ == "__main__":
	main()
