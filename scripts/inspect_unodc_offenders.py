#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter

import build_unodc as base

URL = "https://data.unodc.org/sites/dataportal.unodc.org/files/2026-07/data_cts_intentional_homicide.xlsx"
TARGETS = (
	"Persons arrested/suspected for intentional homicide",
	"Persons convicted for intentional homicide",
)


def main() -> None:
	path, source_url = base.download_xlsx([URL], 90)
	try:
		records = base.read_records(path)
	finally:
		path.unlink(missing_ok=True)
	print(f"source={source_url}")
	for indicator in TARGETS:
		rows = [record for record in records if base.equal_text(record["indicator"], indicator)]
		print(f"\n{indicator}: rows={len(rows)}")
		combinations = Counter(
			(
				record["dimension"],
				record["category"],
				record["sex"],
				record["age"],
				record["unit"],
			)
			for record in rows
		)
		for combination, count in combinations.most_common(200):
			print(f"{count:6d} | dimension={combination[0]!r} | category={combination[1]!r} | sex={combination[2]!r} | age={combination[3]!r} | unit={combination[4]!r}")


if __name__ == "__main__":
	main()
