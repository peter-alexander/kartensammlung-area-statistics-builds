#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen
import shutil

import openpyxl

URL = "https://data.unodc.org/sites/dataportal.unodc.org/files/2026-07/data_cts_violent_and_sexual_crime.xlsx"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def clean(value: object) -> str:
	return "" if value is None else " ".join(str(value).strip().split())


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
			regions: set[str] = set()
			subregions: set[str] = set()
			for row in rows:
				if len(row) < 6:
					continue
				region = clean(row[0])
				subregion = clean(row[1])
				country = clean(row[2])
				category = clean(row[3])
				year = parse_year(row[4])
				value = parse_number(row[5])
				if not country or not category or year is None or value is None:
					continue
				countries.add(country)
				if region:
					regions.add(region)
				if subregion:
					subregions.add(subregion)
				by_category[category].append((country, year, value))
			print(f"countries={len(countries)}")
			print(f"countryNames={sorted(countries)}")
			print(f"regions={sorted(regions)}")
			print(f"subregions={sorted(subregions)}")
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
				latest_coverage = coverage_by_year[latest_year]
				samples = []
				for sample_country in ("Austria", "Germany", "United States of America", "United States", "India"):
					values = sorted((year, value) for country, year, value in items if country == sample_country)
					if values:
						samples.append(f"{sample_country}={values[-1]}")
				print(
					f"CATEGORY {category!r}: countries={len(category_countries)} years={years[0]}-{years[-1]} "
					f"bestYear={best_year}/{coverage_by_year[best_year]} latestYear={latest_year}/{latest_coverage} "
					f"samples={'; '.join(samples) or '(none)'}"
				)
		finally:
			workbook.close()
	finally:
		path.unlink(missing_ok=True)


if __name__ == "__main__":
	main()
