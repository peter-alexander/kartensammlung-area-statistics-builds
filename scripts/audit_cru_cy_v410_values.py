#!/usr/bin/env python3

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import statistics
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "config" / "cru-cy-v410-country-map.json"
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
BASE = "https://crudata.uea.ac.uk/cru/data/hrg/cru_ts_4.10/crucy.2606161920.v4.10"
VARIABLES = ("tmp", "tmx", "tmn", "pre", "dtr", "frs", "wet", "pet", "cld", "vap")
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


def fetch_text(url):
	req = urllib.request.Request(
		url,
		headers={"User-Agent": "kartensammlung-area-statistics-builds/cru-cy-value-audit"},
	)
	last_error = None
	for attempt in range(3):
		try:
			with urllib.request.urlopen(req, timeout=60) as response:
				return response.read().decode("utf-8", errors="strict")
		except (urllib.error.URLError, TimeoutError) as error:
			last_error = error
	raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def fetch_json(url):
	return json.loads(fetch_text(url))


def percentile(values, p):
	ordered = sorted(values)
	if not ordered:
		return None
	position = (len(ordered) - 1) * p
	lower = math.floor(position)
	upper = math.ceil(position)
	if lower == upper:
		return ordered[lower]
	weight = position - lower
	return ordered[lower] * (1 - weight) + ordered[upper] * weight


def parse_file(variable, source_name, iso3):
	filename = f"crucy.v4.10.1901.2025.{source_name}.{variable}.per"
	url = f"{BASE}/countries/{variable}/{filename}"
	text = fetch_text(url)
	lines = [line.rstrip() for line in text.splitlines() if line.strip()]
	if len(lines) != 129:
		raise RuntimeError(f"Unexpected line count for {variable}/{source_name}: {len(lines)}")
	if f"Country = {source_name.replace('_', ' ')}" not in lines[1] and f"Country = {source_name}" not in lines[1]:
		# CRU prints some source names with different spacing; the filename is the authoritative identity.
		pass
	units_marker = "Units = "
	if units_marker not in lines[1]:
		raise RuntimeError(f"Missing units in {variable}/{source_name}: {lines[1]}")
	units = lines[1].split(units_marker, 1)[1].strip()
	if units != EXPECTED_UNITS[variable]:
		raise RuntimeError(f"Unexpected units for {variable}/{source_name}: {units!r}")
	if "Period = 1901.2025" not in lines[2] or "missing value = -999.0" not in lines[2]:
		raise RuntimeError(f"Unexpected period/missing marker for {variable}/{source_name}: {lines[2]}")
	if not lines[3].split() == ["YEAR", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "MAM", "JJA", "SON", "DJF", "ANN"]:
		raise RuntimeError(f"Unexpected header for {variable}/{source_name}: {lines[3]}")

	annual = {}
	for line in lines[4:]:
		fields = line.split()
		if len(fields) != 18:
			raise RuntimeError(f"Unexpected row width for {variable}/{source_name}: {line}")
		year = int(fields[0])
		annual[year] = float(fields[-1])
	if sorted(annual) != list(range(1901, 2026)):
		raise RuntimeError(f"Unexpected years for {variable}/{source_name}")
	return variable, source_name, iso3, annual


def main():
	mapping_payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
	if mapping_payload.get("schema") != "kartensammlung.cru-cy-country-map/v1":
		raise RuntimeError("Invalid CRU-CY mapping schema")
	mapping = mapping_payload["sourceNameToIso3"]
	excluded = set(mapping_payload["excludedSourceAreas"])
	if len(mapping) != mapping_payload["mappedAreaCount"] or len(mapping) != 218:
		raise RuntimeError(f"Unexpected mapped source count: {len(mapping)}")
	if len(set(mapping.values())) != len(mapping):
		raise RuntimeError("CRU-CY mapping is not one-to-one")

	registry = fetch_json(REGISTRY_URL)
	registry_iso3 = {area["codes"]["iso3"] for area in registry["areas"]}
	if len(registry_iso3) != 250:
		raise RuntimeError(f"Unexpected registry size: {len(registry_iso3)}")
	if not set(mapping.values()).issubset(registry_iso3):
		raise RuntimeError("CRU-CY mapping contains ISO3 codes outside registry")
	missing_registry = sorted(registry_iso3 - set(mapping.values()))
	if missing_registry != mapping_payload["expectedMissingRegistryIso3"]:
		raise RuntimeError(f"Registry gap changed: {missing_registry}")

	# Validate that the audited source-name universe is exactly partitioned into mapped, excluded and 'all'.
	index_text = fetch_text(f"{BASE}/countries/tmp/")
	import re
	source_names = set(re.findall(r"crucy\.v4\.10\.1901\.2025\.([^\"<>/]+)\.tmp\.per", index_text))
	if len(source_names) != mapping_payload["sourceAreaCount"]:
		raise RuntimeError(f"Unexpected CRU-CY source-name count: {len(source_names)}")
	if source_names != set(mapping) | excluded | {"all"}:
		raise RuntimeError(
			"CRU-CY source-name universe changed: "
			f"new={sorted(source_names - set(mapping) - excluded - {'all'})} "
			f"missing={sorted((set(mapping) | excluded | {'all'}) - source_names)}"
		)

	results = {variable: {} for variable in VARIABLES}
	tasks = []
	with ThreadPoolExecutor(max_workers=10) as pool:
		for variable in VARIABLES:
			for source_name, iso3 in mapping.items():
				tasks.append(pool.submit(parse_file, variable, source_name, iso3))
		for index, future in enumerate(as_completed(tasks), start=1):
			variable, source_name, iso3, annual = future.result()
			results[variable][iso3] = annual
			if index % 250 == 0 or index == len(tasks):
				print(f"downloaded={index}/{len(tasks)}")

	summary = {
		"schema": "kartensammlung.cru-cy-v410-value-audit/v1",
		"sourceVersion": "4.10",
		"sourceYears": [1901, 2025],
		"mappedAreas": len(mapping),
		"variables": {},
	}
	for variable in VARIABLES:
		series_by_iso3 = results[variable]
		if len(series_by_iso3) != 218:
			raise RuntimeError(f"Unexpected mapped coverage for {variable}: {len(series_by_iso3)}")
		coverage_by_year = {}
		missing_by_year = {}
		for year in range(1901, 2026):
			valid = [
				iso3
				for iso3, annual in series_by_iso3.items()
				if annual[year] != -999.0 and math.isfinite(annual[year])
			]
			coverage_by_year[str(year)] = len(valid)
			if len(valid) != 218:
				missing_by_year[str(year)] = sorted(set(series_by_iso3) - set(valid))
		latest_values = {
			iso3: annual[2025]
			for iso3, annual in sorted(series_by_iso3.items())
			if annual[2025] != -999.0 and math.isfinite(annual[2025])
		}
		values = list(latest_values.values())
		stats = {
			"seriesCount": len(series_by_iso3),
			"minimumCoverage": min(coverage_by_year.values()),
			"maximumCoverage": max(coverage_by_year.values()),
			"latestCoverage": len(values),
			"missingYears": missing_by_year,
			"latestMin": min(values) if values else None,
			"latestP05": percentile(values, 0.05),
			"latestP10": percentile(values, 0.10),
			"latestP25": percentile(values, 0.25),
			"latestMedian": statistics.median(values) if values else None,
			"latestP75": percentile(values, 0.75),
			"latestP90": percentile(values, 0.90),
			"latestP95": percentile(values, 0.95),
			"latestMax": max(values) if values else None,
			"latestValues": latest_values,
		}
		summary["variables"][variable] = stats
		print(variable + "=" + json.dumps({k: v for k, v in stats.items() if k != "latestValues"}, sort_keys=True))

	# Regression checks for the directly audited Austrian source values.
	expected_austria = {
		"tmp": 8.4,
		"tmx": 13.2,
		"tmn": 3.7,
		"pre": 870.1,
		"dtr": 9.5,
		"frs": 133.5,
		"wet": 148.1,
		"pet": 2.1,
		"cld": 59.4,
		"vap": 8.5,
	}
	for variable, expected in expected_austria.items():
		actual = results[variable]["AUT"][2025]
		if abs(actual - expected) > 1e-9:
			raise RuntimeError(f"Austria 2025 changed for {variable}: {actual} != {expected}")

	outdir = Path("diagnostics/cru-cy-v410")
	outdir.mkdir(parents=True, exist_ok=True)
	(outdir / "value-summary.json").write_text(
		json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
		encoding="utf-8",
	)
	print("VALUE_AUDIT_OK")


if __name__ == "__main__":
	main()
