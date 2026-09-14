#!/usr/bin/env python3

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://cckpapi.worldbank.org/cckp/v1"
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
VARIABLES = ["tas", "tasmax", "tasmin", "pr", "txx", "tnn", "fd", "tr", "rx1day", "rx5day"]
ENDPOINT_TEMPLATE = (
	"era5-x0.25_timeseries_{variables}_timeseries_annual_1950-2022_"
	"mean_historical_era5_x0.25_mean/{geocode}?_format=json"
)


def fetch(url):
	req = urllib.request.Request(
		url,
		headers={
			"User-Agent": "kartensammlung-area-statistics-builds/cckp-era5-audit",
			"Accept": "application/json",
		},
	)
	try:
		with urllib.request.urlopen(req, timeout=90) as response:
			body = response.read()
			return response.status, response.headers.get("Content-Type", ""), body
	except urllib.error.HTTPError as exc:
		body = exc.read()
		return exc.code, exc.headers.get("Content-Type", ""), body


def describe(value, depth=0):
	if depth >= 3:
		if isinstance(value, dict):
			return {"type": "dict", "keys": list(value)[:20], "len": len(value)}
		if isinstance(value, list):
			return {"type": "list", "len": len(value)}
		return value
	if isinstance(value, dict):
		result = {"type": "dict", "len": len(value), "keys": list(value)[:30]}
		for key in list(value)[:5]:
			result.setdefault("sample", {})[key] = describe(value[key], depth + 1)
		return result
	if isinstance(value, list):
		return {
			"type": "list",
			"len": len(value),
			"sample": [describe(item, depth + 1) for item in value[:3]],
		}
	return value


def collect_three_letter_strings(value, output):
	if isinstance(value, dict):
		for key, item in value.items():
			if isinstance(item, str) and len(item) == 3 and item.isalpha():
				if key.lower() in {"iso3", "iso_a3", "code", "geocode", "countrycode", "country_code"}:
					output.add(item.upper())
			collect_three_letter_strings(item, output)
	elif isinstance(value, list):
		for item in value:
			collect_three_letter_strings(item, output)


def load_registry():
	status, content_type, body = fetch(REGISTRY_URL)
	if status != 200:
		raise RuntimeError(f"Registry request failed: HTTP {status}: {body[:500]!r}")
	payload = json.loads(body)
	areas = payload.get("areas") or payload.get("countries") or []
	iso3 = set()
	for area in areas:
		if not isinstance(area, dict):
			continue
		for key in ("iso3", "ISO3", "code"):
			value = area.get(key)
			if isinstance(value, str) and len(value) == 3:
				iso3.add(value.upper())
				break
	print(f"registry_http={status} content_type={content_type} bytes={len(body)}")
	print(f"registry_top_keys={list(payload) if isinstance(payload, dict) else '<non-dict>'}")
	print(f"registry_area_count={len(areas)} extracted_iso3={len(iso3)}")
	return payload, iso3


def request_payload(variables, geocode, output_path):
	endpoint = ENDPOINT_TEMPLATE.format(variables=variables, geocode=geocode)
	url = f"{API_BASE}/{endpoint}"
	status, content_type, body = fetch(url)
	print(f"request variables={variables} geocode={geocode} http={status} content_type={content_type} bytes={len(body)}")
	if status != 200:
		print(body[:2000].decode("utf-8", errors="replace"))
		return None
	try:
		payload = json.loads(body)
	except json.JSONDecodeError:
		print(body[:2000].decode("utf-8", errors="replace"))
		return None
	output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
	print(json.dumps(describe(payload), ensure_ascii=False, indent=2)[:12000])
	return payload


def main():
	outdir = Path("diagnostics/cckp-era5")
	outdir.mkdir(parents=True, exist_ok=True)
	registry, registry_iso3 = load_registry()
	(outdir / "registry.json").write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

	failures = []
	for variable in VARIABLES:
		payload = request_payload(variable, "AUT", outdir / f"AUT-{variable}.json")
		if payload is None:
			failures.append(f"AUT:{variable}")

	all_countries = request_payload("tas", "all_countries", outdir / "all-countries-tas.json")
	if all_countries is None:
		failures.append("all_countries:tas")
	else:
		cckp_codes = set()
		collect_three_letter_strings(all_countries, cckp_codes)
		print(f"all_countries_detected_three_letter_codes={len(cckp_codes)}")
		if cckp_codes:
			print("cckp_codes=" + ",".join(sorted(cckp_codes)))
			if registry_iso3:
				missing = sorted(registry_iso3 - cckp_codes)
				extra = sorted(cckp_codes - registry_iso3)
				print(f"registry_iso3_not_detected={len(missing)}: {','.join(missing)}")
				print(f"cckp_codes_not_in_registry={len(extra)}: {','.join(extra)}")

	if failures:
		print("FAILED_REQUESTS=" + ",".join(failures), file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
