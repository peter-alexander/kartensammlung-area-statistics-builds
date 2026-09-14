#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import math
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import build_world_bank as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "world-bank-esmap-solar-pv-indicators.json"
DEFAULT_PROVIDERS = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "statistics"
DEFAULT_REGISTRY = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")
ISO3_RE = re.compile(r"^[A-Z]{3}$")
MISSING_VALUES = {None, "", "#N/A"}
EXPECTED_INDICATORS = {
	"energy.solar-average-ghi": (11, 209),
	"energy.solar-pvout-level1": (12, 209),
	"energy.solar-lcoe-2018": (13, 209),
	"energy.solar-pv-seasonality-index": (14, 209),
	"energy.solar-pv-equivalent-area": (15, 135),
}
EXPECTED_PARTIAL_NOTES = {"up to parallel 45°S", "up to parallel 60°N"}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build static country solar/PV potential statistics from the World Bank/ESMAP 2020 study workbook."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument("--registry", default=DEFAULT_REGISTRY)
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def validate_iso3_list(name: str, value: Any) -> list[str]:
	if not isinstance(value, list) or any(not isinstance(item, str) or not ISO3_RE.fullmatch(item) for item in value):
		raise ValueError(f"{name} must be a list of uppercase ISO3 codes.")
	if value != sorted(set(value)):
		raise ValueError(f"{name} must be sorted and unique.")
	return value


def validate_value_range(indicator_id: str, value: Any) -> list[float]:
	if (
		not isinstance(value, list)
		or len(value) != 2
		or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
	):
		raise ValueError(f"Indicator {indicator_id} has invalid valueRange.")
	normalized = [float(item) for item in value]
	if not all(math.isfinite(item) for item in normalized) or normalized[0] >= normalized[1]:
		raise ValueError(f"Indicator {indicator_id} has invalid valueRange.")
	return normalized


def validate_config(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.world-bank-esmap-solar-pv-statistics/v1":
		raise ValueError("Invalid World Bank/ESMAP solar PV statistics config.")
	for key in ("sourceUrl", "dataUrl", "reportUrl", "licenseUrl"):
		if not str(payload.get(key, "")).startswith("https://"):
			raise ValueError(f"World Bank/ESMAP solar PV {key} must use HTTPS.")
	if payload.get("studyEdition") != "March 2020" or payload.get("snapshotYear") != 2020:
		raise ValueError("World Bank/ESMAP solar PV study edition must remain March 2020 / snapshotYear 2020.")
	if payload.get("sourceSheet") != "Country indicators" or payload.get("expectedSourceRows") != 209:
		raise ValueError("Unexpected World Bank/ESMAP solar PV source-sheet contract.")
	if payload.get("countryAliases") != {"XKO": "XKX"}:
		raise ValueError("World Bank/ESMAP solar PV aliases must remain {'XKO': 'XKX'}.")

	base_missing = validate_iso3_list("expectedMissingIso3", payload.get("expectedMissingIso3"))
	if len(base_missing) != 41 or 250 - len(base_missing) != 209:
		raise ValueError("World Bank/ESMAP solar PV base coverage must remain 209/250.")

	provider = payload.get("provider")
	if not isinstance(provider, dict) or provider.get("id") != "world-bank-esmap-solar-pv":
		raise ValueError("World Bank/ESMAP solar PV provider metadata is invalid.")
	for key in ("name", "dataset", "license", "licenseUrl", "attribution"):
		if not str(provider.get(key, "")).strip():
			raise ValueError(f"World Bank/ESMAP solar PV provider metadata is missing {key}.")
	if provider.get("license") != "CC BY 4.0":
		raise ValueError("World Bank/ESMAP solar PV license must remain CC BY 4.0.")

	indicators = payload.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != len(EXPECTED_INDICATORS):
		raise ValueError("World Bank/ESMAP solar PV requires exactly five indicators.")
	seen: set[str] = set()
	for indicator in indicators:
		if not isinstance(indicator, dict):
			raise ValueError("World Bank/ESMAP solar PV indicator must be an object.")
		for key in ("id", "slug", "sourceIndicator", "title", "description"):
			if not str(indicator.get(key, "")).strip():
				raise ValueError(f"World Bank/ESMAP solar PV indicator is missing {key}.")
		indicator_id = str(indicator["id"])
		if indicator_id in seen:
			raise ValueError(f"Duplicate World Bank/ESMAP solar PV indicator id: {indicator_id}")
		seen.add(indicator_id)
		expected = EXPECTED_INDICATORS.get(indicator_id)
		if expected is None or (indicator.get("sourceColumn"), indicator.get("expectedAreas")) != expected:
			raise ValueError(f"Unexpected source column/coverage for {indicator_id}.")
		unit = indicator.get("unit")
		if not isinstance(unit, dict) or not str(unit.get("id", "")).strip() or not str(unit.get("label", "")).strip():
			raise ValueError(f"Indicator {indicator_id} has invalid unit metadata.")
		common.validate_classification(indicator_id, indicator.get("classification"))
		validate_value_range(indicator_id, indicator.get("valueRange"))
		additional = validate_iso3_list(
			f"{indicator_id}.expectedAdditionalMissingIso3",
			indicator.get("expectedAdditionalMissingIso3"),
		)
		if set(additional) & set(base_missing):
			raise ValueError(f"Indicator {indicator_id} duplicates base-missing ISO3 codes.")
		if int(indicator["expectedAreas"]) != 250 - len(base_missing) - len(additional):
			raise ValueError(f"Indicator {indicator_id} expectedAreas does not match missing-code contract.")
		audit_values = indicator.get("auditValues")
		if not isinstance(audit_values, dict) or not audit_values:
			raise ValueError(f"Indicator {indicator_id} requires auditValues.")
		for area_id, value in audit_values.items():
			if not str(area_id).startswith("country:"):
				raise ValueError(f"Indicator {indicator_id} has invalid audit area {area_id!r}.")
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
				raise ValueError(f"Indicator {indicator_id} has invalid audit value for {area_id}.")
	if seen != set(EXPECTED_INDICATORS):
		raise ValueError("World Bank/ESMAP solar PV indicator set changed unexpectedly.")
	return payload


def fetch_bytes(url: str, timeout: int) -> tuple[bytes, dict[str, str], str]:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 3, 10, 20, 40), start=1):
		if delay:
			time.sleep(delay)
		request = Request(
			url,
			headers={
				"Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream;q=0.9,*/*;q=0.1",
				"User-Agent": USER_AGENT,
			},
		)
		try:
			with urlopen(request, timeout=timeout) as response:
				raw = response.read()
				headers = {key.lower(): value for key, value in response.headers.items()}
				effective_url = response.geturl()
			if not raw or not raw.startswith(b"PK"):
				raise RuntimeError("World Bank solar PV source did not return an XLSX/ZIP payload.")
			return raw, headers, effective_url
		except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
			last_error = error
			print(f"World Bank solar PV request failed ({attempt}/5): {url}: {error}")
	if last_error is None:
		raise RuntimeError("World Bank solar PV request failed without an exception.")
	raise RuntimeError("World Bank solar PV request failed after 5 attempts.") from last_error


def column_number(letters: str) -> int:
	value = 0
	for char in letters:
		value = value * 26 + ord(char) - ord("A") + 1
	return value


def load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
	name = "xl/sharedStrings.xml"
	if name not in archive.namelist():
		return []
	root = ET.fromstring(archive.read(name))
	strings: list[str] = []
	for item in root.findall(f"{{{NS_MAIN}}}si"):
		strings.append("".join(node.text or "" for node in item.iter(f"{{{NS_MAIN}}}t")))
	return strings


def workbook_sheets(archive: zipfile.ZipFile) -> dict[str, str]:
	workbook = ET.fromstring(archive.read("xl/workbook.xml"))
	rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
	targets = {
		rel.attrib["Id"]: rel.attrib["Target"]
		for rel in rels.findall(f"{{{NS_PKG_REL}}}Relationship")
	}
	sheets: dict[str, str] = {}
	for sheet in workbook.findall(f".//{{{NS_MAIN}}}sheet"):
		name = str(sheet.attrib.get("name", ""))
		rel_id = str(sheet.attrib.get(f"{{{NS_REL}}}id", ""))
		target = targets.get(rel_id, "")
		path = target.lstrip("/") if target.startswith("/") else "xl/" + target.lstrip("/")
		if name in sheets:
			raise RuntimeError(f"Duplicate workbook sheet name: {name!r}")
		sheets[name] = path
	return sheets


def cell_value(cell: ET.Element, shared_strings: list[str]) -> Any:
	cell_type = cell.attrib.get("t", "")
	if cell_type == "inlineStr":
		return "".join(node.text or "" for node in cell.iter(f"{{{NS_MAIN}}}t"))
	value_node = cell.find(f"{{{NS_MAIN}}}v")
	if value_node is None or value_node.text is None:
		return None
	text = value_node.text
	if cell_type == "s":
		return shared_strings[int(text)]
	if cell_type in {"str", "e"}:
		return text
	try:
		number = float(text)
	except ValueError:
		return text
	if math.isfinite(number) and number.is_integer():
		return int(number)
	return number


def read_sheet(archive: zipfile.ZipFile, path: str, shared_strings: list[str]) -> dict[int, dict[int, Any]]:
	root = ET.fromstring(archive.read(path))
	rows: dict[int, dict[int, Any]] = {}
	for row in root.findall(f".//{{{NS_MAIN}}}row"):
		row_number = int(row.attrib.get("r", "0") or 0)
		if row_number <= 0:
			continue
		values: dict[int, Any] = {}
		for cell in row.findall(f"{{{NS_MAIN}}}c"):
			match = CELL_RE.match(cell.attrib.get("r", ""))
			if match is None:
				continue
			value = cell_value(cell, shared_strings)
			if value not in (None, ""):
				values[column_number(match.group(1))] = value
		if values:
			rows[row_number] = values
	return rows


def normalize_header(value: Any) -> str:
	return " ".join(str(value or "").split())


def expected_missing_for_indicator(config: dict[str, Any], indicator: dict[str, Any]) -> list[str]:
	return sorted(set(config["expectedMissingIso3"]) | set(indicator["expectedAdditionalMissingIso3"]))


def load_source(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	timeout: int,
) -> tuple[dict[str, dict[str, int | float]], dict[str, Any]]:
	raw, headers, effective_url = fetch_bytes(str(config["dataUrl"]), timeout)
	workbook_sha256 = hashlib.sha256(raw).hexdigest()
	with zipfile.ZipFile(io.BytesIO(raw)) as archive:
		shared_strings = load_shared_strings(archive)
		sheets = workbook_sheets(archive)
		required_sheets = {"Country indicators", "Monthly data", "Summary statistics", "Glossary", "Data sources", "About"}
		if not required_sheets.issubset(sheets):
			raise RuntimeError(f"World Bank solar PV workbook sheets changed: {sorted(sheets)}")
		country_rows = read_sheet(archive, sheets[str(config["sourceSheet"])], shared_strings)
		about_rows = read_sheet(archive, sheets["About"], shared_strings)

	about_values = {
		normalize_header(value)
		for row in about_rows.values()
		for value in row.values()
	}
	if str(config["studyEdition"]) not in about_values:
		raise RuntimeError(f"World Bank solar PV workbook no longer declares {config['studyEdition']!r}.")

	expected_headers = {
		1: "ISO_A3",
		2: "Country or region",
		11: "Average theoretical potential (GHI, kWh/m2/day), long-term",
		12: "Average practical potential (PVOUT Level 1, kWh/kWp/day), long-term",
		13: "Average economic potential (LCOE, USD/kWh), 2018",
		14: "Average PV seasonality index, long-term",
		15: "PV equivalent area (% of total area), long-term",
	}
	for column, expected in expected_headers.items():
		actual = normalize_header(country_rows.get(2, {}).get(column))
		if actual != expected:
			raise RuntimeError(f"World Bank solar PV source header C{column} changed: {actual!r} != {expected!r}")

	data_rows: list[tuple[str, dict[int, Any]]] = []
	for values in country_rows.values():
		source_code = str(values.get(1, "")).strip().upper()
		if ISO3_RE.fullmatch(source_code):
			data_rows.append((source_code, values))
	if len(data_rows) != int(config["expectedSourceRows"]):
		raise RuntimeError(f"World Bank solar PV source-row count changed: {len(data_rows)}.")
	if len({source_code for source_code, _ in data_rows}) != len(data_rows):
		raise RuntimeError("World Bank solar PV source contains duplicate country codes.")

	aliases = dict(config["countryAliases"])
	mapped_rows: dict[str, dict[int, Any]] = {}
	unmapped_source: list[str] = []
	for source_code, values in data_rows:
		iso3 = aliases.get(source_code, source_code)
		area_id = area_by_iso3.get(iso3)
		if area_id is None:
			unmapped_source.append(source_code)
			continue
		if iso3 in mapped_rows:
			raise RuntimeError(f"Duplicate mapped World Bank solar PV ISO3 code: {iso3}")
		mapped_rows[iso3] = values
	if unmapped_source:
		raise RuntimeError(f"Unexpected unmapped World Bank solar PV source codes: {sorted(unmapped_source)}")
	missing_registry = sorted(set(area_by_iso3) - set(mapped_rows))
	if missing_registry != config["expectedMissingIso3"]:
		raise RuntimeError(f"World Bank solar PV country coverage changed: missing={missing_registry}")

	partial_notes: dict[str, str] = {}
	for iso3, values in mapped_rows.items():
		note = normalize_header(values.get(3))
		if not note:
			continue
		if note not in EXPECTED_PARTIAL_NOTES:
			raise RuntimeError(f"Unexpected World Bank solar PV source note for {iso3}: {note!r}")
		partial_notes[iso3] = note
	if len(partial_notes) != 7:
		raise RuntimeError(f"Expected 7 latitude-limited World Bank solar PV rows, got {partial_notes}.")

	values_by_indicator: dict[str, dict[str, int | float]] = {}
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		column = int(indicator["sourceColumn"])
		value_min, value_max = (float(item) for item in indicator["valueRange"])
		values: dict[str, int | float] = {}
		for iso3, row in mapped_rows.items():
			value = row.get(column)
			if value in MISSING_VALUES:
				continue
			if isinstance(value, bool) or not isinstance(value, (int, float)):
				raise RuntimeError(f"Unexpected World Bank solar PV value for {indicator_id} {iso3}: {value!r}")
			number = common.normalize_number(value)
			if not math.isfinite(float(number)) or float(number) < value_min or float(number) > value_max:
				raise RuntimeError(
					f"World Bank solar PV value outside {value_min}..{value_max}: {indicator_id} {iso3} {number}."
				)
			values[area_by_iso3[iso3]] = number

		expected_missing = expected_missing_for_indicator(config, indicator)
		actual_missing = sorted(iso3 for iso3, area_id in area_by_iso3.items() if area_id not in values)
		if len(values) != int(indicator["expectedAreas"]) or actual_missing != expected_missing:
			raise RuntimeError(
				f"World Bank solar PV coverage changed for {indicator_id}: {len(values)} areas, missing={actual_missing}."
			)
		for area_id, expected_value in indicator["auditValues"].items():
			actual = values.get(area_id)
			if actual is None or abs(float(actual) - float(expected_value)) > 1e-10:
				raise RuntimeError(
					f"World Bank solar PV regression changed for {indicator_id} {area_id}: {actual} != {expected_value}."
				)
		values_by_indicator[indicator_id] = values
		print(f"{indicator_id}: coverage={len(values)}/250 sourceColumn={column}")

	return values_by_indicator, {
		"sourceWorkbookBytes": len(raw),
		"sourceWorkbookSha256": workbook_sha256,
		"sourceContentType": headers.get("content-type"),
		"sourceLastModified": headers.get("last-modified"),
		"sourceEtag": headers.get("etag"),
		"effectiveDataUrl": effective_url,
		"sourceRows": len(data_rows),
		"mappedAreas": len(mapped_rows),
		"expectedMissingIso3": missing_registry,
		"partialCoverageNotes": {iso3: partial_notes[iso3] for iso3 in sorted(partial_notes)},
	}


def build_payload(
	config: dict[str, Any],
	indicator: dict[str, Any],
	values: dict[str, int | float],
	diagnostics: dict[str, Any],
	registry_area_count: int,
) -> dict[str, Any]:
	provider = config["provider"]
	snapshot_year = int(config["snapshotYear"])
	return {
		"schema": "kartensammlung.statistics-indicator/v1",
		"indicator": {
			"id": indicator["id"],
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "snapshot",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
		},
		"source": {
			"providerId": provider["id"],
			"providerName": provider["name"],
			"dataset": provider["dataset"],
			"indicator": indicator["sourceIndicator"],
			"sourceColumn": indicator["sourceColumn"],
			"license": provider["license"],
			"licenseUrl": provider["licenseUrl"],
			"attribution": provider["attribution"],
			"url": config["sourceUrl"],
			"dataUrl": config["dataUrl"],
			"reportUrl": config["reportUrl"],
			"studyEdition": config["studyEdition"],
			"snapshotYear": snapshot_year,
			"sourceWorkbookSha256": diagnostics["sourceWorkbookSha256"],
			"countryAliases": config["countryAliases"],
			"expectedMissingIso3": expected_missing_for_indicator(config, indicator),
			"partialCoverageNotes": diagnostics["partialCoverageNotes"],
		},
		"availableYears": [snapshot_year],
		"defaultYear": snapshot_year,
		"coverage": {
			"registryAreas": registry_area_count,
			"areasWithAnyValue": len(values),
			"latestYear": snapshot_year,
			"areasInLatestYear": len(values),
			"areasInDefaultYear": len(values),
			"observations": len(values),
		},
		"values": {
			str(snapshot_year): {area_id: values[area_id] for area_id in sorted(values)},
		},
	}


def main() -> None:
	args = parse_args()
	config = validate_config(common.read_json_path(args.config))
	provider_catalog = common.validate_provider_catalog(common.read_json_path(args.providers))
	provider = config["provider"]
	if not any(item["id"] == provider["id"] for item in provider_catalog["providers"]):
		raise RuntimeError("World Bank/ESMAP solar PV is missing from statistics-providers.json.")

	area_by_iso3, registry_payload = common.load_registry(args.registry, args.timeout)
	if len(area_by_iso3) != 250:
		raise RuntimeError(f"World Bank/ESMAP solar PV requires the audited 250-area registry, got {len(area_by_iso3)}.")

	print("Fetching World Bank/ESMAP Global Photovoltaic Power Potential country workbook")
	values_by_indicator, diagnostics = load_source(config, area_by_iso3, args.timeout)
	payloads: dict[str, dict[str, Any]] = {}
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		payloads[indicator_id] = build_payload(
			config,
			indicator,
			values_by_indicator[indicator_id],
			diagnostics,
			len(area_by_iso3),
		)

	hasher = hashlib.sha256()
	for indicator_id in sorted(payloads):
		hasher.update(indicator_id.encode("utf-8"))
		hasher.update(b"\0")
		hasher.update(common.canonical_bytes(payloads[indicator_id]))
		hasher.update(b"\0")
	snapshot = hasher.hexdigest()[:16]

	now = datetime.now(timezone.utc)
	provider_dir = args.output_dir / provider["id"]
	release_dir = provider_dir / "releases" / snapshot
	indicator_index: list[dict[str, Any]] = []
	for indicator in config["indicators"]:
		indicator_id = str(indicator["id"])
		payload = payloads[indicator_id]
		filename = f"{indicator['slug']}.json"
		common.write_json(release_dir / filename, payload)
		indicator_index.append({
			"id": indicator_id,
			"title": indicator["title"],
			"description": indicator["description"],
			"areaLevel": "country",
			"frequency": "snapshot",
			"unit": indicator["unit"],
			"classification": indicator["classification"],
			"sourceIndicator": indicator["sourceIndicator"],
			"sourceColumn": indicator["sourceColumn"],
			"path": f"releases/{snapshot}/{filename}",
			"availableYears": payload["availableYears"],
			"defaultYear": payload["defaultYear"],
			"coverage": payload["coverage"],
		})

	registry_source = {
		"url": args.registry if args.registry.startswith(("https://", "http://")) else None,
		"schema": registry_payload.get("schema"),
		"generatedAt": registry_payload.get("generatedAt"),
		"areaCount": len(area_by_iso3),
	}
	if registry_source["url"] is None:
		registry_source.pop("url")

	provider_index = {
		"schema": "kartensammlung.statistics-provider-index/v1",
		"provider": provider,
		"retrievedAt": now.isoformat().replace("+00:00", "Z"),
		"activeSnapshot": snapshot,
		"areaRegistry": registry_source,
		"dataset": {
			"url": config["sourceUrl"],
			"dataUrl": config["dataUrl"],
			"effectiveDataUrl": diagnostics["effectiveDataUrl"],
			"reportUrl": config["reportUrl"],
			"studyEdition": config["studyEdition"],
			"snapshotYear": config["snapshotYear"],
			"sourceSheet": config["sourceSheet"],
			"sourceWorkbookBytes": diagnostics["sourceWorkbookBytes"],
			"sourceWorkbookSha256": diagnostics["sourceWorkbookSha256"],
			"sourceContentType": diagnostics["sourceContentType"],
			"sourceLastModified": diagnostics["sourceLastModified"],
			"sourceEtag": diagnostics["sourceEtag"],
			"sourceRows": diagnostics["sourceRows"],
			"mappedAreas": diagnostics["mappedAreas"],
			"countryAliases": config["countryAliases"],
			"expectedMissingIso3": diagnostics["expectedMissingIso3"],
			"partialCoverageNotes": diagnostics["partialCoverageNotes"],
		},
		"indicators": indicator_index,
		"notes": [
			"Static March 2020 study snapshot; the long-term GHI, PVOUT and seasonality values are not annual observations even though 2020 is used as the UI snapshot year.",
			"GHI is long-term global horizontal irradiance. PVOUT Level 1 is long-term specific PV yield for utility-scale, monofacial, fixed-mounted modules at optimum tilt, excluding land with identifiable physical obstacles.",
			"LCOE is the study's 2018 economic-potential estimate and is not inflation- or technology-cost-adjusted to later years.",
			"PV equivalent area is the modeled share of national area needed to produce electricity equivalent to the study-era annual electricity consumption; the source publishes this field for only 135 registry areas.",
			"Seven source rows explicitly limit the evaluated country area by latitude (45°S or 60°N). Those source limitations are preserved in dataset.partialCoverageNotes and no geographic correction is applied.",
			"No interpolation, territorial synthesis, raster re-aggregation or cross-provider fallback is used. Missing source values remain missing.",
			"The World Bank Data Catalog classifies the dataset as Public and licenses it under Creative Commons Attribution 4.0; Solargis prepared the country indicators under contract to the World Bank Group/ESMAP.",
		],
	}
	common.write_json(provider_dir / "index.json", provider_index)
	common.write_json(args.output_dir / "index.json", common.build_global_index(provider_catalog))
	print(f"sourceWorkbookSha256={diagnostics['sourceWorkbookSha256']}")
	print(f"partialCoverageNotes={diagnostics['partialCoverageNotes']}")
	print(f"Built World Bank/ESMAP solar PV snapshot {snapshot}")
	print(f"Indicators: {len(indicator_index)}")


if __name__ == "__main__":
	main()
