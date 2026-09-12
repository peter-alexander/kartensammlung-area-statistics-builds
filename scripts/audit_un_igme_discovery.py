#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

BASE = "https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/UNICEF,GLOBAL_DATAFLOW,1.0"
STRUCTURE_URL = f"{BASE}/all?format=sdmx-json&detail=structureOnly"
SAMPLE_URL = f"{BASE}/AUT.CME_MRM0+CME_MRY0+CME_MRY0T4._T?format=sdmx-json"


def fetch_json(url: str) -> Any:
	request = Request(url, headers={"Accept": "application/json", "User-Agent": "kartensammlung-area-statistics-builds/1"})
	with urlopen(request, timeout=120) as response:
		return json.load(response)


def dump_structure(label: str, structure: dict[str, Any]) -> None:
	print(label)
	for level in ("dataSet", "series", "observation"):
		print(f"  DIMENSIONS {level}")
		for index, dimension in enumerate(structure.get("dimensions", {}).get(level, [])):
			values = dimension.get("values") or []
			print(f"    {index}: id={dimension.get('id')!r} name={dimension.get('name')!r} values={len(values)}")
			if len(values) <= 10:
				for value in values:
					print(f"      {value.get('id')}\t{value.get('name')}")
		print(f"  ATTRIBUTES {level}")
		for index, attribute in enumerate(structure.get("attributes", {}).get(level, [])):
			values = attribute.get("values") or []
			print(f"    {index}: id={attribute.get('id')!r} name={attribute.get('name')!r} values={len(values)}")
			for value in values[:12]:
				print(f"      {value.get('id')}\t{value.get('name')}")


def main() -> None:
	payload = fetch_json(STRUCTURE_URL)
	dump_structure("GLOBAL STRUCTURE", payload["structure"])

	print("SAMPLE URL", SAMPLE_URL)
	sample = fetch_json(SAMPLE_URL)
	data = sample.get("data") or {}
	print("SAMPLE keys", sorted(data))
	dump_structure("SAMPLE STRUCTURE", data.get("structure") or {})
	data_sets = data.get("dataSets") or []
	print("SAMPLE datasets", len(data_sets))
	if data_sets:
		series = data_sets[0].get("series") or {}
		print("SAMPLE series keys", list(series)[:10])
		for key in list(series)[:3]:
			observations = series[key].get("observations") or {}
			print("SERIES", key, "observations", len(observations))
			for observation_key in list(observations)[:3] + list(observations)[-3:]:
				print("  OBS", observation_key, observations[observation_key])


if __name__ == "__main__":
	main()
