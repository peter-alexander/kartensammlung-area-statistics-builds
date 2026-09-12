#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import statistics
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.data.apps.fao.org/api/v2/bigquery"
SQL_URL = "https://data.apps.fao.org/catalog/dataset/945666e6-7803-4621-b8ef-cfd885a84596/resource/4a000a1b-24f0-4328-aab6-b9b525892090/download/query_en.sql"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
CANDIDATES = {
	4550: "SDG 6.4.2 water stress",
	4551: "SDG 6.4.1 water use efficiency",
	4188: "total renewable water resources",
	4190: "renewable water resources per capita",
	4158: "internal renewable water resources per capita",
	4253: "total water withdrawal",
	4257: "total water withdrawal per capita",
	4254: "agricultural share of total withdrawal",
	4255: "municipal share of total withdrawal",
	4256: "industrial share of total withdrawal",
	4313: "area equipped for irrigation",
	4331: "cultivated area equipped for irrigation",
	4318: "equipped irrigation area actually irrigated",
	4328: "share of equipped area actually irrigated",
	4264: "desalinated water produced",
	4269: "produced municipal wastewater",
	4270: "treated municipal wastewater",
	4265: "direct use of treated municipal wastewater",
	4192: "dependency ratio",
	4471: "dam capacity per capita",
	4197: "total dam capacity",
}


def get_csv(variable: int, year: int = 2023) -> list[dict[str, str]]:
	query = urlencode({
		"area": "World",
		"download": "true",
		"sql_url": SQL_URL,
		"type": "all",
		"variable": str(variable),
		"year": str(year),
	})
	url = f"{API}?{query}"
	req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"})
	with urlopen(req, timeout=120) as response:
		data = response.read()
		print(f"REQUEST code={variable} status={response.status} bytes={len(data)} contentType={response.headers.get('content-type')}")
	text = data.decode("utf-8-sig")
	return list(csv.DictReader(io.StringIO(text)))


def quantile(values: list[float], q: float) -> float | None:
	if not values:
		return None
	values = sorted(values)
	if len(values) == 1:
		return values[0]
	pos = (len(values) - 1) * q
	lo = int(pos)
	hi = min(lo + 1, len(values) - 1)
	weight = pos - lo
	return values[lo] * (1 - weight) + values[hi] * weight


def main() -> None:
	for requested_code, label in CANDIDATES.items():
		print(f"\n=== {requested_code} {label} ===")
		try:
			rows = get_csv(requested_code)
		except Exception as exc:
			print(f"ERROR {type(exc).__name__}: {exc}")
			continue
		if not rows:
			print("EMPTY")
			continue
		variables: dict[str, tuple[str, str]] = {}
		country_values: dict[str, list[float]] = {}
		for row in rows:
			code = str(row.get("VariableCode", "")).strip()
			variables[code] = (str(row.get("Variable", "")).strip(), str(row.get("Unit", "")).strip())
			if str(row.get("IsAggregate", "")).strip().lower() == "true":
				continue
			m49 = str(row.get("m49", "")).strip()
			if not m49.isdigit():
				continue
			try:
				value = float(str(row.get("Value", "")).strip())
			except ValueError:
				continue
			country_values.setdefault(code, []).append(value)
		print(f"rows={len(rows)} variables={len(variables)} codes={','.join(sorted(variables))}")
		for code in sorted(variables, key=lambda value: int(value) if value.isdigit() else 999999):
			name, unit = variables[code]
			values = country_values.get(code, [])
			if values:
				print(
					f"VAR {code} | {name} | unit={unit!r} | countries={len(values)} "
					f"min={min(values):.6g} q10={quantile(values, .1):.6g} q25={quantile(values, .25):.6g} "
					f"median={statistics.median(values):.6g} q75={quantile(values, .75):.6g} "
					f"q90={quantile(values, .9):.6g} max={max(values):.6g}"
				)
			else:
				print(f"VAR {code} | {name} | unit={unit!r} | countries=0")


if __name__ == "__main__":
	main()
