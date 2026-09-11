#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen
import json
import shutil

import openpyxl

URL = "https://data.unodc.org/sites/dataportal.unodc.org/files/2026-07/data_cts_violent_and_sexual_crime.xlsx"
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def clean(value: object) -> str:
	return "" if value is None else " ".join(str(value).strip().split())


def key(value: object) -> str:
	return clean(value).casefold()


def parse_year(value: object) -> int | None:
	try:
		year = int(float(value))
	except (TypeError, ValueError):
		return None
	return year if 1900 <= year <= 2200 else None


def parse_number(value: object) -> float | None:
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def registry_names(area: dict[str, object]) -> set[str]:
	names: set[str] = set()
	for field in ("name", "label", "display_name", "displayName"):
		value = area.get(field)
		if isinstance(value, str) and value.strip():
			names.add(value.strip())
	for field in ("names", "name"):
		value = area.get(field)
		if isinstance(value, dict):
			for item in value.values():
				if isinstance(item, str) and item.strip():
					names.add(item.strip())
	return names


def main() -> None:
	handle = NamedTemporaryFile(prefix="unodc-violent-", suffix=".xlsx", delete=False)
	path = Path(handle.name)
	handle.close()
	try:
		request = Request(URL, headers={"User-Agent": USER_AGENT})
		with urlopen(request, timeout=90) as response, path.open("wb") as output:
			shutil.copyfileobj(response, output)
		print(f"downloadBytes={path.stat().st_size}")
		workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
		try:
			worksheet = workbook["data"]
			rows = worksheet.iter_rows(values_only=True)
			next(rows, None)
			next(rows, None)
			header = [clean(value) for value in next(rows, ())]
			print(f"header={header}")
			by_category: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
			countries: set[str] = set()
			for row in rows:
				if len(row) < 6:
					continue
				country = clean(row[2])
				category = clean(row[3])
				year = parse_year(row[4])
				value = parse_number(row[5])
				if not country or not category or year is None or value is None:
					continue
				countries.add(country)
				by_category[category].append((country, year, value))
		finally:
			workbook.close()

		registry_request = Request(REGISTRY_URL, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
		with urlopen(registry_request, timeout=90) as response:
			registry = json.load(response)
		areas = [area for area in registry.get("areas", []) if isinstance(area, dict) and area.get("level") == "country"]
		print(f"registryAreas={len(areas)}")
		for area in areas[:5]:
			print(f"registrySample={area}")
		name_to_area: dict[str, str] = {}
		for area in areas:
			area_id = clean(area.get("area_id"))
			for name in registry_names(area):
				name_to_area[key(name)] = area_id
		matched = sorted(country for country in countries if key(country) in name_to_area)
		unmatched = sorted(country for country in countries if key(country) not in name_to_area)
		print(f"countries={len(countries)} directRegistryMatches={len(matched)} unmatched={len(unmatched)}")
		print(f"unmatchedCountryNames={unmatched}")
		print(f"categories={len(by_category)}")
		for category in sorted(by_category):
			items = by_category[category]
			years = sorted({year for _, year, _ in items})
			category_countries = {country for country, _, _ in items}
			coverage_by_year: dict[int, int] = defaultdict(int)
			for country, year, _ in items:
				coverage_by_year[year] += 1
			best_year = max(coverage_by_year, key=lambda year: (coverage_by_year[year], year))
			latest_year = max(years)
			print(
				f"CATEGORY {category!r}: countries={len(category_countries)} years={years[0]}-{years[-1]} "
				f"bestYear={best_year}/{coverage_by_year[best_year]} latestYear={latest_year}/{coverage_by_year[latest_year]}"
			)
	finally:
		path.unlink(missing_ok=True)


if __name__ == "__main__":
	main()
