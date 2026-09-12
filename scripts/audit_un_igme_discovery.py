#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

BASE = "https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/UNICEF,GLOBAL_DATAFLOW,1.0"
STRUCTURE_URL = f"{BASE}/all?format=sdmx-json&detail=structureOnly"
SAMPLE_URL = f"{BASE}/AUT.CME_MRM0+CME_MRY0+CME_MRY0T4.?format=sdmx-json"


def fetch_json(url: str) -> Any:
	request = Request(url, headers={"Accept": "application/json", "User-Agent": "kartensammlung-area-statistics-builds/1"})
	with urlopen(request, timeout=120) as response:
		return json.load(response)


def main() -> None:
	payload = fetch_json(STRUCTURE_URL)
	structure = payload["structure"]
	for level in ("dataSet", "series", "observation"):
		dimensions = structure.get("dimensions", {}).get(level, [])
		print(f"DIMENSIONS {level}: {len(dimensions)}")
		for index, dimension in enumerate(dimensions):
			values = dimension.get("values") or []
			print(f"  {index}: id={dimension.get('id')!r} name={dimension.get('name')!r} values={len(values)}")
			if dimension.get("id") in {"INDICATOR", "SEX"}:
				for item in values:
					item_id = str(item.get("id") or "")
					item_name = str(item.get("name") or "")
					if dimension.get("id") == "SEX" or item_id in {"CME_MRM0", "CME_MRY0", "CME_MRY0T4"}:
						print(f"    {item_id}\t{item_name}")
	print("ATTRIBUTES")
	for level in ("dataSet", "series", "observation"):
		attributes = structure.get("attributes", {}).get(level, [])
		print(f"  {level}: {len(attributes)}")
		for index, attribute in enumerate(attributes):
			values = attribute.get("values") or []
			print(f"    {index}: id={attribute.get('id')!r} name={attribute.get('name')!r} values={len(values)}")
			if len(values) <= 20:
				for item in values:
					print(f"      {item.get('id')}\t{item.get('name')}")

	print("SAMPLE URL", SAMPLE_URL)
	sample = fetch_json(SAMPLE_URL)
	print("SAMPLE top-level", sorted(sample))
	print("SAMPLE metrics", sample.get("metrics"))
	sample_structure = sample.get("structure", {})
	for level in ("series", "observation"):
		print(f"SAMPLE {level} dimensions")
		for index, dimension in enumerate(sample_structure.get("dimensions", {}).get(level, [])):
			print(
				f"  {index}: {dimension.get('id')} "
				f"values={[(item.get('id'), item.get('name')) for item in (dimension.get('values') or [])]}"
			)
	print("SAMPLE observation attributes")
	for index, attribute in enumerate(sample_structure.get("attributes", {}).get("observation", [])):
		print(
			f"  {index}: {attribute.get('id')} "
			f"values={[(item.get('id'), item.get('name')) for item in (attribute.get('values') or [])[:20]]}"
		)
	data_sets = sample.get("dataSets") or []
	print("SAMPLE dataSets", len(data_sets))
	if data_sets:
		print(json.dumps(data_sets[0], ensure_ascii=False, sort_keys=True)[:12000])


if __name__ == "__main__":
	main()
