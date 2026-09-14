#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request


DEFAULT_API_BASE = "https://cckpapi.worldbank.org/cckp/v1"
DEFAULT_START_YEAR = 1950
DEFAULT_MINIMUM_LATEST_YEAR = 2025
DEFAULT_VARIABLES = ["tas", "pr", "txx", "tnn", "fd", "tr", "rx1day", "rx5day"]
LATEST_MONTH = "07"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Download audited CCKP ERA5 annual country time series.")
	parser.add_argument("--output-json", type=Path, required=True)
	parser.add_argument("--metadata-json", type=Path, required=True)
	parser.add_argument("--api-base", default=DEFAULT_API_BASE)
	parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
	parser.add_argument("--minimum-latest-year", type=int, default=DEFAULT_MINIMUM_LATEST_YEAR)
	parser.add_argument("--timeout", type=int, default=180)
	return parser.parse_args()


def request(url: str, timeout: int) -> bytes:
	req = urllib.request.Request(
		url,
		headers={
			"User-Agent": "kartensammlung-area-statistics-builds/cckp-era5",
			"Accept": "application/json",
		},
	)
	try:
		with urllib.request.urlopen(req, timeout=timeout) as response:
			if response.status != 200:
				raise RuntimeError(f"Unexpected CCKP HTTP status {response.status}.")
			return response.read()
	except urllib.error.HTTPError as error:
		body = error.read().decode("utf-8", errors="replace")
		raise RuntimeError(f"CCKP request failed with HTTP {error.code}: {body[:1000]}") from error


def candidate_url(api_base: str, start_year: int, end_year: int) -> str:
	variables = ",".join(DEFAULT_VARIABLES)
	return (
		f"{api_base.rstrip('/')}/era5-x0.25_timeseries_{variables}_timeseries_annual_"
		f"{start_year}-{end_year}_mean_historical_era5_x0.25_mean/all_countries?_format=json"
	)


def validate_payload(payload: object, start_year: int, end_year: int) -> dict:
	if not isinstance(payload, dict):
		raise RuntimeError("CCKP response must be a JSON object.")
	metadata = payload.get("metadata")
	if not isinstance(metadata, dict) or metadata.get("status") != "success" or metadata.get("messages") not in ([], None):
		raise RuntimeError(f"CCKP API returned unsuccessful metadata: {metadata!r}")
	data = payload.get("data")
	if not isinstance(data, dict) or set(data) != set(DEFAULT_VARIABLES):
		raise RuntimeError(f"Unexpected CCKP variable set: {list(data) if isinstance(data, dict) else type(data)}")

	expected_latest = f"{end_year}-{LATEST_MONTH}"
	expected_first = f"{start_year}-{LATEST_MONTH}"
	expected_count = end_year - start_year + 1
	common_codes: set[str] | None = None
	for variable in DEFAULT_VARIABLES:
		countries = data[variable]
		if not isinstance(countries, dict) or len(countries) < 240:
			raise RuntimeError(f"CCKP coverage unexpectedly small for {variable}: {len(countries) if isinstance(countries, dict) else 'invalid'}")
		codes = set(countries)
		common_codes = codes if common_codes is None else common_codes & codes
		for code, series in countries.items():
			if not isinstance(code, str) or len(code) != 3 or not isinstance(series, dict):
				raise RuntimeError(f"Unexpected CCKP country series for {variable}: {code!r}")
			keys = sorted(series)
			if len(keys) != expected_count or not keys or keys[0] != expected_first or keys[-1] != expected_latest:
				raise RuntimeError(
					f"CCKP {variable}/{code} does not contain a complete {start_year}-{end_year} annual series: "
					f"count={len(keys)} first={keys[0] if keys else None} last={keys[-1] if keys else None}"
				)
	if common_codes is None or len(common_codes) < 240:
		raise RuntimeError("CCKP variables do not share sufficient country coverage.")
	return {
		"countryCount": len(common_codes),
		"countries": sorted(common_codes),
		"latestKey": expected_latest,
		"seriesLength": expected_count,
	}


def main() -> None:
	args = parse_args()
	preferred_end_year = datetime.now(timezone.utc).year - 1
	if preferred_end_year < args.minimum_latest_year:
		preferred_end_year = args.minimum_latest_year

	last_error: Exception | None = None
	selected: tuple[int, str, bytes, dict, dict] | None = None
	for end_year in range(preferred_end_year, args.minimum_latest_year - 1, -1):
		url = candidate_url(args.api_base, args.start_year, end_year)
		try:
			body = request(url, args.timeout)
			payload = json.loads(body)
			audit = validate_payload(payload, args.start_year, end_year)
			selected = (end_year, url, body, payload, audit)
			break
		except (RuntimeError, json.JSONDecodeError) as error:
			last_error = error
			print(f"CCKP {args.start_year}-{end_year} not usable: {error}")

	if selected is None:
		raise RuntimeError(f"No complete CCKP ERA5 period from {args.minimum_latest_year} onward is available: {last_error}")

	end_year, url, body, payload, audit = selected
	args.output_json.parent.mkdir(parents=True, exist_ok=True)
	args.output_json.write_bytes(body)
	retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
	metadata = {
		"schema": "kartensammlung.cckp-era5-download/v1",
		"retrievedAt": retrieved_at,
		"requestUrl": url,
		"apiVersion": payload["metadata"].get("apiVersion"),
		"collection": "era5-x0.25",
		"scenario": "historical_era5",
		"aggregation": "annual",
		"statistic": "mean",
		"variables": DEFAULT_VARIABLES,
		"startYear": args.start_year,
		"endYear": end_year,
		"latestKey": audit["latestKey"],
		"countryCount": audit["countryCount"],
		"seriesLength": audit["seriesLength"],
		"inputFile": {
			"fileName": args.output_json.name,
			"bytes": len(body),
			"sha256": hashlib.sha256(body).hexdigest(),
		},
	}
	args.metadata_json.parent.mkdir(parents=True, exist_ok=True)
	args.metadata_json.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	print(
		f"Downloaded CCKP ERA5 {args.start_year}-{end_year}: "
		f"variables={len(DEFAULT_VARIABLES)} countries={audit['countryCount']} bytes={len(body)}"
	)


if __name__ == "__main__":
	main()
