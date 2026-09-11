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
				years.add(int(year_text))
			if area_type == "Country or economy" and year_text.isdigit() and value:
				coverage[(category, subcategory, variable, unit)].add(area)

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
		print(f"  {category} | {subcategory} | {variable} | units={units} | countries={country_count}")


if __name__ == "__main__":
	main()
