#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
from urllib.request import Request, urlopen

WID_COUNTRIES_URL = "https://wid.world/bulk_download/WID_countries.csv"
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-wid-source-audit/1"


def fetch_bytes(url: str) -> bytes:
	request = Request(url, headers={"User-Agent": USER_AGENT})
	with urlopen(request, timeout=90) as response:
		return response.read()


def main() -> None:
	wid_raw = fetch_bytes(WID_COUNTRIES_URL)
	wid_rows = list(csv.DictReader(io.StringIO(wid_raw.decode("utf-8-sig")), delimiter=";"))
	wid_by_iso2 = {
		str(row["alpha2"]).strip().upper(): row
		for row in wid_rows
		if str(row.get("alpha2", "")).strip()
	}
	if len(wid_by_iso2) != len(wid_rows):
		raise RuntimeError("WID country list contains duplicate or blank alpha2 codes.")

	registry = json.loads(fetch_bytes(REGISTRY_URL))
	if registry.get("schema") != "kartensammlung.area-registry/v1":
		raise RuntimeError(f"Unexpected registry schema: {registry.get('schema')!r}")
	registry_by_iso2 = {}
	for area in registry["areas"]:
		if area.get("level") != "country":
			continue
		iso2 = str(area.get("codes", {}).get("iso2", "")).strip().upper()
		if not iso2:
			raise RuntimeError(f"Registry country lacks ISO2: {area.get('area_id')}")
		if iso2 in registry_by_iso2:
			raise RuntimeError(f"Duplicate registry ISO2: {iso2}")
		registry_by_iso2[iso2] = area

	wid_codes = set(wid_by_iso2)
	registry_codes = set(registry_by_iso2)
	overlap = wid_codes & registry_codes
	wid_only = sorted(wid_codes - registry_codes)
	registry_only = sorted(registry_codes - wid_codes)

	print(f"widCountries={len(wid_codes)}")
	print(f"registryCountries={len(registry_codes)}")
	print(f"overlap={len(overlap)}")
	print(f"widOnly={len(wid_only)}")
	for iso2 in wid_only:
		row = wid_by_iso2[iso2]
		print(f"WID_ONLY {iso2} name={row.get('shortname')} region={row.get('region')} region2={row.get('region2')}")
	print(f"registryOnly={len(registry_only)}")
	for iso2 in registry_only:
		area = registry_by_iso2[iso2]
		print(
			f"REGISTRY_ONLY {iso2} area={area['area_id']} name={area['name'].get('default')} "
			f"iso3={area['codes'].get('iso3')}"
		)

	for iso2 in ("AT", "DE", "US", "FR", "BR", "ZA", "IN", "CN", "TW", "HK", "MO", "PS", "XK"):
		print(
			f"CHECK {iso2} wid={'yes' if iso2 in wid_codes else 'no'} "
			f"registry={'yes' if iso2 in registry_codes else 'no'}"
		)


if __name__ == "__main__":
	main()
