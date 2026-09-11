#!/usr/bin/env python3
from __future__ import annotations

import json
from urllib.request import Request, urlopen

URL = "https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/UNICEF,WASH_HOUSEHOLDS,1.0/all?format=sdmx-json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def main() -> None:
	request = Request(URL, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
	with urlopen(request, timeout=120) as response:
		data = response.read()
	print(f"bytes={len(data)}")
	payload = json.loads(data)
	print(f"topKeys={list(payload)}")
	root = payload.get("data", payload)
	print(f"rootKeys={list(root) if isinstance(root, dict) else type(root).__name__}")
	structure = root.get("structure", {})
	dimensions = structure.get("dimensions", {})
	for level in ("dataSet", "series", "observation"):
		items = dimensions.get(level, [])
		print(f"DIMENSIONS {level} count={len(items)}")
		for item in items:
			values = item.get("values", [])
			print(f"  {item.get('id')}: values={len(values)} sample={[{'id': v.get('id'), 'name': v.get('name')} for v in values[:12]]}")

	datasets = root.get("dataSets", [])
	print(f"dataSets={len(datasets)}")
	if datasets:
		dataset = datasets[0]
		series = dataset.get("series", {})
		print(f"seriesCount={len(series)}")
		for key, value in list(series.items())[:8]:
			print(f"SERIES {key}: keys={list(value)} observationsSample={list(value.get('observations', {}).items())[:5]}")

	indicator_dim = next((item for item in dimensions.get("series", []) if item.get("id") == "INDICATOR"), None)
	if indicator_dim:
		print("INDICATORS")
		for value in indicator_dim.get("values", []):
			print(f"  {value.get('id')} = {value.get('name')}")

	for level in ("series", "observation"):
		time_dim = next((item for item in dimensions.get(level, []) if item.get("id") in ("TIME_PERIOD", "TIME")), None)
		if time_dim:
			values = time_dim.get("values", [])
			print(f"TIME {level}: {[value.get('id') for value in values]}")


if __name__ == "__main__":
	main()
