#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pycountry

USER_AGENT = "kartensammlung-area-statistics-builds/1"
WHO_BASE = "https://ghoapi.azureedge.net/api"
WDI_BASE = "https://api.worldbank.org/v2"

INDICATORS = (
	{
		"name": "physicians",
		"who": "HWF_0001",
		"wdi": "SH.MED.PHYS.ZS",
		"who_scale": 0.1,
	},
	{
		"name": "nurses_midwives",
		"who": "HWF_0006",
		"wdi": "SH.MED.NUMW.P3",
		"who_scale": 0.1,
	},
	{
		"name": "measles_mcv1",
		"who": "WHS8_110",
		"wdi": "SH.IMM.MEAS",
		"who_scale": 1.0,
	},
)


def fetch_json(url: str, timeout: int = 60) -> Any:
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
		raise RuntimeError(f"request failed: {url}")
	raise last_error


def valid_iso3(code: str) -> bool:
	return code == "XKX" or pycountry.countries.get(alpha_3=code) is not None


def fetch_who(code: str) -> dict[tuple[str, int], float]:
	values: dict[tuple[str, int], float] = {}
	params = {
		"$select": "SpatialDim,SpatialDimType,TimeDim,NumericValue,Value",
		"$filter": "SpatialDimType eq 'COUNTRY'",
		"$top": "1000",
		"$skip": "0",
	}
	url = f"{WHO_BASE}/{code}?{urlencode(params)}"
	pages = 0
	while url:
		pages += 1
		if pages > 100:
			raise RuntimeError(f"WHO {code}: pagination runaway")
		payload = fetch_json(url)
		rows = payload.get("value") if isinstance(payload, dict) else None
		if not isinstance(rows, list):
			raise RuntimeError(f"WHO {code}: unexpected response")
		for row in rows:
			iso3 = str(row.get("SpatialDim") or "").strip().upper()
			if not valid_iso3(iso3):
				continue
			try:
				year = int(row.get("TimeDim"))
				value = float(row.get("NumericValue") if row.get("NumericValue") is not None else row.get("Value"))
			except (TypeError, ValueError):
				continue
			if math.isfinite(value):
				values[(iso3, year)] = value
		next_url = payload.get("@odata.nextLink") or payload.get("odata.nextLink")
		if next_url:
			url = str(next_url)
		elif len(rows) >= 1000:
			params["$skip"] = str(int(params["$skip"]) + 1000)
			url = f"{WHO_BASE}/{code}?{urlencode(params)}"
		else:
			url = ""
	print(f"WHO {code}: {len(values)} observations, {pages} pages")
	return values


def fetch_wdi(code: str) -> dict[tuple[str, int], float]:
	url = f"{WDI_BASE}/country/all/indicator/{code}?format=json&per_page=20000"
	payload = fetch_json(url)
	if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
		raise RuntimeError(f"WDI {code}: unexpected response")
	if int(payload[0].get("pages", 1)) != 1:
		raise RuntimeError(f"WDI {code}: unexpectedly paginated")
	values: dict[tuple[str, int], float] = {}
	for row in payload[1]:
		if row.get("value") is None:
			continue
		iso3 = str(row.get("countryiso3code") or "").strip().upper()
		if not valid_iso3(iso3):
			continue
		try:
			year = int(row.get("date"))
			value = float(row["value"])
		except (TypeError, ValueError):
			continue
		if math.isfinite(value):
			values[(iso3, year)] = value
	print(f"WDI {code}: {len(values)} observations")
	return values


def summarize_series(label: str, values: dict[tuple[str, int], float]) -> None:
	years = sorted({year for _, year in values})
	countries = {iso3 for iso3, _ in values}
	latest_by_country: dict[str, int] = {}
	for iso3, year in values:
		latest_by_country[iso3] = max(latest_by_country.get(iso3, year), year)
	latest_year = max(years)
	latest_coverage = sum(1 for iso3, year in values if year == latest_year)
	print(
		f"{label}: observations={len(values)} countries={len(countries)} "
		f"years={years[0]}-{years[-1]} latest_year_coverage={latest_coverage}"
	)
	for year in sorted(years, reverse=True)[:6]:
		coverage = sum(1 for _, row_year in values if row_year == year)
		print(f"  {label} {year}: countries={coverage}")
	latest_counts: dict[int, int] = defaultdict(int)
	for year in latest_by_country.values():
		latest_counts[year] += 1
	print(f"  {label} latest-country-years: {dict(sorted(latest_counts.items(), reverse=True)[:8])}")


def compare(name: str, who: dict[tuple[str, int], float], wdi: dict[tuple[str, int], float], who_scale: float) -> None:
	who_scaled = {key: value * who_scale for key, value in who.items()}
	common = sorted(set(who_scaled) & set(wdi))
	who_only = sorted(set(who_scaled) - set(wdi))
	wdi_only = sorted(set(wdi) - set(who_scaled))
	if not common:
		raise RuntimeError(f"{name}: no common observations")
	diffs = [abs(who_scaled[key] - wdi[key]) for key in common]
	rel_diffs = [diff / max(abs(wdi[key]), 1e-12) for key, diff in zip(common, diffs)]
	exact_1e12 = sum(diff <= 1e-12 for diff in diffs)
	exact_1e6 = sum(diff <= 1e-6 for diff in diffs)
	print(f"\n=== {name} ===")
	summarize_series("WHO", who_scaled)
	summarize_series("WDI", wdi)
	print(
		f"common={len(common)} exact<=1e-12={exact_1e12}/{len(common)} "
		f"exact<=1e-6={exact_1e6}/{len(common)}"
	)
	print(
		f"median_abs_diff={statistics.median(diffs):.12g} "
		f"mean_abs_diff={statistics.fmean(diffs):.12g} "
		f"max_abs_diff={max(diffs):.12g} "
		f"median_rel_diff={statistics.median(rel_diffs):.12g}"
	)
	print(f"who_only_pairs={len(who_only)} wdi_only_pairs={len(wdi_only)}")
	print(f"who_only_countries={sorted({iso3 for iso3, _ in who_only})}")
	print(f"wdi_only_countries={sorted({iso3 for iso3, _ in wdi_only})}")
	for key in sorted(common, key=lambda item: abs(who_scaled[item] - wdi[item]), reverse=True)[:15]:
		print(
			f"DIFF {key[0]} {key[1]} WHO={who_scaled[key]:.12g} "
			f"WDI={wdi[key]:.12g} abs={abs(who_scaled[key] - wdi[key]):.12g}"
		)
	common_years = sorted({year for _, year in common})
	for year in common_years[-5:]:
		keys = [key for key in common if key[1] == year]
		year_diffs = [abs(who_scaled[key] - wdi[key]) for key in keys]
		print(
			f"COMMON_YEAR {year}: n={len(keys)} exact<=1e-6={sum(diff <= 1e-6 for diff in year_diffs)} "
			f"median_abs={statistics.median(year_diffs):.12g} max_abs={max(year_diffs):.12g}"
		)


def main() -> None:
	for indicator in INDICATORS:
		who = fetch_who(str(indicator["who"]))
		wdi = fetch_wdi(str(indicator["wdi"]))
		compare(str(indicator["name"]), who, wdi, float(indicator["who_scale"]))


if __name__ == "__main__":
	main()
