#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from urllib.request import Request, urlopen

import build_world_bank as common

USER_AGENT = "kartensammlung-area-statistics-builds/1"
OECD_STRUCTURE = "https://sdmx.oecd.org/public/rest/dataflow/OECD.ENV.EPI/DSD_ECH@EXT_TEMP_H/2.0?references=all"
OECD_DATA_BASE = "https://sdmx.oecd.org/public/rest/data/OECD.ENV.EPI,DSD_ECH@EXT_TEMP_H,2.0"
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


def iso3_list(area_ids: set[str]) -> list[str]:
	return sorted(area_id.split(":", 1)[1] for area_id in area_ids)


def audit_oecd_structure() -> set[str]:
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
	candidates = [node for node in structures if node.attrib.get("id") == "DSD_ECH"]
	if len(candidates) != 1:
		raise RuntimeError("Could not resolve OECD data structure DSD_ECH")
	structure = candidates[0]
	print(
		"OECD data structure="
		+ f"{structure.attrib.get('agencyID', '')}:{structure.attrib.get('id', '')}"
		+ f"({structure.attrib.get('version', '')})"
	)

	regional_codes: set[str] = set()
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
		print(f"  pos={position} id={dimension_id}")
		for ref_agency, ref_id, ref_class in refs:
			if ref_class != "Codelist":
				continue
			codes = codelists.get((ref_agency, ref_id))
			if not codes:
				matches = [value for (agency, cid), value in codelists.items() if cid == ref_id]
				codes = matches[0] if len(matches) == 1 else None
			if not codes:
				continue
			if dimension_id == "REF_AREA":
				regional_codes = set(codes)
			elif dimension_id == "MEASURE":
				for code in ("HD", "HD_POP_EXP", "HD_PW_EXP", "UTCI_PW_EXP", "TN", "TN_PW_EXP", "ID_PW_EXP"):
					if code in codes:
						print(f"    {code}: {codes[code]}")
			elif dimension_id == "TEMP_THRESHOLD":
				for code in ("H_20", "H_30", "H_32", "H_35", "H_38", "H_40", "H_46"):
					if code in codes:
						print(f"    {code}: {codes[code]}")
			elif dimension_id == "DURATION":
				for code, label in codes.items():
					print(f"    {code}: {label}")
	if not regional_codes:
		raise RuntimeError("OECD REF_AREA codelist could not be resolved")
	return regional_codes


def build_oecd_country_map(area_by_iso3: dict[str, str], regional_codes: set[str]) -> dict[str, str]:
	source_to_area: dict[str, str] = {}
	missing: list[str] = []
	for iso3, area_id in sorted(area_by_iso3.items()):
		source_code = "XKV" if iso3 == "XKX" else iso3
		if source_code in regional_codes:
			source_to_area[source_code] = area_id
		else:
			missing.append(iso3)
	print(f"OECD registry mapping={len(source_to_area)}/{len(area_by_iso3)} missing={missing}")
	return source_to_area


def audit_oecd_data(source_to_area: dict[str, str]) -> None:
	registry_areas = set(source_to_area.values())
	ref_areas = "+".join(sorted(source_to_area))
	queries = {
		"HD_PW_EXP": f"{OECD_DATA_BASE}/{ref_areas}.A.HD_PW_EXP...H_35......?startPeriod=1979&endPeriod=2024&dimensionAtObservation=AllDimensions",
		"UTCI_PW_EXP": f"{OECD_DATA_BASE}/{ref_areas}.A.UTCI_PW_EXP...H_32+H_38+H_46......?startPeriod=1979&endPeriod=2024&dimensionAtObservation=AllDimensions",
	}
	for measure, url in queries.items():
		raw = fetch(url, "text/csv")
		reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
		fields = set(reader.fieldnames or [])
		required = {"REF_AREA", "FREQ", "MEASURE", "UNIT_MEASURE", "DURATION", "TEMP_THRESHOLD", "TIME_PERIOD", "OBS_VALUE"}
		missing_fields = sorted(required - fields)
		if missing_fields:
			raise RuntimeError(f"OECD {measure} response missing fields: {missing_fields}")
		by_threshold: dict[str, dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
		units: set[str] = set()
		durations: set[str] = set()
		row_count = 0
		for row in reader:
			row_count += 1
			if str(row.get("FREQ") or "") != "A" or str(row.get("MEASURE") or "") != measure:
				raise RuntimeError(f"Unexpected OECD {measure} row dimensions")
			source_code = str(row.get("REF_AREA") or "").upper()
			area_id = source_to_area.get(source_code)
			threshold = str(row.get("TEMP_THRESHOLD") or "")
			year_text = str(row.get("TIME_PERIOD") or "")
			value_text = str(row.get("OBS_VALUE") or "")
			units.add(str(row.get("UNIT_MEASURE") or ""))
			durations.add(str(row.get("DURATION") or ""))
			if area_id is None or not year_text.isdigit() or not value_text:
				continue
			by_threshold[threshold][int(year_text)][area_id] = float(value_text)
		print(f"OECD {measure}: bytes={len(raw)} rows={row_count} units={sorted(units)} durations={sorted(durations)}")
		for threshold in sorted(by_threshold):
			by_year = by_threshold[threshold]
			years = sorted(by_year)
			all_areas = set().union(*(set(values) for values in by_year.values()))
			latest_areas = set(by_year[years[-1]])
			print(
				f"  threshold={threshold or '<blank>'} years={years[0]}-{years[-1]} "
				f"areasWithAny={len(all_areas)} latestCoverage={len(latest_areas)}"
			)
			print(f"    missingAny={iso3_list(registry_areas - all_areas)}")
			print(f"    missingLatest={iso3_list(registry_areas - latest_areas)}")
			for iso3 in ("AUT", "DEU", "USA", "IND", "CHN", "ZAF", "NAM", "XKX"):
				area_id = f"country:{iso3}"
				series = [(year, by_year[year][area_id]) for year in years if area_id in by_year[year]]
				print(f"    {iso3}: latest={series[-1] if series else None} count={len(series)}")


def audit_spei(area_by_iso3: dict[str, str]) -> None:
	registry_areas = set(area_by_iso3.values())
	raw = fetch(SPEI_URL, "application/json")
	payload = json.loads(raw)
	if not isinstance(payload, list) or len(payload) != 2:
		raise RuntimeError("Unexpected World Bank SPEI response")
	meta, rows = payload
	print(f"SPEI API bytes={len(raw)} pages={meta.get('pages')} total={meta.get('total')}")
	by_year: dict[int, dict[str, float]] = defaultdict(dict)
	unmapped: set[str] = set()
	for row in rows:
		iso3 = str(row.get("countryiso3code") or "").upper()
		year_text = str(row.get("date") or "")
		value = row.get("value")
		if len(iso3) != 3 or not year_text.isdigit() or value is None:
			continue
		area_id = area_by_iso3.get(iso3)
		if area_id is None:
			unmapped.add(iso3)
			continue
		by_year[int(year_text)][area_id] = float(value)
	if not by_year:
		raise RuntimeError("No SPEI observations mapped")

	available_years = sorted(by_year)
	all_areas = set().union(*(set(values) for values in by_year.values()))
	latest_areas = set(by_year[available_years[-1]])
	missing_any = registry_areas - all_areas
	print(f"SPEI years={available_years[0]}-{available_years[-1]} yearCount={len(available_years)}")
	print(f"SPEI areasWithAnyValue={len(all_areas)} unmapped={sorted(unmapped)}")
	print(f"SPEI missingAny={iso3_list(missing_any)}")
	print(f"SPEI missingLatest={iso3_list(registry_areas - latest_areas)}")

	coverage_groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
	for year in available_years:
		missing_year = tuple(iso3_list(registry_areas - set(by_year[year])))
		coverage_groups[missing_year].append(year)
	print(f"SPEI distinct yearly coverage patterns={len(coverage_groups)}")
	for missing_year, years in sorted(coverage_groups.items(), key=lambda item: (len(item[0]), item[1][0], item[0])):
		coverage = len(registry_areas) - len(missing_year)
		extra_missing = sorted(set(missing_year) - set(iso3_list(missing_any)))
		print(
			f"  coverage={coverage} years={years} extraMissingVsAny={extra_missing} "
			f"missing={list(missing_year)}"
		)

	for iso3 in ("AUT", "DEU", "USA", "IND", "CHN", "ZAF", "NAM", "VUT", "XKX"):
		area_id = area_by_iso3[iso3]
		series = [(year, by_year[year][area_id]) for year in available_years if area_id in by_year[year]]
		missing_years = [year for year in available_years if area_id not in by_year[year]]
		print(
			f"  {iso3}: latest={series[-1] if series else None} count={len(series)} "
			f"missingYears={missing_years}"
		)


def main() -> None:
	area_by_iso3, _ = common.load_registry(REGISTRY_URL, 120)
	print(f"Registry ISO3 areas={len(area_by_iso3)}")
	regional_codes = audit_oecd_structure()
	source_to_area = build_oecd_country_map(area_by_iso3, regional_codes)
	audit_oecd_data(source_to_area)
	audit_spei(area_by_iso3)


if __name__ == "__main__":
	main()
