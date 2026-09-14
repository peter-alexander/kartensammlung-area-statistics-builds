#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import math
import re
import statistics
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any
from urllib.request import Request, urlopen

import build_world_bank as common

SOURCE_URL = (
	"https://datacatalogfiles.worldbank.org/ddh-published/0038379/1/DR0046831/"
	"solargis_pvpotential_countryranking_2020_data.xlsx"
)
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")
ISO3_RE = re.compile(r"^[A-Z]{3}$")
ALIASES = {"XKO": "XKX"}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Audit the World Bank/ESMAP Global PV Potential country spreadsheet.")
	parser.add_argument("--timeout", type=int, default=120)
	return parser.parse_args()


def fetch_bytes(url: str, timeout: int) -> tuple[bytes, dict[str, str]]:
	request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"})
	with urlopen(request, timeout=timeout) as response:
		raw = response.read()
		headers = {key.lower(): value for key, value in response.headers.items()}
	if not raw:
		raise RuntimeError(f"Empty response: {url}")
	return raw, headers


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
		parts = [node.text or "" for node in item.iter(f"{{{NS_MAIN}}}t")]
		strings.append("".join(parts))
	return strings


def workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
	workbook = ET.fromstring(archive.read("xl/workbook.xml"))
	rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
	targets = {
		rel.attrib["Id"]: rel.attrib["Target"]
		for rel in rels.findall(f"{{{NS_PKG_REL}}}Relationship")
	}
	sheets: list[tuple[str, str]] = []
	for sheet in workbook.findall(f".//{{{NS_MAIN}}}sheet"):
		name = sheet.attrib.get("name", "")
		rel_id = sheet.attrib.get(f"{{{NS_REL}}}id", "")
		target = targets.get(rel_id, "")
		if target.startswith("/"):
			path = target.lstrip("/")
		else:
			path = "xl/" + target.lstrip("/")
		sheets.append((name, path))
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
			ref = cell.attrib.get("r", "")
			match = CELL_RE.match(ref)
			if match is None:
				continue
			column = column_number(match.group(1))
			value = cell_value(cell, shared_strings)
			if value not in (None, ""):
				values[column] = value
		if values:
			rows[row_number] = values
	return rows


def print_grid(rows: dict[int, dict[int, Any]], first_row: int, last_row: int, max_column: int) -> None:
	for row_number in range(first_row, last_row + 1):
		values = rows.get(row_number, {})
		parts: list[str] = []
		for column in range(1, max_column + 1):
			if column not in values:
				continue
			text = str(values[column]).replace("\n", " / ").strip()
			if len(text) > 180:
				text = text[:177] + "..."
			parts.append(f"C{column}={text!r}")
		print(f"ROW {row_number}: " + (" | ".join(parts) if parts else "<empty>"))


def numeric_summary(values: list[float]) -> str:
	ordered = sorted(values)
	if not ordered:
		return "no numeric values"

	def percentile(fraction: float) -> float:
		if len(ordered) == 1:
			return ordered[0]
		position = (len(ordered) - 1) * fraction
		lower = int(math.floor(position))
		upper = int(math.ceil(position))
		if lower == upper:
			return ordered[lower]
		weight = position - lower
		return ordered[lower] * (1 - weight) + ordered[upper] * weight

	return (
		f"n={len(ordered)} min={ordered[0]:.6g} p05={percentile(0.05):.6g} "
		f"p25={percentile(0.25):.6g} median={statistics.median(ordered):.6g} "
		f"p75={percentile(0.75):.6g} p95={percentile(0.95):.6g} max={ordered[-1]:.6g}"
	)


def main() -> None:
	args = parse_args()
	area_by_iso3, _ = common.load_registry(REGISTRY_URL, args.timeout)
	if len(area_by_iso3) != 250:
		raise RuntimeError(f"Expected 250 registry ISO3 areas, got {len(area_by_iso3)}.")

	raw, headers = fetch_bytes(SOURCE_URL, args.timeout)
	print(f"sourceUrl={SOURCE_URL}")
	print(f"sourceBytes={len(raw)}")
	print(f"contentType={headers.get('content-type')}")
	print(f"lastModified={headers.get('last-modified')}")
	print(f"etag={headers.get('etag')}")

	with zipfile.ZipFile(io.BytesIO(raw)) as archive:
		shared_strings = load_shared_strings(archive)
		sheets = workbook_sheets(archive)
		print(f"sheets={sheets}")
		print(f"sharedStrings={len(shared_strings)}")
		if not sheets:
			raise RuntimeError("Workbook contains no sheets.")

		all_sheet_rows: list[tuple[str, dict[int, dict[int, Any]]]] = []
		for sheet_name, path in sheets:
			rows = read_sheet(archive, path, shared_strings)
			all_sheet_rows.append((sheet_name, rows))
			max_row = max(rows, default=0)
			max_col = max((max(row) for row in rows.values()), default=0)
			print(f"SHEET {sheet_name!r}: path={path} nonemptyRows={len(rows)} maxRow={max_row} maxColumn={max_col}")
			print_grid(rows, 1, min(max_row, 18), min(max_col, 45))

	country_sheet_name = ""
	country_rows: dict[int, dict[int, Any]] | None = None
	best_code_count = -1
	best_code_column = -1
	for sheet_name, rows in all_sheet_rows:
		for column in range(1, 16):
			count = 0
			for values in rows.values():
				value = str(values.get(column, "")).strip().upper()
				if ISO3_RE.match(value):
					count += 1
			if count > best_code_count:
				best_code_count = count
				best_code_column = column
				country_sheet_name = sheet_name
				country_rows = rows

	if country_rows is None or best_code_count < 100:
		raise RuntimeError(f"Could not identify country data sheet/code column; best count={best_code_count}.")
	print(
		f"COUNTRY_TABLE sheet={country_sheet_name!r} codeColumn={best_code_column} "
		f"iso3LikeRows={best_code_count}"
	)

	data_rows: list[tuple[int, str, dict[int, Any]]] = []
	for row_number, values in sorted(country_rows.items()):
		source_code = str(values.get(best_code_column, "")).strip().upper()
		if ISO3_RE.match(source_code):
			data_rows.append((row_number, source_code, values))

	codes = [source_code for _, source_code, _ in data_rows]
	duplicates = sorted(code for code, count in Counter(codes).items() if count > 1)
	print(f"countryRows={len(data_rows)} uniqueSourceCodes={len(set(codes))} duplicateCodes={duplicates}")

	mapped: dict[str, str] = {}
	unmapped_source: list[str] = []
	for _, source_code, _ in data_rows:
		iso3 = ALIASES.get(source_code, source_code)
		area_id = area_by_iso3.get(iso3)
		if area_id is None:
			unmapped_source.append(source_code)
			continue
		if iso3 in mapped:
			raise RuntimeError(f"Duplicate mapped country code {iso3} from spreadsheet.")
		mapped[iso3] = source_code
	missing_registry = sorted(set(area_by_iso3) - set(mapped))
	print(f"mappedRegistryAreas={len(mapped)}/250 aliases={ALIASES}")
	print(f"unmappedSourceCodes={sorted(set(unmapped_source))}")
	print(f"missingRegistryIso3={missing_registry}")

	max_column = max((max(values) for _, _, values in data_rows), default=0)
	for column in range(1, max_column + 1):
		present = 0
		numeric: list[float] = []
		text_samples: list[str] = []
		for _, _, values in data_rows:
			value = values.get(column)
			if value in (None, "", "#N/A"):
				continue
			present += 1
			if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
				numeric.append(float(value))
			elif len(text_samples) < 8:
				text_samples.append(str(value))
		print(
			f"COLUMN {column}: present={present}/{len(data_rows)} numeric={len(numeric)} "
			f"summary=({numeric_summary(numeric)}) textSamples={text_samples}"
		)

	for column in (11, 12, 13, 14, 15):
		missing_source_codes = sorted(
			source_code
			for _, source_code, values in data_rows
			if values.get(column) in (None, "", "#N/A")
		)
		missing_registry_codes = sorted(
			set(missing_registry)
			| {ALIASES.get(source_code, source_code) for source_code in missing_source_codes}
		)
		print(f"SOLAR_COLUMN {column}: missingSourceCodes={missing_source_codes}")
		print(f"SOLAR_COLUMN {column}: missingRegistryIso3={missing_registry_codes}")

	for iso3 in ("AUT", "DEU", "USA", "IND", "CHN", "ZAF", "NAM", "XKX"):
		source_code = mapped.get(iso3)
		if source_code is None:
			print(f"REFERENCE {iso3}: <missing>")
			continue
		row = next(values for _, code, values in data_rows if code == source_code)
		print(f"REFERENCE {iso3} source={source_code}: {row}")


if __name__ == "__main__":
	main()
