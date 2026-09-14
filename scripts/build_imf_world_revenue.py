#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import math
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "imf-world-revenue-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"

ISO3_ALIASES = {
	"KOS": "XKX",
	"WBG": "PSE",
}

EXPECTED_SOURCE_INDICATORS = {
	"TotRev",
	"TaxRev",
	"TaxInc",
	"TaxIncI",
	"TaxIncC",
	"TaxPro",
	"TaxSal",
	"TaxSalG",
	"TaxSalExc",
	"TaxTra",
	"SocialCon",
	"Grants",
	"RevOth",
	"NonTaxRes",
}

EXCLUDED_RESIDUAL_COLUMNS = {
	"TaxIncO",
	"TaxSalUnal",
	"TaxOth",
	"NonTaxOth",
}

EXPECTED_WORKBOOK_COLUMNS = {
	"property_ShortForm_en_displayNam",
	"year",
	"property_IMFNumericCode_en_displ",
	"ISO3",
	"GDP_LCU",
	"TotRev",
	"TaxRev",
	"TaxInc",
	"TaxIncI",
	"TaxIncC",
	"TaxIncCRes",
	"TaxIncO",
	"TaxPro",
	"TaxSal",
	"TaxSalG",
	"TaxSalGI",
	"SalGType",
	"TaxSalExc",
	"TaxSalUnal",
	"TaxTra",
	"TaxOth",
	"SocialCon",
	"Grants",
	"RevOth",
	"NonTaxRes",
	"NonTaxOth",
	"check_TaxInc",
	"check_TaxRev",
	"check_TaxSal",
	"check_TotRev",
	"Incomegroup",
	"Region",
	"SmallIsland",
	"SmallIslandEMDE",
	"FuelExporting",
	"FuelExportingEMDE",
	"Landlocked",
	"LandlockedEMDE",
	"ResourceRich",
	"ResourceRichEMDE",
}

XML_NS = {
	"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
	"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build country revenue statistics from the IMF World Revenue Longitudinal Database (WoRLD)."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def validate_value_range(indicator_id: str, value_range: Any) -> None:
	if (
		not isinstance(value_range, list)
		or len(value_range) != 2
		or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in value_range)
		or not all(math.isfinite(float(value)) for value in value_range)
		or float(value_range[0]) >= float(value_range[1])
	):
		raise ValueError(f"IMF WoRLD indicator {indicator_id} has invalid valueRange.")


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.imf-world-revenue-statistics/v1":
		raise ValueError("Invalid IMF WoRLD statistics config.")
	for key in ("sourcePage", "workbookUrl", "technicalNoteUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"IMF WoRLD {key} must use HTTPS.")
	if str(payload.get("sourceRelease", "")) != "2026":
		raise ValueError("IMF WoRLD sourceRelease must remain the audited 2026 release.")
	if payload.get("latestYear") != 2024:
		raise ValueError("IMF WoRLD latestYear must remain 2024 for the 2026 release.")
	if not isinstance(payload.get("minimumWorkbookRows"), int) or int(payload["minimumWorkbookRows"]) < 8000:
		raise ValueError("IMF WoRLD minimumWorkbookRows is invalid.")
	if not isinstance(payload.get("minimumWorkbookCountries"), int) or int(payload["minimumWorkbookCountries"]) < 190:
		raise ValueError("IMF WoRLD minimumWorkbookCountries is invalid.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "imf-world-revenue":
		raise ValueError("IMF WoRLD provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"IMF WoRLD provider metadata is missing {key}.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != len(EXPECTED_SOURCE_INDICATORS):
		raise ValueError(f"IMF WoRLD config requires exactly {len(EXPECTED_SOURCE_INDICATORS)} indicators.")

	ids: set[str] = set()
	slugs: set[str] = set()
	source_indicators: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("IMF WoRLD indicator entries must be objects.")
		for key in ("id", "slug", "sourceIndicator", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"IMF WoRLD indicator entry is missing {key}.")
		indicator_id = str(indicator["id"])
		slug = str(indicator["slug"])
		source_indicator = str(indicator["sourceIndicator"])
		if indicator_id in ids:
			raise ValueError(f"Duplicate IMF WoRLD indicator id: {indicator_id}")
		if slug in slugs:
			raise ValueError(f"Duplicate IMF WoRLD indicator slug: {slug}")
		if source_indicator in source_indicators:
			raise ValueError(f"Duplicate IMF WoRLD source indicator: {source_indicator}")
		if source_indicator not in EXPECTED_SOURCE_INDICATORS:
			raise ValueError(f"Unexpected IMF WoRLD source indicator: {source_indicator}")
		if source_indicator in EXCLUDED_RESIDUAL_COLUMNS:
			raise ValueError(f"Residual IMF WoRLD field must not be published as direct data: {source_indicator}")
		ids.add(indicator_id)
		slugs.add(slug)
		source_indicators.add(source_indicator)

		unit = indicator.get("unit")
		if not isinstance(unit, dict) or unit.get("id") != "percent-of-gdp":
			raise ValueError(f"IMF WoRLD indicator {indicator_id} must use percent-of-gdp.")
		if not str(unit.get("label", "")).strip():
			raise ValueError(f"IMF WoRLD indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		validate_value_range(indicator_id, indicator.get("valueRange"))
		for key in ("minAreasWithAnyValue", "minAreasInDefaultYear"):
			value = indicator.get(key)
			if not isinstance(value, int) or value <= 0:
				raise ValueError(f"IMF WoRLD indicator {indicator_id} has invalid {key}.")
		required_areas = indicator.get("requiredAreas")
		if not isinstance(required_areas, list) or any(not str(area_id).startswith("country:") for area_id in required_areas):
			raise ValueError(f"IMF WoRLD indicator {indicator_id} has invalid requiredAreas.")

	if source_indicators != EXPECTED_SOURCE_INDICATORS:
		raise ValueError(
			"IMF WoRLD source indicator set changed: "
			f"missing={sorted(EXPECTED_SOURCE_INDICATORS - source_indicators)} "
			f"extra={sorted(source_indicators - EXPECTED_SOURCE_INDICATORS)}"
		)
	return payload


def fetch_workbook(url: str, timeout: int) -> tuple[bytes, dict[str, str]]:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 5, 15, 30), start=1):
		if delay:
			time.sleep(delay)
		request = Request(
			url,
			headers={
				"Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream,*/*",
				"User-Agent": USER_AGENT,
			},
		)
		try:
			with urlopen(request, timeout=timeout) as response:
				raw = response.read()
				headers = {key.lower(): value for key, value in response.headers.items()}
			if len(raw) < 1_000_000:
				raise RuntimeError(f"IMF WoRLD workbook unexpectedly small: {len(raw)} bytes.")
			if not zipfile.is_zipfile(BytesIO(raw)):
				raise RuntimeError("IMF WoRLD workbook is not a valid XLSX/ZIP file.")
			return raw, headers
		except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
			last_error = error
			print(f"IMF WoRLD download failed ({attempt}/4): {url}: {error}")
	if last_error is None:
		raise RuntimeError("IMF WoRLD workbook download failed without an exception.")
	raise RuntimeError("IMF WoRLD workbook download failed after 4 attempts.") from last_error


def column_index(cell_ref: str) -> int:
	match = re.match(r"[A-Z]+", cell_ref)
	if match is None:
		raise RuntimeError(f"Invalid XLSX cell reference: {cell_ref!r}")
	value = 0
	for letter in match.group(0):
		value = value * 26 + ord(letter) - ord("A") + 1
	return value - 1


def load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
	if "xl/sharedStrings.xml" not in archive.namelist():
		return []
	root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
	return [
		"".join(node.text or "" for node in item.iterfind(".//m:t", XML_NS))
		for item in root.findall("m:si", XML_NS)
	]


def xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
	cell_type = cell.attrib.get("t")
	if cell_type == "inlineStr":
		return "".join(node.text or "" for node in cell.iterfind(".//m:t", XML_NS))
	value_node = cell.find("m:v", XML_NS)
	value = "" if value_node is None else value_node.text or ""
	if cell_type == "s" and value:
		index = int(value)
		if index < 0 or index >= len(shared_strings):
			raise RuntimeError(f"Invalid XLSX shared-string index: {index}")
		return shared_strings[index]
	return value


def workbook_sheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
	workbook = ET.fromstring(archive.read("xl/workbook.xml"))
	relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
	rel_map = {relation.attrib["Id"]: relation.attrib["Target"] for relation in relationships}
	targets: dict[str, str] = {}
	for sheet in workbook.find("m:sheets", XML_NS) or []:
		name = str(sheet.attrib.get("name", "")).strip()
		relation_id = sheet.attrib.get(f"{{{XML_NS['r']}}}id")
		if not name or relation_id not in rel_map:
			continue
		target = rel_map[relation_id]
		if target.startswith("/"):
			target = target.lstrip("/")
		else:
			target = "xl/" + target.lstrip("/")
		targets[name] = target
	return targets


def read_sheet_rows(
	archive: zipfile.ZipFile,
	target: str,
	shared_strings: list[str],
) -> list[list[str]]:
	if target not in archive.namelist():
		raise RuntimeError(f"IMF WoRLD workbook sheet target is missing: {target}")
	root = ET.fromstring(archive.read(target))
	rows: list[list[str]] = []
	for row in root.findall(".//m:sheetData/m:row", XML_NS):
		values: list[str] = []
		for cell in row.findall("m:c", XML_NS):
			index = column_index(str(cell.attrib.get("r", "A1")))
			while len(values) <= index:
				values.append("")
			values[index] = xlsx_cell_value(cell, shared_strings)
		rows.append(values)
	return rows


def parse_workbook(raw: bytes, config: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
	with zipfile.ZipFile(BytesIO(raw)) as archive:
		shared_strings = load_shared_strings(archive)
		targets = workbook_sheet_targets(archive)
		for required_sheet in ("Summary", "Data"):
			if required_sheet not in targets:
				raise RuntimeError(f"IMF WoRLD workbook is missing sheet {required_sheet!r}.")
		summary_rows = read_sheet_rows(archive, targets["Summary"], shared_strings)
		data_rows = read_sheet_rows(archive, targets["Data"], shared_strings)

	if not data_rows:
		raise RuntimeError("IMF WoRLD workbook Data sheet is empty.")
	header = [str(value).strip() for value in data_rows[0]]
	if len(header) != len(set(header)):
		raise RuntimeError("IMF WoRLD workbook Data sheet contains duplicate column names.")
	missing_columns = sorted(EXPECTED_WORKBOOK_COLUMNS - set(header))
	if missing_columns:
		raise RuntimeError(f"IMF WoRLD workbook schema changed; missing columns: {missing_columns}")
	if len(data_rows) - 1 < int(config["minimumWorkbookRows"]):
		raise RuntimeError(
			f"IMF WoRLD workbook unexpectedly small: {len(data_rows) - 1} data rows, "
			f"expected at least {config['minimumWorkbookRows']}."
		)

	rows: list[dict[str, str]] = []
	for raw_row in data_rows[1:]:
		padded = raw_row + [""] * (len(header) - len(raw_row))
		rows.append({key: str(value).strip() for key, value in zip(header, padded)})

	summary_text = "\n".join(" | ".join(value for value in row if value) for row in summary_rows)
	if "2026 release" not in summary_text:
		raise RuntimeError("IMF WoRLD workbook Summary sheet does not identify the audited 2026 release.")

	iso3_codes = {
		row["ISO3"].strip().upper()
		for row in rows
		if len(row["ISO3"].strip()) == 3 and row["ISO3"].strip().isalpha()
	}
	if len(iso3_codes) < int(config["minimumWorkbookCountries"]):
		raise RuntimeError(
			f"IMF WoRLD workbook country coverage unexpectedly small: {len(iso3_codes)}, "
			f"expected at least {config['minimumWorkbookCountries']}."
		)

	years = {
		int(row["year"])
		for row in rows
		if row["year"].isdigit()
	}
	if not years or max(years) != int(config["latestYear"]):
		raise RuntimeError(
			f"IMF WoRLD workbook latest year changed: {max(years) if years else '(none)'}, "
			f"expected {config['latestYear']}."
		)
	if min(years) > 1980:
		raise RuntimeError(f"IMF WoRLD workbook history unexpectedly short: first year is {min(years)}.")

	metadata = {
		"sourceRows": len(rows),
		"sourceCountries": len(iso3_codes),
		"firstYear": min(years),
		"latestYear": max(years),
		"columns": header,
	}
	return rows, metadata


def mapped_iso3(source_code: str) -> str:
	code = source_code.strip().upper()
	return ISO3_ALIASES.get(code, code)


def normalize_values(
	config: dict[str, Any],
	rows: list[dict[str, str]],
	area_by_iso3: dict[str, str],
) -> tuple[
	dict[str, dict[int, dict[str, int | float]]],
	dict[str, set[str]],
	dict[str, int],
]:
	indicators = config["indicators"]
	values_by_indicator: dict[str, dict[int, dict[str, int | float]]] = {
		str(indicator["id"]): defaultdict(dict)
		for indicator in indicators
	}
	ignored_codes_by_indicator: dict[str, set[str]] = {
		str(indicator["id"]): set()
		for indicator in indicators
	}
	retained_rows_by_indicator = {str(indicator["id"]): 0 for indicator in indicators}
	latest_year = int(config["latestYear"])

	for row in rows:
		iso3_source = str(row.get("ISO3", "")).strip().upper()
		year_text = str(row.get("year", "")).strip()
		if len(iso3_source) != 3 or not iso3_source.isalpha() or not year_text.isdigit():
			continue
		year = int(year_text)
		if year < 1900 or year > latest_year:
			continue
		iso3 = mapped_iso3(iso3_source)
		area_id = area_by_iso3.get(iso3)
		for indicator in indicators:
			indicator_id = str(indicator["id"])
			source_indicator = str(indicator["sourceIndicator"])
			value_text = str(row.get(source_indicator, "")).strip()
			if not value_text:
				continue
			try:
				value = float(value_text)
			except ValueError as error:
				raise RuntimeError(
					f"Invalid IMF WoRLD numeric value: {source_indicator} {iso3_source} {year} {value_text!r}."
				) from error
			if not math.isfinite(value):
				raise RuntimeError(f"Non-finite IMF WoRLD value: {source_indicator} {iso3_source} {year}.")
			value_min, value_max = (float(item) for item in indicator["valueRange"])
			if value < value_min or value > value_max:
				raise RuntimeError(
					f"IMF WoRLD value outside configured range: {indicator_id} {iso3_source} {year} {value}."
				)
			if area_id is None:
				ignored_codes_by_indicator[indicator_id].add(iso3_source)
				continue
			year_values = values_by_indicator[indicator_id][year]
			if area_id in year_values:
				raise RuntimeError(f"Duplicate IMF WoRLD value for {indicator_id} {area_id} {year}.")
			year_values[area_id] = common.normalize_number(value_text)
			retained_rows_by_indicator[indicator_id] += 1

	return values_by_indicator, ignored_codes_by_indicator, retained_rows_by_indicator


def build_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	area_by_iso3: dict[str, str],
	values: dict[int, dict[str, int | float]],
	ignored_codes: set[str],
	retained_rows: int,
	workbook_sha256: str,
) -> dict[str, Any]:
	provider = config["provider"]
	indicator_id = str(indicator["id"])
	available_years = sorted(year for year, mapped in values.items() if mapped)
	if not available_years:
		raise RuntimeError(f"IMF WoRLD returned no mapped observations for {indicator_id}.")
	mapped_areas = {area_id for mapped in values.values() for area_id in mapped}
	if len(mapped_areas) < int(indicator["minAreasWithAnyValue"]):
		raise RuntimeError(
			f"IMF WoRLD coverage too small for {indicator_id}: {len(mapped_areas)} mapped countries, "
			f"expected at least {indicator['minAreasWithAnyValue']}."
		)

	default_year = int(config["latestYear"])
	if default_year not in values:
		raise RuntimeError(f"IMF WoRLD {indicator_id} has no values for default year {default_year}.")
	if len(values[default_year]) < int(indicator["minAreasInDefaultYear"]):
		raise RuntimeError(
			f"IMF WoRLD {indicator_id} default-year coverage too small: {len(values[default_year])}, "
			f"expected at least {indicator['minAreasInDefaultYear']}."
		)
	for area_id in indicator["requiredAreas"]:
		if area_id not in values[default_year]:
			raise RuntimeError(f"Required area {area_id} is missing from IMF WoRLD {indicator_id} in {default_year}.")

	latest_year = available_years[-1]
	if latest_year != default_year:
		raise RuntimeError(f"IMF WoRLD {indicator_id} latest year is {latest_year}, expected {default_year}.")

	sorted_values = {
		str(year): {
			area_id: values[year][area_id]
			for area_id in sorted(values[year])
		}
		for year in available_years
	}
	return {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": {
			"id": indicator_id,
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "annual",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		},
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"indicator": indicator["sourceIndicator"],
			"sourceRelease": config["sourceRelease"],
			"url": config["sourcePage"],
			"workbookUrl": config["workbookUrl"],
			"technicalNoteUrl": config["technicalNoteUrl"],
			"workbookSha256": workbook_sha256,
			"timeCoverage": {"startYear": available_years[0], "endYear": latest_year},
			"governmentCoverage": "General Government is preferred where available; Central Government or, in limited cases, Public Sector may be used depending on country data availability under IMF WoRLD methodology.",
			"taxConcept": "WoRLD follows the Government Finance Statistics Manual classification. TaxRev excludes social contributions, which are reported separately as SocialCon.",
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"ignoredAreaCodes": sorted(ignored_codes),
			"retainedRows": retained_rows,
		},
		"availableYears": available_years,
		"defaultYear": default_year,
		"coverage": {
			"registryAreas": len(area_by_iso3),
			"areasWithAnyValue": len(mapped_areas),
			"latestYear": latest_year,
			"areasInLatestYear": len(values[latest_year]),
			"areasInDefaultYear": len(values[default_year]),
			"observations": retained_rows,
		},
		"values": sorted_values,
	}


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("IMF WoRLD statistics is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	print(f"Fetching IMF WoRLD workbook from {config['workbookUrl']}")
	raw, response_headers = fetch_workbook(str(config["workbookUrl"]), args.timeout)
	workbook_sha256 = hashlib.sha256(raw).hexdigest()
	rows, workbook_metadata = parse_workbook(raw, config)
	print(
		f"IMF WoRLD workbook: bytes={len(raw)} rows={workbook_metadata['sourceRows']} "
		f"countries={workbook_metadata['sourceCountries']} years={workbook_metadata['firstYear']}-{workbook_metadata['latestYear']} "
		f"sha256={workbook_sha256}"
	)

	values_by_indicator, ignored_codes_by_indicator, retained_rows_by_indicator = normalize_values(
		config,
		rows,
		area_by_iso3,
	)
	payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		payload = build_payload(
			config,
			indicator,
			area_by_iso3,
			values_by_indicator[indicator_id],
			ignored_codes_by_indicator[indicator_id],
			retained_rows_by_indicator[indicator_id],
			workbook_sha256,
		)
		payloads.append((indicator, payload))
		coverage = payload["coverage"]
		print(
			f"{indicator_id}: observations={coverage['observations']} areas={coverage['areasWithAnyValue']} "
			f"years={payload['availableYears'][0]}-{payload['availableYears'][-1]} "
			f"defaultYear={payload['defaultYear']} defaultCoverage={coverage['areasInDefaultYear']} "
			f"ignored={payload['source']['ignoredAreaCodes'] or '(none)'}"
		)

	hasher = hashlib.sha256()
	hasher.update(str(config["sourceRelease"]).encode("utf-8"))
	hasher.update(b"\0")
	hasher.update(workbook_sha256.encode("ascii"))
	hasher.update(b"\0")
	for indicator, payload in payloads:
		hasher.update(str(indicator["id"]).encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(common.canonical_bytes(payload))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	now = datetime.now(timezone.utc)
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	index_indicators: list[dict[str, Any]] = []
	for indicator, payload in payloads:
		filename = f"{indicator['slug']}.json"
		common.write_json(release_dir / filename, payload)
		index_indicators.append(
			{
				"id": indicator["id"],
				"title": indicator["title"],
				"description": indicator["description"],
				"path": f"releases/{snapshot}/{filename}",
				"frequency": "annual",
				"unit": indicator["unit"],
				"classification": indicator["classification"],
				"availableYears": payload["availableYears"],
				"defaultYear": payload["defaultYear"],
				"coverage": payload["coverage"],
			}
		)

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_iso3),
	}
	if registry_source["url"] is None:
		registry_source.pop("url")

	all_ignored_codes = sorted({
		code
		for codes in ignored_codes_by_indicator.values()
		for code in codes
	})
	dataset = {
		"url": config["sourcePage"],
		"workbookUrl": config["workbookUrl"],
		"technicalNoteUrl": config["technicalNoteUrl"],
		"sourceRelease": config["sourceRelease"],
		"workbookSha256": workbook_sha256,
		"workbookBytes": len(raw),
		"sourceRows": workbook_metadata["sourceRows"],
		"sourceCountries": workbook_metadata["sourceCountries"],
		"firstYear": workbook_metadata["firstYear"],
		"latestYear": workbook_metadata["latestYear"],
		"ignoredAreaCodes": all_ignored_codes,
		"excludedResidualColumns": sorted(EXCLUDED_RESIDUAL_COLUMNS),
	}
	for header_name in ("last-modified", "etag"):
		if response_headers.get(header_name):
			dataset[header_name.replace("-", "").replace("modified", "Modified")] = response_headers[header_name]

	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"dataset": dataset,
		"indicators": index_indicators,
		"notes": [
			"The 2026 IMF WoRLD release covers 195 countries and extends through 2024.",
			"Government coverage follows IMF WoRLD methodology: General Government is preferred where available; Central Government or occasionally Public Sector may be used depending on country data availability.",
			"WoRLD TaxRev excludes social contributions. SocialCon is published separately and no OECD or World Bank series is used as a fallback because the tax concepts and government perimeter are not equivalent.",
			"Empty workbook cells remain missing. Numeric zero values are retained as observations.",
			"TaxIncO, TaxSalUnal, TaxOth and NonTaxOth are deliberately excluded because IMF documents them as residual rather than directly observed series.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"Built IMF WoRLD snapshot {snapshot}")
	print(f"Indicators: {len(index_indicators)}")


if __name__ == "__main__":
	main()
