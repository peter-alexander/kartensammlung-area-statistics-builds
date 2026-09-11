#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter

import openpyxl

import build_unodc as base

URL = "https://data.unodc.org/sites/dataportal.unodc.org/files/2026-07/data_cts_violent_and_sexual_crime.xlsx"


def clean(value: object) -> str:
	return "" if value is None else " ".join(str(value).strip().split())


def main() -> None:
	path, source_url = base.download_xlsx([URL], 90)
	try:
		workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
		try:
			print(f"source={source_url}")
			print(f"sheets={workbook.sheetnames}")
			for worksheet in workbook.worksheets:
				print(f"\nSHEET {worksheet.title!r}")
				rows = worksheet.iter_rows(values_only=True)
				for index, row in enumerate(rows, start=1):
					print(f"ROW {index}: {[clean(value) for value in row[:16]]}")
					if index >= 8:
						break
				if "violent" not in worksheet.title.lower() and "assault" not in worksheet.title.lower() and "sexual" not in worksheet.title.lower():
					continue
				rows = worksheet.iter_rows(values_only=True)
				combinations: Counter[tuple[str, ...]] = Counter()
				for row in rows:
					if len(row) < 12:
						continue
					iso3 = clean(row[0]).upper()
					if len(iso3) != 3 or not iso3.isalpha():
						continue
					combinations[(clean(row[4]), clean(row[5]), clean(row[6]), clean(row[7]), clean(row[8]), clean(row[10]))] += 1
				print(f"combinations={len(combinations)}")
				for combination, count in combinations.most_common(200):
					print(
						f"{count:6d} | indicator={combination[0]!r} | dimension={combination[1]!r} | "
						f"category={combination[2]!r} | sex={combination[3]!r} | age={combination[4]!r} | unit={combination[5]!r}"
					)
		finally:
			workbook.close()
	finally:
		path.unlink(missing_ok=True)


if __name__ == "__main__":
	main()
