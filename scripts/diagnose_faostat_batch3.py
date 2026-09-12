#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import math
from urllib.request import Request, urlopen
import zipfile

REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
SOURCES = {
	"production-indices": "https://bulks-faostat.fao.org/production/Production_Indices_E_All_Data_(Normalized).zip",
	"livestock-patterns": "https://bulks-faostat.fao.org/production/Environment_LivestockPatterns_E_All_Data_(Normalized).zip",
	"pesticides-use": "https://bulks-faostat.fao.org/production/Inputs_Pesticides_Use_E_All_Data_(Normalized).zip",
	"emissions-indicators": "https://bulks-faostat.fao.org/production/Climate_change_Emissions_indicators_E_All_Data_(Normalized).zip",
}
SERIES = [
	("production.agriculture-index", "production-indices", {"Item Code":"2051", "Element Code":"432"}),
	("production.food-per-capita-index", "production-indices", {"Item Code":"2054", "Element Code":"434"}),
	("livestock.livestock-units-per-agricultural-land", "livestock-patterns", {"Item Code":"1752", "Element Code":"7213"}),
	("inputs.pesticides-per-cropland", "pesticides-use", {"Item Code":"1357", "Element Code":"5159"}),
	("emissions.agrifood-per-capita", "emissions-indicators", {"Item Code":"6518", "Element Code":"7279"}),
	("emissions.agrifood-share-national", "emissions-indicators", {"Item Code":"6518", "Element Code":"726313"}),
	("emissions.farm-gate-per-production-value", "emissions-indicators", {"Item Code":"6996", "Element Code":"72791"}),
]


def fetch(url: str) -> bytes:
	req = Request(url, headers={"User-Agent":"kartensammlung-area-statistics-builds/1"})
	with urlopen(req, timeout=180) as r:
		return r.read()


def decode(data: bytes) -> str:
	for enc in ("utf-8-sig", "cp1252", "latin-1"):
		try:
			return data.decode(enc)
		except UnicodeDecodeError:
			pass
	raise RuntimeError("decode failed")


def norm_m49(raw: str) -> str:
	v = str(raw or "").strip().lstrip("'")
	return v.zfill(3) if v.isdigit() else ""


def quantile(values: list[float], q: float) -> float:
	values = sorted(values)
	if not values:
		return math.nan
	if len(values) == 1:
		return values[0]
	pos = q * (len(values) - 1)
	lo = math.floor(pos); hi = math.ceil(pos)
	if lo == hi:
		return values[lo]
	weight = pos - lo
	return values[lo] * (1 - weight) + values[hi] * weight


def main() -> None:
	registry = json.loads(fetch(REGISTRY_URL))
	valid_m49 = {str(a.get("codes",{}).get("m49","")) for a in registry.get("areas",[]) if a.get("level")=="country" and a.get("codes",{}).get("m49")}
	by_source: dict[str, list[tuple[str, dict[str,str]]]] = {}
	for indicator_id, source_id, filters in SERIES:
		by_source.setdefault(source_id, []).append((indicator_id, filters))

	results = {
		indicator_id: {"latest": None, "latestValues": {}, "allValues": [], "years": set(), "units": set(), "anyAreas": set()}
		for indicator_id, _, _ in SERIES
	}

	for source_id, url in SOURCES.items():
		blob = fetch(url)
		with zipfile.ZipFile(io.BytesIO(blob)) as zf:
			csv_names = [n for n in zf.namelist() if n.endswith("All_Data_(Normalized).csv")]
			if len(csv_names) != 1:
				raise RuntimeError(f"{source_id}: expected one normalized CSV")
			print(f"SOURCE {source_id} bytes={len(blob)} file={csv_names[0]}")
			print("ZIP", ", ".join(zf.namelist()))
			reader = csv.DictReader(io.StringIO(decode(zf.read(csv_names[0]))))
			series = by_source.get(source_id, [])
			for row in reader:
				matched = []
				for indicator_id, filters in series:
					if all(str(row.get(k, "")).strip() == v for k, v in filters.items()):
						matched.append(indicator_id)
				if not matched:
					continue
				m49 = norm_m49(row.get("Area Code (M49)", ""))
				if m49 not in valid_m49:
					continue
				year_text = str(row.get("Year", "")).strip()
				value_text = str(row.get("Value", "")).strip()
				if not year_text.isdigit() or not value_text:
					continue
				try:
					value = float(value_text)
				except ValueError:
					continue
				if not math.isfinite(value):
					continue
				year = int(year_text)
				for indicator_id in matched:
					res = results[indicator_id]
					res["years"].add(year)
					res["units"].add(str(row.get("Unit", "")).strip())
					res["anyAreas"].add(m49)
					res["allValues"].append(value)
					if res["latest"] is None or year > res["latest"]:
						res["latest"] = year
						res["latestValues"] = {}
					if year == res["latest"]:
						res["latestValues"][m49] = value

	for indicator_id, _, filters in SERIES:
		res = results[indicator_id]
		latest_values = list(res["latestValues"].values())
		all_values = res["allValues"]
		qs = {f"q{int(q*100):02d}": quantile(latest_values, q) for q in (0.05,0.10,0.25,0.50,0.75,0.90,0.95)}
		print("\nSERIES", indicator_id)
		print("FILTERS", filters)
		print(f"unit={sorted(res['units'])} years={min(res['years'])}-{max(res['years'])} latest={res['latest']} anyAreas={len(res['anyAreas'])} latestAreas={len(latest_values)}")
		print(f"allMin={min(all_values):.8g} allMax={max(all_values):.8g} latestMin={min(latest_values):.8g} latestMax={max(latest_values):.8g}")
		print("QUANTILES", " ".join(f"{k}={v:.8g}" for k,v in qs.items()))
		neg = sum(v < 0 for v in latest_values); zero = sum(v == 0 for v in latest_values); pos = sum(v > 0 for v in latest_values)
		print(f"SIGNS negative={neg} zero={zero} positive={pos}")


if __name__ == "__main__":
	main()
