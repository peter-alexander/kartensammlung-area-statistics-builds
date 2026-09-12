#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import io
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_world_bank as wb

REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
WUP_URL = (
	"https://population.un.org/wup/assets/Download/Countries%20and%20Aggregates/"
	"WUP2025-DB-National-Definitions-Population-Data.csv.gz"
)
WDI_INDICATOR = "SP.URB.TOTL.IN.ZS"
MAX_ESTIMATE_YEAR = 2025
USER_AGENT = "Kartensammlung-WUP-Audit/1.0"


def fetch_bytes(url: str, timeout: int = 90) -> bytes:
	delays = (0, 5, 15, 30, 60)
	last_error: Exception | None = None
	for attempt, delay in enumerate(delays, start=1):
		if delay:
			time.sleep(delay)
		try:
			with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout) as response:
				data = response.read()
				print(
					f"download status={response.status} bytes={len(data)} "
					f"lastModified={response.headers.get('Last-Modified')}"
				)
				return data
		except (HTTPError, URLError, TimeoutError, OSError) as error:
			last_error = error
			print(f"download failed ({attempt}/{len(delays)}): {error}")
	if last_error is None:
		raise RuntimeError("WUP download failed without exception")
	raise RuntimeError("WUP download failed after retries") from last_error


def percentile(values: list[float], fraction: float) -> float:
	if not values:
		return math.nan
	ordered = sorted(values)
	index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
	return ordered[index]


def main() -> None:
	area_by_iso3, registry = wb.load_registry(REGISTRY_URL, 60)
	area_name = {
		str(area.get("area_id", "")): str(area.get("name", area.get("area_id", "")))
		for area in registry.get("areas", [])
		if isinstance(area, dict)
	}
	print(f"registry iso3={len(area_by_iso3)}")

	compressed = fetch_bytes(WUP_URL)
	text = gzip.decompress(compressed).decode("utf-8-sig")
	reader = csv.DictReader(io.StringIO(text))
	required_columns = {
		"Location",
		"ISO3_Code",
		"LocTypeName",
		"Category",
		"Year",
		"percPop",
	}
	missing = required_columns - set(reader.fieldnames or [])
	if missing:
		raise RuntimeError(f"WUP columns missing: {sorted(missing)}")

	wup: dict[tuple[str, int], float] = {}
	wup_area_ids: set[str] = set()
	wup_unmapped = Counter()
	wup_blank_iso = Counter()
	wup_year_counts = Counter()
	raw_country_urban = 0
	projection_rows_skipped = 0

	for row in reader:
		if row.get("LocTypeName") != "Country/Area" or row.get("Category") != "Urban":
			continue
		raw_country_urban += 1
		year_text = str(row.get("Year", "")).strip()
		if not year_text.isdigit():
			continue
		year = int(year_text)
		if year > MAX_ESTIMATE_YEAR:
			projection_rows_skipped += 1
			continue
		iso3 = str(row.get("ISO3_Code", "")).strip().upper()
		location = str(row.get("Location", "")).strip()
		if not iso3:
			wup_blank_iso[location] += 1
			continue
		if iso3 not in area_by_iso3:
			wup_unmapped[f"{iso3} {location}"] += 1
			continue
		value_text = str(row.get("percPop", "")).strip()
		if not value_text:
			continue
		value = float(value_text)
		if not math.isfinite(value):
			raise RuntimeError(f"Non-finite WUP value: {iso3} {year}")
		key = (iso3, year)
		if key in wup:
			raise RuntimeError(f"Duplicate WUP observation: {key}")
		wup[key] = value
		wup_area_ids.add(area_by_iso3[iso3])
		wup_year_counts[year] += 1

	print(
		f"WUP rawCountryUrban={raw_country_urban} mapped={len(wup)} "
		f"areas={len(wup_area_ids)} years={min(y for _, y in wup)}-{max(y for _, y in wup)} "
		f"projectionsSkipped={projection_rows_skipped}"
	)
	print(f"WUP blankISO locations={dict(wup_blank_iso)}")
	print(f"WUP unmapped locations={dict(wup_unmapped)}")
	print(f"WUP 1950 coverage={wup_year_counts[1950]} 1960={wup_year_counts[1960]} 2024={wup_year_counts[2024]} 2025={wup_year_counts[2025]}")

	records = wb.fetch_world_bank_records(
		"https://api.worldbank.org/v2",
		f"country/all/indicator/{WDI_INDICATOR}",
		2,
		60,
	)
	wdi: dict[tuple[str, int], float] = {}
	wdi_area_ids: set[str] = set()
	wdi_ignored = Counter()
	wdi_year_counts = Counter()
	forecast_skipped = 0
	future_skipped = 0
	for record in records:
		value = record.get("value")
		if value is None:
			continue
		if str(record.get("obs_status", "")).strip().upper() == "F":
			forecast_skipped += 1
			continue
		iso3 = str(record.get("countryiso3code", "")).strip().upper()
		if iso3 not in area_by_iso3:
			if iso3:
				wdi_ignored[iso3] += 1
			continue
		year_text = str(record.get("date", "")).strip()
		if not year_text.isdigit():
			continue
		year = int(year_text)
		if year > MAX_ESTIMATE_YEAR:
			future_skipped += 1
			continue
		number = float(value)
		key = (iso3, year)
		if key in wdi:
			raise RuntimeError(f"Duplicate WDI observation: {key}")
		wdi[key] = number
		wdi_area_ids.add(area_by_iso3[iso3])
		wdi_year_counts[year] += 1

	print(
		f"WDI mapped={len(wdi)} areas={len(wdi_area_ids)} "
		f"years={min(y for _, y in wdi)}-{max(y for _, y in wdi)} "
		f"forecastSkipped={forecast_skipped} futureSkipped={future_skipped}"
	)
	print(f"WDI ignoredCodes={sorted(wdi_ignored)}")
	print(f"WDI 1960 coverage={wdi_year_counts[1960]} 2024={wdi_year_counts[2024]} 2025={wdi_year_counts[2025]}")

	wup_keys = set(wup)
	wdi_keys = set(wdi)
	common = sorted(wup_keys & wdi_keys)
	wup_only = sorted(wup_keys - wdi_keys)
	wdi_only = sorted(wdi_keys - wup_keys)
	diffs = [abs(wup[key] - wdi[key]) for key in common]
	print(
		f"COMPARE common={len(common)} wupOnly={len(wup_only)} wdiOnly={len(wdi_only)} "
		f"exact={sum(diff == 0 for diff in diffs)} "
		f"le1e-12={sum(diff <= 1e-12 for diff in diffs)} "
		f"le1e-9={sum(diff <= 1e-9 for diff in diffs)} "
		f"le1e-6={sum(diff <= 1e-6 for diff in diffs)}"
	)
	print(
		f"DIFF max={max(diffs) if diffs else math.nan:.15g} "
		f"mean={statistics.fmean(diffs) if diffs else math.nan:.15g} "
		f"median={statistics.median(diffs) if diffs else math.nan:.15g} "
		f"p95={percentile(diffs, 0.95):.15g} p99={percentile(diffs, 0.99):.15g}"
	)

	common_1960 = [key for key in common if key[1] >= 1960]
	diffs_1960 = [abs(wup[key] - wdi[key]) for key in common_1960]
	print(
		f"COMPARE1960 common={len(common_1960)} "
		f"exact={sum(diff == 0 for diff in diffs_1960)} "
		f"le1e-9={sum(diff <= 1e-9 for diff in diffs_1960)} "
		f"max={max(diffs_1960) if diffs_1960 else math.nan:.15g}"
	)

	wup_only_years = Counter(year for _, year in wup_only)
	wdi_only_years = Counter(year for _, year in wdi_only)
	print(
		"WUP_ONLY byRange "
		f"1950-1959={sum(count for year, count in wup_only_years.items() if 1950 <= year <= 1959)} "
		f"1960-1999={sum(count for year, count in wup_only_years.items() if 1960 <= year <= 1999)} "
		f"2000-2024={sum(count for year, count in wup_only_years.items() if 2000 <= year <= 2024)} "
		f"2025={wup_only_years[2025]}"
	)
	print(
		"WDI_ONLY byRange "
		f"1950-1959={sum(count for year, count in wdi_only_years.items() if 1950 <= year <= 1959)} "
		f"1960-1999={sum(count for year, count in wdi_only_years.items() if 1960 <= year <= 1999)} "
		f"2000-2024={sum(count for year, count in wdi_only_years.items() if 2000 <= year <= 2024)} "
		f"2025={wdi_only_years[2025]}"
	)

	for year in (1950, 1960, 1990, 2000, 2024, 2025):
		direct = {iso3 for iso3, y in wup if y == year}
		distributed = {iso3 for iso3, y in wdi if y == year}
		print(
			f"YEAR {year} WUP={len(direct)} WDI={len(distributed)} "
			f"WUPonly={len(direct - distributed)} WDIonly={len(distributed - direct)}"
		)
		if year in (2024, 2025):
			print("  WUPonlyAreas", [(iso3, area_name.get(area_by_iso3[iso3], area_by_iso3[iso3])) for iso3 in sorted(direct - distributed)])
			print("  WDIonlyAreas", [(iso3, area_name.get(area_by_iso3[iso3], area_by_iso3[iso3])) for iso3 in sorted(distributed - direct)])

	largest = sorted(common, key=lambda key: abs(wup[key] - wdi[key]), reverse=True)[:30]
	print("LARGEST_DIFFERENCES")
	for key in largest:
		diff = abs(wup[key] - wdi[key])
		if diff == 0:
			break
		iso3, year = key
		print(f"  {iso3} {year}: WUP={wup[key]:.15g} WDI={wdi[key]:.15g} diff={diff:.15g}")

	print("WDI_ONLY observations", wdi_only[:100])
	print("WUP_ONLY_2025", [key for key in wup_only if key[1] == 2025])


if __name__ == "__main__":
	main()
