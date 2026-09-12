#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.data.apps.fao.org/api/v2/bigquery"
SQL_URL = "https://data.apps.fao.org/catalog/dataset/945666e6-7803-4621-b8ef-cfd885a84596/resource/4a000a1b-24f0-4328-aab6-b9b525892090/download/query_en.sql"
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def fetch(variable: int, years: str) -> list[dict[str, str]]:
	params = {
		"area": "World",
		"download": "true",
		"sql_url": SQL_URL,
		"type": "all",
		"variable": str(variable),
		"year": years,
	}
	url = f"{API}?{urlencode(params)}"
	req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"})
	with urlopen(req, timeout=120) as response:
		data = response.read()
		print(f"status={response.status} bytes={len(data)} contentType={response.headers.get('content-type')}")
	return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))


def summarize(variable: int, years: str) -> None:
	print(f"\n=== variable={variable} years={years[:80]}{'...' if len(years) > 80 else ''} ===")
	try:
		rows = fetch(variable, years)
	except Exception as exc:
		print(f"ERROR {type(exc).__name__}: {exc}")
		return
	year_values = sorted({int(row["Year"]) for row in rows if str(row.get("Year", "")).isdigit()})
	codes = sorted({str(row.get("VariableCode", "")) for row in rows})
	countries = {str(row.get("m49", "")).strip() for row in rows if str(row.get("m49", "")).strip().isdigit() and str(row.get("IsAggregate", "")).lower() != "true"}
	print(f"rows={len(rows)} codes={codes} years={year_values[0] if year_values else '-'}..{year_values[-1] if year_values else '-'} yearCount={len(year_values)} countries={len(countries)}")
	print(f"yearSample={year_values[:5]} ... {year_values[-5:] if year_values else []}")


def main() -> None:
	all_years = ",".join(str(year) for year in range(1960, 2024))
	summarize(4190, all_years)
	summarize(4550, ",".join(str(year) for year in range(2000, 2024)))


if __name__ == "__main__":
	main()
