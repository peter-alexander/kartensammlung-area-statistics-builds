#!/usr/bin/env python3

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://cckpapi.worldbank.org/cckp/v1"
REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
VARIABLES = ["tas", "tasmax", "tasmin", "pr", "txx", "tnn", "fd", "tr", "rx1day", "rx5day"]


def endpoint_for(variables, geocode, period="1950-2022"):
	return (
		f"era5-x0.25_timeseries_{variables}_timeseries_annual_{period}_"
		f"mean_historical_era5_x0.25_mean/{geocode}?_format=json"
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


def collect_iso3(value, output):
	if isinstance(value, dict):
		for key, item in value.items():
			if key.lower() in {"iso3", "iso_a3"} and isinstance(item, str) and len(item) == 3:
				output.add(item.upper())
			collect_iso3(item, output)
	elif isinstance(value, list):
		for item in value:
			collect_iso3(item, output)


def load_registry():
	status, content_type, body = fetch(REGISTRY_URL)
	if status != 200:
		raise RuntimeError(f"Registry request failed: HTTP {status}: {body[:500]!r}")
	payload = json.loads(body)
	areas = payload.get("areas") or payload.get("countries") or []
	iso3 = set()
	collect_iso3(areas, iso3)
	print(f"registry_http={status} content_type={content_type} bytes={len(body)}")
	print(f"registry_top_keys={list(payload) if isinstance(payload, dict) else '<non-dict>'}")
	print(f"registry_area_count={len(areas)} extracted_iso3={len(iso3)}")
	if areas:
		print("registry_first_area=" + json.dumps(areas[0], ensure_ascii=False, sort_keys=True))
	return payload, iso3


def request_payload(variables, geocode, output_path, period="1950-2022"):
	url = f"{API_BASE}/{endpoint_for(variables, geocode, period)}"
	status, content_type, body = fetch(url)
	print(
		f"request variables={variables} geocode={geocode} period={period} "
		f"http={status} content_type={content_type} bytes={len(body)}"
	)
	if status != 200:
		print(body[:2000].decode("utf-8", errors="replace"))
		return None
	try:
		payload = json.loads(body)
	except json.JSONDecodeError:
		print(body[:2000].decode("utf-8", errors="replace"))
		return None
	output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
	metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
	print("metadata=" + json.dumps(metadata, ensure_ascii=False, sort_keys=True))
	print(json.dumps(describe(payload), ensure_ascii=False, indent=2)[:12000])
	return payload


def summarize_country_series(label, payload, geocode="AUT"):
	if not isinstance(payload, dict):
		return
	data = payload.get("data")
	if not isinstance(data, dict):
		return
	series = data.get(geocode)
	if not isinstance(series, dict):
		print(f"series {label}: no {geocode} dict; data_keys={list(data)[:20]}")
		return
	keys = sorted(series)
	print(
		f"series {label}: count={len(keys)} first={keys[0] if keys else None} "
		f"last={keys[-1] if keys else None} last_value={series.get(keys[-1]) if keys else None}"
	)


def main():
	outdir = Path("diagnostics/cckp-era5")
	outdir.mkdir(parents=True, exist_ok=True)
	registry, registry_iso3 = load_registry()
	(outdir / "registry.json").write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

	failures = []
	individual = {}
	for variable in VARIABLES:
		payload = request_payload(variable, "AUT", outdir / f"AUT-{variable}-1950-2022.json")
		individual[variable] = payload
		if payload is None:
			failures.append(f"AUT:{variable}")
		else:
			summarize_country_series(variable, payload)

	combined = request_payload(
		"tas,tasmax,tasmin",
		"AUT",
		outdir / "AUT-tas-tasmax-tasmin-1950-2022.json",
	)
	if combined is not None:
		print("combined_temperature_request_success=true")

	for period in ("1950-2023", "1950-2024", "1950-2025"):
		payload = request_payload("tas", "AUT", outdir / f"AUT-tas-{period}.json", period=period)
		summarize_country_series(f"tas:{period}", payload)

	all_countries = request_payload("tas", "all_countries", outdir / "all-countries-tas-1950-2022.json")
	if all_countries is None:
		failures.append("all_countries:tas")
	else:
		data = all_countries.get("data") if isinstance(all_countries, dict) else None
		cckp_codes = set(data) if isinstance(data, dict) else set()
		print(f"all_countries_codes={len(cckp_codes)}")
		print("cckp_codes=" + ",".join(sorted(cckp_codes)))
		if registry_iso3:
			missing = sorted(registry_iso3 - cckp_codes)
			extra = sorted(cckp_codes - registry_iso3)
			print(f"registry_iso3_not_in_cckp={len(missing)}: {','.join(missing)}")
			print(f"cckp_codes_not_in_registry={len(extra)}: {','.join(extra)}")

	for variable in ("tasmax", "tasmin"):
		try:
			tas_series = individual["tas"]["data"]["AUT"]
			other_series = individual[variable]["data"]["AUT"]
			print(f"individual_{variable}_equals_tas={other_series == tas_series}")
		except (KeyError, TypeError):
			pass

	if failures:
		print("FAILED_REQUESTS=" + ",".join(failures), file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
