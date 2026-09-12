#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import statistics
import time
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
WHO_BASE = "https://ghoapi.azureedge.net/api/MDG_0000000026"
WDI_URL = "https://api.worldbank.org/v2/country/all/indicator/SH.STA.MMRT?format=json&per_page=20000"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def fetch_json(url: str, timeout: int = 120) -> Any:
	last_error: Exception | None = None
	for delay in (0, 3, 10, 20):
		if delay:
			time.sleep(delay)
		request = Request(url, headers={"Accept": "application/json,*/*", "User-Agent": USER_AGENT})
		try:
			with urlopen(request, timeout=timeout) as response:
				return json.loads(response.read().decode("utf-8-sig"))
		except Exception as error:
			last_error = error
			print(f"retry {url}: {error}")
	if last_error is None:
		raise RuntimeError(f"Request failed: {url}")
	raise last_error


def load_registry() -> set[str]:
	payload = fetch_json(REGISTRY_URL)
	result = {
		str((area.get("codes") or {}).get("iso3") or "").strip().upper()
		for area in payload.get("areas", [])
		if isinstance(area, dict) and area.get("level") == "country"
	}
	result.discard("")
	print(f"registry ISO3 countries={len(result)}")
	return result


def load_who(allowed_iso3: set[str]) -> tuple[dict[tuple[str, int], float], dict[tuple[str, int], tuple[float | None, float | None]]]:
	rows: list[dict[str, Any]] = []
	skip = 0
	while True:
		query = urlencode({"$top": 1000, "$skip": skip})
		payload = fetch_json(f"{WHO_BASE}?{query}")
		batch = payload.get("value") or []
		if not isinstance(batch, list):
			raise RuntimeError("Unexpected WHO GHO response")
		rows.extend(batch)
		if len(batch) < 1000:
			break
		skip += len(batch)
	print(f"WHO raw rows={len(rows)}")

	print("WHO keys=", sorted({key for row in rows for key in row}))
	print("WHO SpatialDimType=", Counter(str(row.get("SpatialDimType")) for row in rows))
	print("WHO dimension combos=", Counter((str(row.get("Dim1")), str(row.get("Dim2")), str(row.get("Dim3"))) for row in rows).most_common(20))

	values: dict[tuple[str, int], float] = {}
	bounds: dict[tuple[str, int], tuple[float | None, float | None]] = {}
	ignored_spatial: Counter[str] = Counter()
	for row in rows:
		iso3 = str(row.get("SpatialDim") or "").strip().upper()
		if iso3 not in allowed_iso3:
			if iso3:
				ignored_spatial[iso3] += 1
			continue
		try:
			year = int(row.get("TimeDim"))
			value = float(row.get("NumericValue"))
		except (TypeError, ValueError):
			continue
		if not math.isfinite(value):
			continue
		key = (iso3, year)
		if key in values:
			raise RuntimeError(f"Duplicate WHO value {iso3} {year}")
		values[key] = value
		low = row.get("Low")
		high = row.get("High")
		bounds[key] = (
			float(low) if low is not None and math.isfinite(float(low)) else None,
			float(high) if high is not None and math.isfinite(float(high)) else None,
		)
	print(f"WHO ignored spatial={dict(ignored_spatial)}")
	return values, bounds


def load_wdi(allowed_iso3: set[str]) -> dict[tuple[str, int], float]:
	payload = fetch_json(WDI_URL)
	if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
		raise RuntimeError("Unexpected WDI response")
	if int(payload[0].get("pages", 1)) != 1:
		raise RuntimeError("Unexpected WDI pagination")
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


def describe(label: str, values: dict[tuple[str, int], float]) -> None:
	years = sorted({year for _, year in values})
	countries = {iso3 for iso3, _ in values}
	print(f"{label}: observations={len(values)} countries={len(countries)} years={years[0]}-{years[-1]}")
	for year in years[-8:]:
		print(f"  {label} {year}: {sum(1 for _, row_year in values if row_year == year)} countries")


def main() -> None:
	allowed_iso3 = load_registry()
	who, bounds = load_who(allowed_iso3)
	wdi = load_wdi(allowed_iso3)
	describe("WHO", who)
	describe("WDI", wdi)

	common = sorted(set(who) & set(wdi))
	who_only = sorted(set(who) - set(wdi))
	wdi_only = sorted(set(wdi) - set(who))
	diffs = [abs(who[key] - wdi[key]) for key in common]
	rounded = [abs(round(who[key]) - wdi[key]) for key in common]
	rounded_1 = [abs(round(who[key], 1) - wdi[key]) for key in common]
	print(f"common={len(common)}")
	print(f"exact<=1e-12={sum(diff <= 1e-12 for diff in diffs)}")
	print(f"within1e-6={sum(diff <= 1e-6 for diff in diffs)}")
	print(f"roundWHO0_equals_WDI={sum(diff <= 1e-12 for diff in rounded)}/{len(common)}")
	print(f"roundWHO1_equals_WDI={sum(diff <= 1e-12 for diff in rounded_1)}/{len(common)}")
	print(f"median_abs_diff={statistics.median(diffs):.12g} mean_abs_diff={statistics.fmean(diffs):.12g} max_abs_diff={max(diffs):.12g}")
	print(f"WHO_ONLY={len(who_only)} countries={sorted({iso3 for iso3, _ in who_only})}")
	print(f"WDI_ONLY={len(wdi_only)} countries={sorted({iso3 for iso3, _ in wdi_only})}")

	mismatches = [key for key in common if abs(round(who[key]) - wdi[key]) > 1e-12]
	mismatch_by_country: dict[str, list[int]] = defaultdict(list)
	for iso3, year in mismatches:
		mismatch_by_country[iso3].append(year)
	print(f"ROUND_MISMATCH observations={len(mismatches)} countries={len(mismatch_by_country)}")
	for iso3 in sorted(mismatch_by_country, key=lambda code: (-len(mismatch_by_country[code]), code)):
		years = sorted(mismatch_by_country[iso3])
		outside = 0
		for year in years:
			low, high = bounds[(iso3, year)]
			if low is not None and high is not None and not (low <= wdi[(iso3, year)] <= high):
				outside += 1
		print(
			f"MISMATCH_COUNTRY {iso3}: n={len(years)} years={years[0]}-{years[-1]} "
			f"outsideWHOinterval={outside} years_list={years}"
		)

	outside_all = 0
	for key in common:
		low, high = bounds[key]
		if low is not None and high is not None and not (low <= wdi[key] <= high):
			outside_all += 1
	print(f"WDI_OUTSIDE_WHO_INTERVAL={outside_all}/{len(common)}")

	for key in sorted(common, key=lambda item: abs(who[item] - wdi[item]), reverse=True)[:30]:
		print(f"DIFF {key[0]} {key[1]} WHO={who[key]:.12g} WDI={wdi[key]:.12g} abs={abs(who[key]-wdi[key]):.12g} bounds={bounds.get(key)}")

	complete_bounds = sum(1 for low, high in bounds.values() if low is not None and high is not None)
	print(f"WHO_BOUNDS complete={complete_bounds}/{len(who)}")
	for year in sorted({year for _, year in common})[-8:]:
		keys = [key for key in common if key[1] == year]
		year_diffs = [abs(who[key] - wdi[key]) for key in keys]
		print(
			f"COMMON_YEAR {year}: n={len(keys)} exact={sum(diff <= 1e-12 for diff in year_diffs)} "
			f"round0={sum(abs(round(who[key])-wdi[key]) <= 1e-12 for key in keys)} "
			f"median_abs={statistics.median(year_diffs):.12g} max_abs={max(year_diffs):.12g}"
		)


if __name__ == "__main__":
	main()
