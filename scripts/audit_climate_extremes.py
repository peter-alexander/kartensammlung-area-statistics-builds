#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from urllib.request import Request, urlopen

USER_AGENT = "kartensammlung-area-statistics-builds/1"
OECD_STRUCTURE = "https://sdmx.oecd.org/public/rest/dataflow/OECD.ENV.EPI/DSD_ECH@EXT_TEMP_H/2.0?references=all"
SPEI_URL = "https://api.worldbank.org/v2/country/all/indicator/EN.CLC.SPEI.XD?format=json&per_page=20000&date=1960:2026"
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"


def fetch(url: str, accept: str) -> bytes:
	request = Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
	with urlopen(request, timeout=120) as response:
		payload = response.read()
	if not payload:
		raise RuntimeError(f"Empty response: {url}")
	return payload


def local_name(tag: str) -> str:
	return tag.rsplit("}", 1)[-1]


def text_name(node: ET.Element) -> str:
	for child in node.iter():
		if local_name(child.tag) == "Name" and (child.text or "").strip():
			return (child.text or "").strip()
	return ""


def audit_oecd() -> None:
	raw = fetch(OECD_STRUCTURE, "application/vnd.sdmx.structure+xml;version=2.1")
	print(f"OECD structure bytes={len(raw)}")
	root = ET.fromstring(raw)

	codelists: dict[tuple[str, str], dict[str, str]] = {}
	for node in root.iter():
		if local_name(node.tag) != "Codelist":
			continue
		codelist_id = node.attrib.get("id", "")
		agency = node.attrib.get("agencyID", "")
		if not codelist_id:
			continue
		codes: dict[str, str] = {}
		for code in node:
			if local_name(code.tag) != "Code":
				continue
			code_id = code.attrib.get("id", "")
			if code_id:
				codes[code_id] = text_name(code)
		codelists[(agency, codelist_id)] = codes

	structures = [node for node in root.iter() if local_name(node.tag) == "DataStructure"]
	print("OECD data structures=" + ", ".join(
		f"{node.attrib.get('agencyID', '')}:{node.attrib.get('id', '')}({node.attrib.get('version', '')})"
		for node in structures
	))
	candidates = [
		node for node in structures
		if node.attrib.get("id") in {"DSD_ECH", "DSD_ECH@EXT_TEMP_H"}
		or "ECH" in str(node.attrib.get("id", ""))
	]
	if len(candidates) != 1:
		raise RuntimeError(
			"Could not uniquely resolve OECD extreme-temperature data structure: "
			+ ", ".join(str(node.attrib.get("id", "")) for node in candidates)
		)
	structure = candidates[0]
	print(
		"OECD selected data structure="
		+ f"{structure.attrib.get('agencyID', '')}:{structure.attrib.get('id', '')}"
		+ f"({structure.attrib.get('version', '')})"
	)

	print("OECD dimensions:")
	for node in structure.iter():
		if local_name(node.tag) not in {"Dimension", "TimeDimension"}:
			continue
		dimension_id = node.attrib.get("id", "")
		position = node.attrib.get("position", "")
		if not dimension_id:
			continue
		refs = []
		for ref in node.iter():
			if local_name(ref.tag) != "Ref":
				continue
			ref_id = ref.attrib.get("id", "")
			ref_class = ref.attrib.get("class", "")
			ref_agency = ref.attrib.get("agencyID", "")
			if ref_id:
				refs.append((ref_agency, ref_id, ref_class))
		print(f"  pos={position} id={dimension_id} refs={refs}")
		for ref_agency, ref_id, ref_class in refs:
			if ref_class != "Codelist":
				continue
			codes = codelists.get((ref_agency, ref_id)) or codelists.get(("", ref_id))
			if not codes:
				matches = [value for (agency, cid), value in codelists.items() if cid == ref_id]
				codes = matches[0] if len(matches) == 1 else None
			if not codes:
				continue
			interesting = {
				code: label
				for code, label in codes.items()
				if any(term in label.lower() for term in (
					"hot day", "heat stress", "utci", "tropical night", "icing", "temperature",
					"day", "annual", "population-weighted", "area-weighted", "35", "32", "38", "46",
				))
			}
			if dimension_id in {"MEASURE", "UNIT_MEASURE", "FREQ", "DURATION", "HEAT_STRESS_THRESHOLD", "TEMPERATURE_THRESHOLD", "THRESHOLD"}:
				print(f"    codelist={ref_id} total={len(codes)}")
				for code, label in list(codes.items())[:80]:
					print(f"      {code}: {label}")
			elif interesting:
				print(f"    interesting codes in {ref_id}:")
				for code, label in interesting.items():
					print(f"      {code}: {label}")


def audit_spei() -> None:
	registry_raw = fetch(REGISTRY_URL, "application/json")
	registry = json.loads(registry_raw)
	areas = registry.get("areas") if isinstance(registry, dict) else registry
	if not isinstance(areas, list):
		raise RuntimeError("Unexpected registry schema")
	registry_iso3 = {}
	for area in areas:
		if not isinstance(area, dict):
			continue
		area_id = str(area.get("id") or "")
		iso3 = str(area.get("iso3") or "").upper()
		if area_id.startswith("country:") and iso3:
			registry_iso3[iso3] = area_id
	print(f"Registry ISO3 areas={len(registry_iso3)}")

	raw = fetch(SPEI_URL, "application/json")
	payload = json.loads(raw)
	if not isinstance(payload, list) or len(payload) != 2:
		raise RuntimeError("Unexpected World Bank SPEI response")
	meta, rows = payload
	print(f"SPEI API bytes={len(raw)} pages={meta.get('pages')} total={meta.get('total')}")
	by_year: dict[int, dict[str, float]] = defaultdict(dict)
	unmapped = set()
	for row in rows:
		country = row.get("country") or {}
		iso3 = str(country.get("id") or "").upper()
		year_text = str(row.get("date") or "")
		value = row.get("value")
		if len(iso3) != 3 or not year_text.isdigit() or value is None:
			continue
		area_id = registry_iso3.get(iso3)
		if area_id is None:
			unmapped.add(iso3)
			continue
		by_year[int(year_text)][area_id] = float(value)
	if not by_year:
		raise RuntimeError("No SPEI observations mapped")
	available_years = sorted(by_year)
	print(f"SPEI years={available_years[0]}-{available_years[-1]} yearCount={len(available_years)}")
	for year in available_years[-8:]:
		print(f"  SPEI {year}: coverage={len(by_year[year])}")
	all_areas = set().union(*(set(values) for values in by_year.values()))
	print(f"SPEI areasWithAnyValue={len(all_areas)} unmapped={sorted(unmapped)}")
	for iso3 in ("AUT", "DEU", "USA", "IND", "CHN", "ZAF", "NAM", "XKX"):
		area_id = registry_iso3.get(iso3)
		series = [(year, by_year[year][area_id]) for year in available_years if area_id in by_year[year]] if area_id else []
		print(f"  {iso3}: latest={series[-1] if series else None} count={len(series)}")


def main() -> None:
	audit_oecd()
	audit_spei()


if __name__ == "__main__":
	main()
