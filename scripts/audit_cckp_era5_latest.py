#!/usr/bin/env python3

import json
import math
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://cckpapi.worldbank.org/cckp/v1"
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
SAFE_VARIABLES = ["tas", "pr", "txx", "tnn", "fd", "tr", "rx1day", "rx5day"]
PERIOD = "1950-2025"
LATEST_KEY = "2025-07"
ALIASES = {"KSV": "XKX"}


def fetch_json(url):
	req = urllib.request.Request(
		url,
		headers={
			"User-Agent": "kartensammlung-area-statistics-builds/cckp-era5-audit",
			"Accept": "application/json",
		},
	)
	try:
		with urllib.request.urlopen(req, timeout=180) as response:
			body = response.read()
	except urllib.error.HTTPError as exc:
		body = exc.read()
		raise RuntimeError(f"HTTP {exc.code}: {body[:1000]!r}") from exc
	return json.loads(body), len(body)


def percentile(values, p):
	if not values:
		return None
	ordered = sorted(values)
	position = (len(ordered) - 1) * p
	lower = math.floor(position)
	upper = math.ceil(position)
	if lower == upper:
		return ordered[lower]
	weight = position - lower
	return ordered[lower] * (1 - weight) + ordered[upper] * weight


def registry_iso3():
	payload, body_size = fetch_json(REGISTRY_URL)
	areas = payload["areas"]
	codes = {area["codes"]["iso3"] for area in areas}
	print(f"registry areas={len(areas)} iso3={len(codes)} bytes={body_size}")
	assert len(areas) == 250
	assert len(codes) == 250
	return codes


def main():
	outdir = Path("diagnostics/cckp-era5-latest")
	outdir.mkdir(parents=True, exist_ok=True)
	registry_codes = registry_iso3()
	variables = ",".join(SAFE_VARIABLES)
	url = (
		f"{API_BASE}/era5-x0.25_timeseries_{variables}_timeseries_annual_{PERIOD}_"
		"mean_historical_era5_x0.25_mean/all_countries?_format=json"
	)
	payload, body_size = fetch_json(url)
	(outdir / "all-countries-safe-1950-2025.json").write_text(
		json.dumps(payload, ensure_ascii=False, indent=2),
		encoding="utf-8",
	)
	print(f"combined_all_countries bytes={body_size}")
	metadata = payload.get("metadata", {})
	print("metadata=" + json.dumps(metadata, ensure_ascii=False, sort_keys=True))
	assert metadata.get("status") == "success"
	assert not metadata.get("messages")

	data = payload.get("data")
	assert isinstance(data, dict)
	print("data_top_keys=" + ",".join(data.keys()))
	assert set(data) == set(SAFE_VARIABLES), (set(data), set(SAFE_VARIABLES))

	report = {
		"period": PERIOD,
		"latestKey": LATEST_KEY,
		"aliases": ALIASES,
		"variables": {},
	}
	for variable in SAFE_VARIABLES:
		countries = data[variable]
		assert isinstance(countries, dict)
		cckp_codes = set(countries)
		mapped_codes = {ALIASES.get(code, code) for code in cckp_codes}
		missing_registry = sorted(registry_codes - mapped_codes)
		extra_mapped = sorted(mapped_codes - registry_codes)
		latest_values = []
		latest_codes = set()
		series_lengths = set()
		first_keys = set()
		last_keys = set()
		for code, series in countries.items():
			assert isinstance(series, dict)
			keys = sorted(series)
			series_lengths.add(len(keys))
			if keys:
				first_keys.add(keys[0])
				last_keys.add(keys[-1])
			value = series.get(LATEST_KEY)
			if isinstance(value, (int, float)) and math.isfinite(value):
				latest_values.append(float(value))
				latest_codes.add(ALIASES.get(code, code))
		latest_missing = sorted(registry_codes - latest_codes)
		stats = {
			"countryCount": len(countries),
			"mappedCountryCount": len(mapped_codes & registry_codes),
			"missingRegistryCodes": missing_registry,
			"extraMappedCodes": extra_mapped,
			"seriesLengths": sorted(series_lengths),
			"firstKeys": sorted(first_keys),
			"lastKeys": sorted(last_keys),
			"latestValueCount": len(latest_values),
			"latestMissingRegistryCodes": latest_missing,
			"latestMin": min(latest_values) if latest_values else None,
			"latestP10": percentile(latest_values, 0.10),
			"latestP25": percentile(latest_values, 0.25),
			"latestMedian": percentile(latest_values, 0.50),
			"latestP75": percentile(latest_values, 0.75),
			"latestP90": percentile(latest_values, 0.90),
			"latestMax": max(latest_values) if latest_values else None,
		}
		report["variables"][variable] = stats
		print(variable + "=" + json.dumps(stats, ensure_ascii=False, sort_keys=True))
		assert len(countries) >= 240
		assert len(mapped_codes & registry_codes) >= 240
		assert len(latest_values) >= 240
		assert set(missing_registry) <= {"ATA", "ESH", "FLK", "SGS"}
		assert not extra_mapped

	for required in ("AUT", "DEU", "USA", "IND", "CHN", "ZAF", "NAM", "XKX"):
		for variable in SAFE_VARIABLES:
			countries = data[variable]
			source_code = "KSV" if required == "XKX" else required
			assert source_code in countries, (required, variable)
			assert isinstance(countries[source_code].get(LATEST_KEY), (int, float)), (required, variable)

	(outdir / "summary.json").write_text(
		json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
		encoding="utf-8",
	)
	print("AUDIT_OK")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
