#!/usr/bin/env python3
from __future__ import annotations

import csv
from collections import defaultdict
from io import TextIOWrapper
from urllib.request import Request, urlopen

URL = "https://files.ember-energy.org/public-downloads/yearly_full_release_long_format.csv"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def main() -> None:
	request = Request(URL, headers={"User-Agent": USER_AGENT})
	with urlopen(request, timeout=180) as response:
		reader = csv.DictReader(TextIOWrapper(response, encoding="utf-8-sig", newline=""))
		print(f"columns={reader.fieldnames}")
		area_types: set[str] = set()
		categories: set[str] = set()
		subcategories: set[str] = set()
		variables: dict[tuple[str, str, str], set[str]] = defaultdict(set)
		coverage: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
		coverage_by_year: dict[tuple[str, str, str, str, int], set[str]] = defaultdict(set)
		years: set[int] = set()
		rows = 0
		for row in reader:
			rows += 1
			area_type = (row.get("Area type") or "").strip()
			category = (row.get("Category") or "").strip()
			subcategory = (row.get("Subcategory") or "").strip()
			variable = (row.get("Variable") or "").strip()
			unit = (row.get("Unit") or "").strip()
			area = (row.get("Area") or "").strip()
			year_text = (row.get("Year") or "").strip()
			value = (row.get("Value") or "").strip()
			area_types.add(area_type)
			categories.add(category)
			subcategories.add(subcategory)
			variables[(category, subcategory, variable)].add(unit)
			if year_text.isdigit():
				year = int(year_text)
				years.add(year)
			else:
				year = None
			if area_type == "Country or economy" and year is not None and value:
				coverage[(category, subcategory, variable, unit)].add(area)
				coverage_by_year[(category, subcategory, variable, unit, year)].add(area)

	print(f"rows={rows}")
	print(f"areaTypes={sorted(area_types)}")
	print(f"categories={sorted(categories)}")
	print(f"subcategories={sorted(subcategories)}")
	print(f"years={min(years) if years else None}-{max(years) if years else None}")
	print("VARIABLES")
	for key in sorted(variables):
		category, subcategory, variable = key
		units = sorted(variables[key])
		country_count = max((len(coverage[(category, subcategory, variable, unit)]) for unit in units), default=0)
		year_counts = {
			year: max((len(coverage_by_year[(category, subcategory, variable, unit, year)]) for unit in units), default=0)
			for year in (2023, 2024, 2025)
		}
		print(
			f"  {category} | {subcategory} | {variable} | units={units} | countries={country_count} "
			f"| 2023={year_counts[2023]} 2024={year_counts[2024]} 2025={year_counts[2025]}"
		)


if __name__ == "__main__":
	main()
