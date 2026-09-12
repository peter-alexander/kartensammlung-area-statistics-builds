#!/usr/bin/env python3
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import io
import statistics
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.data.apps.fao.org/api/v2/bigquery"
SQL_URL = "https://data.apps.fao.org/catalog/dataset/945666e6-7803-4621-b8ef-cfd885a84596/resource/4a000a1b-24f0-4328-aab6-b9b525892090/download/query_en.sql"
USER_AGENT = "kartensammlung-area-statistics-builds/1"
CANDIDATES = {
	4192: "Dependency ratio",
	4257: "Total water withdrawal per capita",
	4254: "Agricultural water withdrawal share",
	4255: "Municipal water withdrawal share",
	4256: "Industrial water withdrawal share",
	4331: "Cultivated area equipped for irrigation",
	4328: "Equipped irrigation area actually irrigated",
	4471: "Dam capacity per capita",
	4264: "Desalinated water produced",
	4269: "Produced municipal wastewater",
	4270: "Treated municipal wastewater",
	4265: "Direct use of treated municipal wastewater",
}


def fetch_csv(variable: int, year: int | None) -> tuple[int, int | None, list[dict[str, str]], int]:
	params = {
		"area": "World",
		"download": "true",
		"sql_url": SQL_URL,
		"type": "all",
		"variable": str(variable),
	}
	if year is not None:
		params["year"] = str(year)
	url = f"{API}?{urlencode(params)}"
	req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"})
	with urlopen(req, timeout=90) as response:
		data = response.read()
	text = data.decode("utf-8-sig")
	return variable, year, list(csv.DictReader(io.StringIO(text))), len(data)


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


def describe(variable: int, label: str, rows: list[dict[str, str]], byte_count: int, year: int | None) -> None:
	print(f"\n=== {variable} {label} year={year if year is not None else 'ALL'} bytes={byte_count} ===")
	if not rows:
		print("EMPTY")
		return
	variables: dict[str, tuple[str, str]] = {}
	country_values: dict[str, list[float]] = {}
	years: set[int] = set()
	flags: dict[str, int] = {}
	for row in rows:
		code = str(row.get("VariableCode", "")).strip()
		variables[code] = (str(row.get("Variable", "")).strip(), str(row.get("Unit", "")).strip())
		year_text = str(row.get("Year", "")).strip()
		if year_text.isdigit():
			years.add(int(year_text))
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
		symbol = str(row.get("Symbol", "")).strip() or "<blank>"
		flags[symbol] = flags.get(symbol, 0) + 1
	print(f"rows={len(rows)} variables={len(variables)} years={min(years) if years else '-'}..{max(years) if years else '-'} flags={dict(sorted(flags.items()))}")
	for code in sorted(variables, key=lambda value: int(value) if value.isdigit() else 999999):
		name, unit = variables[code]
		values = country_values.get(code, [])
		if values:
			print(
				f"VAR {code} | {name} | unit={unit!r} | countryValues={len(values)} "
				f"min={min(values):.6g} q10={quantile(values, .1):.6g} q25={quantile(values, .25):.6g} "
				f"median={statistics.median(values):.6g} q75={quantile(values, .75):.6g} "
				f"q90={quantile(values, .9):.6g} max={max(values):.6g}"
			)
		else:
			print(f"VAR {code} | {name} | unit={unit!r} | countryValues=0")


def main() -> None:
	requests = [(code, 2023) for code in CANDIDATES]
	requests.append((4190, None))
	results: dict[tuple[int, int | None], tuple[list[dict[str, str]], int] | Exception] = {}
	with ThreadPoolExecutor(max_workers=4) as pool:
		future_map = {pool.submit(fetch_csv, code, year): (code, year) for code, year in requests}
		for future in as_completed(future_map):
			code, year = future_map[future]
			try:
				_, _, rows, byte_count = future.result()
				results[(code, year)] = (rows, byte_count)
			except Exception as exc:
				results[(code, year)] = exc
	for code, year in requests:
		result = results[(code, year)]
		label = CANDIDATES.get(code, "Total renewable water resources per capita")
		if isinstance(result, Exception):
			print(f"\n=== {code} {label} year={year if year is not None else 'ALL'} ===")
			print(f"ERROR {type(result).__name__}: {result}")
			continue
		rows, byte_count = result
		describe(code, label, rows, byte_count, year)


if __name__ == "__main__":
	main()
