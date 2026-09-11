#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
import json
from urllib.request import Request, urlopen

URL = "https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/UNICEF,WASH_HOUSEHOLDS,1.0/all?format=sdmx-json"
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
SELECTED = {
	"WS_PPL_W-ALB",
	"WS_PPL_W-SM",
	"WS_PPL_W-B",
	"WS_PPL_W-L",
	"WS_PPL_W-UI",
	"WS_PPL_W-SW",
	"WS_PPL_S-ALB",
	"WS_PPL_S-SM",
	"WS_PPL_S-B",
	"WS_PPL_S-L",
	"WS_PPL_S-UI",
	"WS_PPL_S-OD",
	"WS_PPL_H-B",
	"WS_PPL_H-L",
	"WS_PPL_H-N",
}


def fetch_json(url: str) -> dict:
	request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
	with urlopen(request, timeout=120) as response:
		return json.load(response)


def main() -> None:
	request = Request(URL, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
	with urlopen(request, timeout=120) as response:
		data = response.read()
	print(f"bytes={len(data)}")
	payload = json.loads(data)
	root = payload.get("data", payload)
	structure = root.get("structure", {})
	dimensions = structure.get("dimensions", {})
	series_dims = dimensions.get("series", [])
	obs_dims = dimensions.get("observation", [])
	print(f"seriesDimensions={[item.get('id') for item in series_dims]}")
	print(f"observationDimensions={[item.get('id') for item in obs_dims]}")

	value_maps: dict[str, list[str]] = {}
	name_maps: dict[str, dict[str, str]] = {}
	for item in series_dims + obs_dims:
		values = item.get("values", [])
		value_maps[item["id"]] = [str(value.get("id", "")) for value in values]
		name_maps[item["id"]] = {
			str(value.get("id", "")): str(value.get("name", ""))
			for value in values
		}

	print("INDICATORS")
	for indicator in value_maps.get("INDICATOR", []):
		print(f"  {indicator} = {name_maps['INDICATOR'].get(indicator)}")
	print(f"TIME={value_maps.get('TIME_PERIOD', [])}")

	registry = fetch_json(REGISTRY_URL)
	area_by_iso3 = {
		str(area.get("codes", {}).get("iso3", "")).strip().upper(): str(area.get("area_id", "")).strip()
		for area in registry.get("areas", [])
		if isinstance(area, dict) and area.get("level") == "country" and isinstance(area.get("codes"), dict)
	}
	area_by_iso3 = {iso3: area_id for iso3, area_id in area_by_iso3.items() if len(iso3) == 3 and area_id}
	print(f"registryCountries={len(area_by_iso3)}")

	coverage: dict[str, dict[int, set[str]]] = {
		indicator: defaultdict(set)
		for indicator in SELECTED
	}
	services: dict[str, set[str]] = defaultdict(set)
	mapped_any: dict[str, set[str]] = defaultdict(set)
	series = root.get("dataSets", [{}])[0].get("series", {})
	for series_key, series_payload in series.items():
		indices = [int(part) for part in series_key.split(":")]
		if len(indices) != len(series_dims):
			continue
		series_values = {
			series_dims[index]["id"]: value_maps[series_dims[index]["id"]][value_index]
			for index, value_index in enumerate(indices)
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
		services[indicator].add(series_values.get("SERVICE_TYPE", ""))
		mapped_any[indicator].add(area_id)
		for time_index, observation in series_payload.get("observations", {}).items():
			if not isinstance(observation, list) or not observation or observation[0] in (None, ""):
				continue
			year = int(value_maps["TIME_PERIOD"][int(time_index)])
			coverage[indicator][year].add(area_id)

	for indicator in sorted(SELECTED):
		years = sorted(coverage[indicator])
		if not years:
			print(f"COVERAGE {indicator}: NONE")
			continue
		best_year = max(years, key=lambda year: (len(coverage[indicator][year]), year))
		latest_year = years[-1]
		print(
			f"COVERAGE {indicator}: services={sorted(services[indicator])} "
			f"mapped={len(mapped_any[indicator])} years={years[0]}-{latest_year} "
			f"latest={latest_year}/{len(coverage[indicator][latest_year])} "
			f"best={best_year}/{len(coverage[indicator][best_year])}"
		)


if __name__ == "__main__":
	main()
