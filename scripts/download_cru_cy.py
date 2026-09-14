#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import html.parser
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "cru-cy-indicators.json"
DEFAULT_MAPPING = ROOT / "config" / "cru-cy-country-map.json"
EXPECTED_VARIABLES = {"tmp", "tmx", "tmn", "pre", "dtr", "frs", "wet", "pet", "cld", "vap"}
EXPECTED_UNITS = {
	"tmp": "degrees Celsius",
	"tmx": "degrees Celsius",
	"tmn": "degrees Celsius",
	"pre": "mm/month",
	"dtr": "degrees Celsius",
	"frs": "days",
	"wet": "days",
	"pet": "mm/day",
	"cld": "percentage",
	"vap": "hPa",
}
EXPECTED_PET_UNAVAILABLE = {
	"BMU", "CCK", "COK", "CXR", "IOT", "KIR", "LCA", "MDV", "MHL", "NFK", "NRU", "TKL", "TUV",
}


class LinkParser(html.parser.HTMLParser):
	def __init__(self) -> None:
		super().__init__()
		self.links: list[str] = []

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if tag != "a":
			return
		for key, value in attrs:
			if key == "href" and value:
				self.links.append(value)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Check and download CRU-CY country climate time series.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
	parser.add_argument("--output-json", type=Path)
	parser.add_argument("--metadata-json", type=Path)
	parser.add_argument("--check-only", action="store_true")
	parser.add_argument("--workers", type=int, default=8)
	parser.add_argument("--timeout", type=int, default=60)
	return parser.parse_args()


def load_json(path: Path) -> dict:
	payload = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(payload, dict):
		raise RuntimeError(f"Expected JSON object in {path}")
	return payload


def fetch_bytes(url: str, timeout: int) -> bytes:
	req = urllib.request.Request(
		url,
		headers={"User-Agent": "kartensammlung-area-statistics-builds/cru-cy"},
	)
	last_error: Exception | None = None
	for attempt in range(4):
		try:
			with urllib.request.urlopen(req, timeout=timeout) as response:
				if response.status != 200:
					raise RuntimeError(f"Unexpected HTTP {response.status} for {url}")
				return response.read()
		except (urllib.error.URLError, TimeoutError, RuntimeError) as error:
			last_error = error
			if attempt < 3:
				time.sleep(1.5 * (attempt + 1))
	raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def fetch_text(url: str, timeout: int) -> str:
	return fetch_bytes(url, timeout).decode("utf-8", errors="strict")


def validate_config(config: dict, mapping: dict) -> tuple[list[str], dict[str, str], set[str]]:
	if config.get("schema") != "kartensammlung.cru-cy-statistics/v1":
		raise RuntimeError("Invalid CRU-CY statistics config schema.")
	if mapping.get("schema") != "kartensammlung.cru-cy-country-map/v1":
		raise RuntimeError("Invalid CRU-CY country mapping schema.")
	if config.get("sourceVersion") != mapping.get("sourceVersion"):
		raise RuntimeError("CRU-CY config and mapping versions differ.")
	if [config.get("sourceStartYear"), config.get("sourceEndYear")] != mapping.get("sourceYears"):
		raise RuntimeError("CRU-CY config and mapping year ranges differ.")
	indicators = config.get("indicators")
	if not isinstance(indicators, list) or len(indicators) != 10:
		raise RuntimeError("CRU-CY must contain exactly ten audited indicators.")
	variables = [str(item.get("sourceVariable", "")) for item in indicators if isinstance(item, dict)]
	if len(variables) != 10 or set(variables) != EXPECTED_VARIABLES or len(set(variables)) != 10:
		raise RuntimeError(f"Unexpected CRU-CY variable set: {variables}")
	name_to_iso3 = mapping.get("sourceNameToIso3")
	if not isinstance(name_to_iso3, dict) or len(name_to_iso3) != 218:
		raise RuntimeError(f"Unexpected CRU-CY mapping size: {len(name_to_iso3) if isinstance(name_to_iso3, dict) else 'invalid'}")
	if len(set(name_to_iso3.values())) != len(name_to_iso3):
		raise RuntimeError("CRU-CY source mapping is not one-to-one.")
	excluded = mapping.get("excludedSourceAreas")
	if not isinstance(excluded, list) or len(excluded) != 73:
		raise RuntimeError("Unexpected CRU-CY excluded source-area set.")
	return variables, {str(key): str(value) for key, value in name_to_iso3.items()}, {str(value) for value in excluded}


def discover_current_version(config: dict, timeout: int) -> str:
	text = fetch_text(str(config["familyPage"]), timeout)
	match = re.search(r"Current\s+CRU-CY\s+dataset\s*\(v([0-9]+(?:\.[0-9]+)+)\)", text, flags=re.IGNORECASE)
	if not match:
		raise RuntimeError("Could not detect the current CRU-CY version from the CRU family page.")
	return match.group(1)


def directory_source_names(config: dict, variable: str, timeout: int) -> set[str]:
	text = fetch_text(f"{str(config['sourceRoot']).rstrip('/')}/countries/{variable}/", timeout)
	parser = LinkParser()
	parser.feed(text)
	version = re.escape(str(config["sourceVersion"]))
	start_year = int(config["sourceStartYear"])
	end_year = int(config["sourceEndYear"])
	pattern = re.compile(rf"^crucy\.v{version}\.{start_year}\.{end_year}\.(.+)\.{re.escape(variable)}\.per$")
	result: set[str] = set()
	for link in parser.links:
		filename = link.rsplit("/", 1)[-1]
		match = pattern.match(filename)
		if match:
			result.add(match.group(1))
	return result


def parse_country_file(
	config: dict,
	variable: str,
	source_name: str,
	iso3: str,
	timeout: int,
) -> tuple[str, str, dict[str, float]]:
	version = str(config["sourceVersion"])
	start_year = int(config["sourceStartYear"])
	end_year = int(config["sourceEndYear"])
	filename = f"crucy.v{version}.{start_year}.{end_year}.{source_name}.{variable}.per"
	url = f"{str(config['sourceRoot']).rstrip('/')}/countries/{variable}/{filename}"
	text = fetch_text(url, timeout)
	lines = [line.rstrip() for line in text.splitlines() if line.strip()]
	expected_lines = 4 + end_year - start_year + 1
	if len(lines) != expected_lines:
		raise RuntimeError(f"Unexpected line count for {variable}/{source_name}: {len(lines)} != {expected_lines}")
	units_marker = "Units = "
	if units_marker not in lines[1]:
		raise RuntimeError(f"Missing units for {variable}/{source_name}: {lines[1]}")
	units = lines[1].split(units_marker, 1)[1].strip()
	if units != EXPECTED_UNITS[variable]:
		raise RuntimeError(f"Unexpected units for {variable}/{source_name}: {units!r}")
	if f"Period = {start_year}.{end_year}" not in lines[2] or "missing value = -999.0" not in lines[2]:
		raise RuntimeError(f"Unexpected period/missing marker for {variable}/{source_name}: {lines[2]}")
	header = lines[3].split()
	expected_header = ["YEAR", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "MAM", "JJA", "SON", "DJF", "ANN"]
	if header != expected_header:
		raise RuntimeError(f"Unexpected CRU-CY header for {variable}/{source_name}: {header}")

	annual: dict[str, float] = {}
	missing_years: list[int] = []
	for line in lines[4:]:
		fields = line.split()
		if len(fields) != 18:
			raise RuntimeError(f"Unexpected row width for {variable}/{source_name}: {line}")
		year = int(fields[0])
		value = float(fields[-1])
		if value == -999.0:
			missing_years.append(year)
			continue
		annual[str(year)] = value
	if sorted(int(year) for year in annual) + missing_years != list(range(start_year, end_year + 1)):
		raise RuntimeError(f"Unexpected year coverage for {variable}/{source_name}")

	if variable == "pet":
		expected_missing = iso3 in EXPECTED_PET_UNAVAILABLE
		if expected_missing and len(missing_years) != end_year - start_year + 1:
			raise RuntimeError(f"PET unexpectedly became partly available for {source_name}/{iso3}: {missing_years[:10]}")
		if not expected_missing and missing_years:
			raise RuntimeError(f"Unexpected PET missing years for {source_name}/{iso3}: {missing_years[:10]}")
	elif missing_years:
		raise RuntimeError(f"Unexpected missing annual values for {variable}/{source_name}/{iso3}: {missing_years[:10]}")
	return variable, iso3, annual


def main() -> None:
	args = parse_args()
	config = load_json(args.config)
	mapping = load_json(args.mapping)
	variables, name_to_iso3, excluded = validate_config(config, mapping)
	current_version = discover_current_version(config, args.timeout)
	configured_version = str(config["sourceVersion"])
	print(f"CRU-CY current version={current_version}; configured version={configured_version}")
	if current_version != configured_version:
		raise RuntimeError(
			f"A new CRU-CY release v{current_version} is available. "
			f"Configured v{configured_version} must be audited before production is updated."
		)
	if args.check_only:
		print("CRU-CY release guard OK")
		return
	if args.output_json is None or args.metadata_json is None:
		raise RuntimeError("--output-json and --metadata-json are required unless --check-only is used.")
	if args.workers < 1 or args.workers > 16:
		raise RuntimeError("--workers must be between 1 and 16.")

	expected_names = set(name_to_iso3) | excluded | {"all"}
	for variable in variables:
		names = directory_source_names(config, variable, args.timeout)
		if len(names) != int(mapping["sourceAreaCount"]) or names != expected_names:
			raise RuntimeError(
				f"CRU-CY source-area universe changed for {variable}: "
				f"count={len(names)} new={sorted(names - expected_names)} missing={sorted(expected_names - names)}"
			)
	print(f"Validated source-area universe: variables={len(variables)} areas={len(expected_names)}")

	data: dict[str, dict[str, dict[str, float]]] = {variable: {} for variable in variables}
	tasks = []
	with ThreadPoolExecutor(max_workers=args.workers) as pool:
		for variable in variables:
			for source_name, iso3 in name_to_iso3.items():
				tasks.append(pool.submit(parse_country_file, config, variable, source_name, iso3, args.timeout))
		for index, future in enumerate(as_completed(tasks), start=1):
			variable, iso3, annual = future.result()
			data[variable][iso3] = annual
			if index % 250 == 0 or index == len(tasks):
				print(f"Downloaded and validated {index}/{len(tasks)} CRU-CY country-variable files")

	for variable in variables:
		if len(data[variable]) != len(name_to_iso3):
			raise RuntimeError(f"Unexpected mapped country count for {variable}: {len(data[variable])}")
	for iso3 in EXPECTED_PET_UNAVAILABLE:
		if data["pet"].get(iso3) != {}:
			raise RuntimeError(f"Expected PET to be unavailable for {iso3}")
	for iso3 in set(name_to_iso3.values()) - EXPECTED_PET_UNAVAILABLE:
		if len(data["pet"].get(iso3, {})) != int(config["sourceEndYear"]) - int(config["sourceStartYear"]) + 1:
			raise RuntimeError(f"Unexpected PET coverage for {iso3}")

	raw_payload = {
		"schema": "kartensammlung.cru-cy-download/v1",
		"sourceVersion": configured_version,
		"sourceRun": config["sourceRun"],
		"sourceYears": [config["sourceStartYear"], config["sourceEndYear"]],
		"sourceRoot": config["sourceRoot"],
		"variables": data,
	}
	raw_bytes = (json.dumps(raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
	args.output_json.parent.mkdir(parents=True, exist_ok=True)
	args.output_json.write_bytes(raw_bytes)
	retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
	metadata = {
		"schema": "kartensammlung.cru-cy-download-metadata/v1",
		"retrievedAt": retrieved_at,
		"sourceVersion": configured_version,
		"sourceRun": config["sourceRun"],
		"sourceYears": [config["sourceStartYear"], config["sourceEndYear"]],
		"sourceAreaCount": mapping["sourceAreaCount"],
		"mappedAreaCount": mapping["mappedAreaCount"],
		"excludedSourceAreaCount": len(excluded),
		"downloadedFileCount": len(tasks),
		"variables": variables,
		"inputFile": {
			"fileName": args.output_json.name,
			"bytes": len(raw_bytes),
			"sha256": hashlib.sha256(raw_bytes).hexdigest(),
		},
	}
	args.metadata_json.parent.mkdir(parents=True, exist_ok=True)
	args.metadata_json.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	print(
		f"Downloaded CRU-CY v{configured_version}: files={len(tasks)} "
		f"mappedAreas={len(name_to_iso3)} years={config['sourceStartYear']}-{config['sourceEndYear']} bytes={len(raw_bytes)}"
	)


if __name__ == "__main__":
	main()
