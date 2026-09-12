#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter, defaultdict
from urllib.request import Request, urlopen

URL = "https://bulks-faostat.fao.org/production/Inputs_LandUse_E_All_Data_(Normalized).zip"
DATA_FILE = "Inputs_LandUse_E_All_Data_(Normalized).csv"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def fetch_bytes(url: str) -> bytes:
	request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/zip,*/*"})
	with urlopen(request, timeout=180) as response:
		data = response.read()
	if not data:
		raise RuntimeError("FAOSTAT land-use ZIP is empty")
	return data


def main() -> None:
	data = fetch_bytes(URL)
	print(f"downloaded={len(data)} bytes")
	with zipfile.ZipFile(io.BytesIO(data)) as archive:
		if DATA_FILE not in archive.namelist():
			raise RuntimeError(f"Missing {DATA_FILE}")
		with archive.open(DATA_FILE) as raw:
			text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
			reader = csv.DictReader(text)
			print("fields=", reader.fieldnames)
			by_element: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
			years: dict[tuple[str, str, str], list[int]] = defaultdict(list)
			areas: dict[tuple[str, str, str], set[str]] = defaultdict(set)
			examples: dict[tuple[str, str, str], list[tuple[str, str, str, str]]] = defaultdict(list)
			for row in reader:
				if str(row.get("Item Code") or "").strip() != "6646":
					continue
				key = (
					str(row.get("Element Code") or "").strip(),
					str(row.get("Element") or "").strip(),
					str(row.get("Unit") or "").strip(),
				)
				flag = str(row.get("Flag") or "").strip()
				by_element[key][flag] += 1
				year = str(row.get("Year") or "").strip()
				if year.isdigit():
					years[key].append(int(year))
				areas[key].add(str(row.get("Area Code (M49)") or "").strip())
				if len(examples[key]) < 5:
					examples[key].append((str(row.get("Area") or ""), year, str(row.get("Value") or ""), flag))

	if not by_element:
		raise RuntimeError("No FAOSTAT rows found for forest land Item Code 6646")
	for key in sorted(by_element):
		code, element, unit = key
		year_values = years[key]
		print(
			f"ELEMENT code={code!r} name={element!r} unit={unit!r} rows={sum(by_element[key].values())} "
			f"areas={len(areas[key])} years={min(year_values) if year_values else None}-{max(year_values) if year_values else None} "
			f"flags={dict(by_element[key])}"
		)
		for example in examples[key]:
			print("  EXAMPLE", example)


if __name__ == "__main__":
	main()
