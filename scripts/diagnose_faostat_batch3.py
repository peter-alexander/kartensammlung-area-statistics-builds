#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
from urllib.request import Request, urlopen
import zipfile

REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
SOURCES = [
	("emissions-indicators", "EM", "https://bulks-faostat.fao.org/production/Climate_change_Emissions_indicators_E_All_Data_(Normalized).zip"),
]


def fetch(url: str) -> bytes:
	req = Request(url, headers={"User-Agent":"kartensammlung-area-statistics-builds/1"})
	with urlopen(req, timeout=180) as r:
		return r.read()


def decode(data: bytes) -> str:
	for enc in ("utf-8-sig", "cp1252", "latin-1"):
		try:
			return data.decode(enc)
		except UnicodeDecodeError:
			pass
	raise RuntimeError("decode failed")


def norm_m49(raw: str) -> str:
	v = str(raw or "").strip().lstrip("'")
	return v.zfill(3) if v.isdigit() else ""


def main() -> None:
	registry = json.loads(fetch(REGISTRY_URL))
	valid_m49 = {str(a.get("codes",{}).get("m49","")) for a in registry.get("areas",[]) if a.get("level")=="country" and a.get("codes",{}).get("m49")}
	print(f"REGISTRY countries={sum(1 for a in registry.get('areas',[]) if a.get('level')=='country')} m49={len(valid_m49)}")
	for source_id, code, url in SOURCES:
		blob = fetch(url)
		with zipfile.ZipFile(io.BytesIO(blob)) as zf:
			csv_names = [n for n in zf.namelist() if n.endswith("All_Data_(Normalized).csv")]
			if len(csv_names) != 1:
				raise RuntimeError(f"{source_id}: expected one normalized CSV, got {csv_names}")
			name = csv_names[0]
			reader = csv.DictReader(io.StringIO(decode(zf.read(name))))
			fields = reader.fieldnames or []
			row_count = 0
			min_year = None
			max_year = None
			items: dict[tuple[str,str], dict[str, object]] = {}
			for r in reader:
				row_count += 1
				year_text = str(r.get("Year", "")).strip()
				year = int(year_text) if year_text.isdigit() else None
				if year is not None:
					min_year = year if min_year is None else min(min_year, year)
					max_year = year if max_year is None else max(max_year, year)
				item = str(r.get("Item", "")).strip()
				item_code = str(r.get("Item Code", "")).strip()
				if not item:
					continue
				key = (item_code, item)
				entry = items.setdefault(key, {"combos": set(), "latest": None, "mapped": set()})
				entry["combos"].add((str(r.get("Element Code","")).strip(), str(r.get("Element","")).strip(), str(r.get("Unit","")).strip()))
				if year is None:
					continue
				latest = entry["latest"]
				if latest is None or year > latest:
					entry["latest"] = year
					entry["mapped"] = set()
				if year == entry["latest"]:
					code_m49 = norm_m49(r.get("Area Code (M49)",""))
					if code_m49 in valid_m49:
						entry["mapped"].add(code_m49)
		print(f"SOURCE {source_id} code={code} bytes={len(blob)} rows={row_count} file={name}")
		print("FIELDS", fields)
		print("YEARS", min_year, max_year)
		print(f"ITEMS matched={len(items)}")
		for (item_code,item), entry in sorted(items.items()):
			combo_text = "; ".join(f"{ec}:{e} [{u}]" for ec,e,u in sorted(entry["combos"]))
			print(f"ITEM {item_code} | {item} | latest={entry['latest']} mappedLatest={len(entry['mapped'])} | {combo_text}")


if __name__ == "__main__":
	main()
