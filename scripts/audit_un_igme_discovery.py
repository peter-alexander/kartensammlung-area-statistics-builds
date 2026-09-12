#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

URL = (
	"https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/"
	"UNICEF,GLOBAL_DATAFLOW,1.0/all?format=sdmx-json&detail=structureOnly"
)


def fetch_json(url: str) -> Any:
	request = Request(url, headers={"Accept": "application/json", "User-Agent": "kartensammlung-area-statistics-builds/1"})
	with urlopen(request, timeout=120) as response:
		return json.load(response)


def walk(value: Any, path: tuple[str, ...] = ()):
	if isinstance(value, dict):
		yield path, value
		for key, child in value.items():
			yield from walk(child, path + (str(key),))
	elif isinstance(value, list):
		for index, child in enumerate(value):
			yield from walk(child, path + (str(index),))


def main() -> None:
	payload = fetch_json(URL)
	print("top-level:", sorted(payload) if isinstance(payload, dict) else type(payload).__name__)
	matches = 0
	for path, node in walk(payload):
		values = node.get("values")
		if not isinstance(values, list):
			continue
		node_id = str(node.get("id") or "")
		node_name = str(node.get("name") or "")
		selected = []
		for item in values:
			if not isinstance(item, dict):
				continue
			item_id = str(item.get("id") or "")
			item_name = str(item.get("name") or "")
			text = f"{item_id} {item_name}".lower()
			if item_id.startswith("CME_") or "mortality" in text or "under-five" in text or "under five" in text or "neonatal" in text or "infant" in text:
				selected.append((item_id, item_name))
		if selected:
			matches += 1
			print(f"DIMENSION path={'/'.join(path)} id={node_id!r} name={node_name!r} selected={len(selected)} total={len(values)}")
			for item_id, item_name in selected:
				print(f"  {item_id}\t{item_name}")
	if matches == 0:
		raise RuntimeError("No child mortality indicator codes found in UNICEF GLOBAL_DATAFLOW structure.")


if __name__ == "__main__":
	main()
