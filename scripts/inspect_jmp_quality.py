#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
import json
from urllib.request import Request, urlopen

URL = "https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/UNICEF,WASH_HOUSEHOLDS,1.0/all?format=sdmx-json"
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
SELECTED = {
	"WS_PPL_W-PRE",
	"WS_PPL_W-AVA",
	"WS_PPL_W-QUA",
	"WS_PPL_S-SEW",
	"WS_PPL_S-WWT",
	"WS_PPL_S-SEP",
	"WS_PPL_S-FST",
	"WS_PPL_S-DIS",
}


def fetch_json(url: str) -> dict:
	request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
	with urlopen(request, timeout=120) as response:
		return json.load(response)


def main() -> None:
	payload = fetch_json(URL)
	root = payload.get("data", payload)
	structure = root["structure"]
	series_dims = structure["dimensions"]["series"]
	obs_dims = structure["dimensions"]["observation"]
	all_dims = series_dims + obs_dims
	values = {
		item["id"]: [str(value.get("id", "")) for value in item.get("values", [])]
		for item in all_dims
	}
	names = {
		item["id"]: {
			str(value.get("id", "")): str(value.get("name", ""))
			for value in item.get("values", [])
		}
		for item in all_dims
	}
	registry = fetch_json(REGISTRY_URL)
	area_by_iso3 = {
		str(area.get("codes", {}).get("iso3", "")).strip().upper(): str(area.get("area_id", "")).strip()
		for area in registry.get("areas", [])
		if isinstance(area, dict) and area.get("level") == "country" and isinstance(area.get("codes"), dict)
	}
	area_by_iso3 = {iso3: area_id for iso3, area_id in area_by_iso3.items() if len(iso3) == 3 and area_id}

	coverage: dict[str, dict[int, set[str]]] = {indicator: defaultdict(set) for indicator in SELECTED}
	mapped_any: dict[str, set[str]] = defaultdict(set)
	services: dict[str, set[str]] = defaultdict(set)
	series = root["dataSets"][0]["series"]
	for series_key, series_payload in series.items():
		indices = [int(part) for part in series_key.split(":")]
		series_values = {
			series_dims[position]["id"]: values[series_dims[position]["id"]][value_index]
			for position, value_index in enumerate(indices)
		}
		indicator = series_values.get("INDICATOR", "")
		if indicator not in SELECTED:
			continue
		if series_values.get("WEALTH_QUINTILE") != "_T" or series_values.get("RESIDENCE") != "_T":
			continue
		iso3 = series_values.get("REF_AREA", "").upper()
		if iso3 not in area_by_iso3:
			continue
		area_id = area_by_iso3[iso3]
		mapped_any[indicator].add(area_id)
		services[indicator].add(series_values.get("SERVICE_TYPE", ""))
		for time_index, observation in series_payload.get("observations", {}).items():
			if not isinstance(observation, list) or not observation or observation[0] in (None, ""):
				continue
			year = int(values["TIME_PERIOD"][int(time_index)])
			coverage[indicator][year].add(area_id)

	for indicator in sorted(SELECTED):
		years = sorted(coverage[indicator])
		print(f"{indicator} = {names['INDICATOR'].get(indicator)}")
		if not years:
			print("  NONE")
			continue
		latest = years[-1]
		best = max(years, key=lambda year: (len(coverage[indicator][year]), year))
		print(
			f"  services={sorted(services[indicator])} mapped={len(mapped_any[indicator])} "
			f"years={years[0]}-{latest} latest={latest}/{len(coverage[indicator][latest])} "
			f"best={best}/{len(coverage[indicator][best])}"
		)


if __name__ == "__main__":
	main()
