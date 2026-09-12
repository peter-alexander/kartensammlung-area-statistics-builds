#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import math
import statistics
import time
import zipfile
from collections import Counter, defaultdict
from typing import Any
from urllib.request import Request, urlopen

FAOSTAT_URL = "https://bulks-faostat.fao.org/production/Inputs_LandUse_E_All_Data_(Normalized).zip"
DATA_FILE = "Inputs_LandUse_E_All_Data_(Normalized).csv"
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
WDI_BASE = "https://api.worldbank.org/v2"
USER_AGENT = "kartensammlung-area-statistics-builds/1"

SERIES = {
	"percent": {
		"elementCode": "7209",
		"element": "Share in Land area",
		"unit": "%",
		"wdi": "AG.LND.FRST.ZS",
		"scale": 1.0,
	},
	"km2": {
		"elementCode": "5110",
		"element": "Area",
		"unit": "1000 ha",
		"wdi": "AG.LND.FRST.K2",
		"scale": 10.0,
	},
}


def fetch_bytes(url: str, accept: str = "*/*", timeout: int = 180) -> bytes:
	last_error: Exception | None = None
	for delay in (0, 3, 10, 20):
		if delay:
			time.sleep(delay)
		request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
		try:
			with urlopen(request, timeout=timeout) as response:
				data = response.read()
			if not data:
				raise RuntimeError(f"Empty response: {url}")
			return data
		except Exception as error:
			last_error = error
			print(f"retry {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"Request failed: {url}")
	raise last_error


def fetch_json(url: str) -> Any:
	return json.loads(fetch_bytes(url, "application/json,*/*").decode("utf-8-sig"))


def normalize_m49(raw: Any) -> str:
	text = str(raw if raw is not None else "").strip().lstrip("'")
	if not text or not text.isdigit():
		return ""
	return text.zfill(3)


def load_registry() -> tuple[dict[str, str], set[str]]:
	payload = fetch_json(REGISTRY_URL)
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.area-registry/v1":
		raise RuntimeError("Unexpected area registry")
	m49_to_iso3: dict[str, str] = {}
	iso3_codes: set[str] = set()
	for area in payload.get("areas") or []:
		if not isinstance(area, dict) or area.get("level") != "country":
			continue
		codes = area.get("codes") or {}
		m49 = str(codes.get("m49") or "").strip()
		iso3 = str(codes.get("iso3") or "").strip().upper()
		if m49 and iso3:
			m49_to_iso3[m49] = iso3
			iso3_codes.add(iso3)
	print(f"registry countries with M49+ISO3={len(m49_to_iso3)}")
	return m49_to_iso3, iso3_codes


def load_faostat(m49_to_iso3: dict[str, str]) -> tuple[
	dict[str, dict[tuple[str, int], float]],
	dict[str, dict[tuple[str, int], str]],
]:
	data = fetch_bytes(FAOSTAT_URL, "application/zip,*/*")
	print(f"FAOSTAT downloaded={len(data)} bytes")
	by_element = {str(spec["elementCode"]): name for name, spec in SERIES.items()}
	values: dict[str, dict[tuple[str, int], float]] = {name: {} for name in SERIES}
	flags: dict[str, dict[tuple[str, int], str]] = {name: {} for name in SERIES}
	unmapped_m49: Counter[str] = Counter()
	with zipfile.ZipFile(io.BytesIO(data)) as archive:
		if DATA_FILE not in archive.namelist():
			raise RuntimeError(f"Missing {DATA_FILE}")
		with archive.open(DATA_FILE) as raw:
			reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
			for row in reader:
				if str(row.get("Item Code") or "").strip() != "6646":
					continue
				element_code = str(row.get("Element Code") or "").strip()
				if element_code not in by_element:
					continue
				name = by_element[element_code]
				spec = SERIES[name]
				if str(row.get("Element") or "").strip() != spec["element"]:
					raise RuntimeError(f"Unexpected FAOSTAT element label for {element_code}: {row.get('Element')!r}")
				if str(row.get("Unit") or "").strip() != spec["unit"]:
					raise RuntimeError(f"Unexpected FAOSTAT unit for {element_code}: {row.get('Unit')!r}")
				m49 = normalize_m49(row.get("Area Code (M49)"))
				iso3 = m49_to_iso3.get(m49)
				if iso3 is None:
					if m49:
						unmapped_m49[m49] += 1
					continue
				year_text = str(row.get("Year") or "").strip()
				if not year_text.isdigit():
					continue
				year = int(year_text)
				try:
					value = float(str(row.get("Value") or "").strip()) * float(spec["scale"])
				except ValueError:
					continue
				if not math.isfinite(value):
					continue
				key = (iso3, year)
				if key in values[name]:
					raise RuntimeError(f"Duplicate FAOSTAT value {name} {iso3} {year}")
				values[name][key] = value
				flags[name][key] = str(row.get("Flag") or "").strip()
	print(f"unmapped FAOSTAT M49 codes={dict(unmapped_m49)}")
	for name in SERIES:
		years = sorted({year for _, year in values[name]})
		print(
			f"FAOSTAT {name}: observations={len(values[name])} countries={len({iso3 for iso3, _ in values[name]})} "
			f"years={years[0]}-{years[-1]} flags={dict(Counter(flags[name].values()))}"
		)
	return values, flags


def load_wdi(code: str, allowed_iso3: set[str]) -> dict[tuple[str, int], float]:
	payload = fetch_json(f"{WDI_BASE}/country/all/indicator/{code}?format=json&per_page=20000")
	if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
		raise RuntimeError(f"Unexpected WDI response for {code}")
	if int(payload[0].get("pages", 1)) != 1:
		raise RuntimeError(f"Unexpected WDI pagination for {code}")
	values: dict[tuple[str, int], float] = {}
	for row in payload[1]:
		if row.get("value") is None:
			continue
		iso3 = str(row.get("countryiso3code") or "").strip().upper()
		if iso3 not in allowed_iso3:
			continue
		try:
			year = int(row.get("date"))
			value = float(row.get("value"))
		 except (TypeError, ValueError):
			continue
		if math.isfinite(value):
			values[(iso3, year)] = value
	return values


def compare(
	name: str,
	faostat: dict[tuple[str, int], float],
	flags: dict[tuple[str, int], str],
	wdi: dict[tuple[str, int], float],
) -> None:
	common = sorted(set(faostat) & set(wdi))
	faostat_only = sorted(set(faostat) - set(wdi))
	wdi_only = sorted(set(wdi) - set(faostat))
	if not common:
		raise RuntimeError(f"No common values for {name}")
	diffs = [abs(faostat[key] - wdi[key]) for key in common]
	rel_diffs = [diff / max(abs(wdi[key]), 1e-12) for key, diff in zip(common, diffs)]
	print(f"\n=== {name}: FAOSTAT vs WDI {SERIES[name]['wdi']} ===")
	for label, values in (("FAOSTAT", faostat), ("WDI", wdi)):
		years = sorted({year for _, year in values})
		print(
			f"{label}: observations={len(values)} countries={len({iso3 for iso3, _ in values})} "
			f"years={years[0]}-{years[-1]}"
		)
		for year in years[-6:]:
			print(f"  {label} {year}: {sum(1 for _, row_year in values if row_year == year)} countries")
	print(
		f"common={len(common)} exact<=1e-12={sum(diff <= 1e-12 for diff in diffs)} "
		f"within1e-6={sum(diff <= 1e-6 for diff in diffs)}"
	)
	print(
		f"median_abs_diff={statistics.median(diffs):.12g} mean_abs_diff={statistics.fmean(diffs):.12g} "
		f"max_abs_diff={max(diffs):.12g} median_rel_diff={statistics.median(rel_diffs):.12g}"
	)
	print(
		f"faostat_only_pairs={len(faostat_only)} countries={sorted({iso3 for iso3, _ in faostat_only})}"
	)
	print(f"wdi_only_pairs={len(wdi_only)} countries={sorted({iso3 for iso3, _ in wdi_only})}")
	for key in sorted(common, key=lambda item: abs(faostat[item] - wdi[item]), reverse=True)[:20]:
		print(
			f"DIFF {key[0]} {key[1]} FAOSTAT={faostat[key]:.12g} WDI={wdi[key]:.12g} "
			f"abs={abs(faostat[key]-wdi[key]):.12g} flag={flags.get(key)}"
		)
	for year in sorted({year for _, year in common})[-8:]:
		keys = [key for key in common if key[1] == year]
		year_diffs = [abs(faostat[key] - wdi[key]) for key in keys]
		print(
			f"COMMON_YEAR {year}: n={len(keys)} exact={sum(diff <= 1e-12 for diff in year_diffs)} "
			f"median_abs={statistics.median(year_diffs):.12g} max_abs={max(year_diffs):.12g}"
		)


def main() -> None:
	m49_to_iso3, allowed_iso3 = load_registry()
	faostat, flags = load_faostat(m49_to_iso3)
	for name, spec in SERIES.items():
		wdi = load_wdi(str(spec["wdi"]), allowed_iso3)
		compare(name, faostat[name], flags[name], wdi)


if __name__ == "__main__":
	main()
