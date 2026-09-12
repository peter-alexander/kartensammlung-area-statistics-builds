#!/usr/bin/env python3
import csv
import io
import json
import math
import urllib.request
from collections import Counter

import pycountry

SERIES = {
	"physicians": {
		"kind": "csv",
		"url": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/217795A_ALL_LATEST.csv",
		"field": "RATE_PER_10000_N",
		"scale": 0.1,
		"wdi": "SH.MED.PHYS.ZS",
	},
	"nurses_midwives": {
		"kind": "csv",
		"url": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/5C8435F_ALL_LATEST.csv",
		"field": "RATE_PER_10000_N",
		"scale": 0.1,
		"wdi": "SH.MED.NUMW.P3",
	},
	"dtp3": {
		"kind": "csv",
		"url": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/F8E084C_ALL_LATEST.csv",
		"field": "RATE_PER_100_N",
		"scale": 1.0,
		"wdi": "SH.IMM.IDPT",
	},
	"measles_mcv1": {
		"kind": "gho",
		"code": "WHS8_110",
		"scale": 1.0,
		"wdi": "SH.IMM.MEAS",
	},
	"health_exp_gdp": {
		"kind": "gho",
		"code": "GHED_CHEGDP_SHA2011",
		"scale": 1.0,
		"wdi": "SH.XPD.CHEX.GD.ZS",
	},
	"health_exp_usd_pc": {
		"kind": "gho",
		"code": "GHED_CHE_pc_US_SHA2011",
		"scale": 1.0,
		"wdi": "SH.XPD.CHEX.PC.CD",
	},
}


def fetch(url, accept="*/*"):
	req = urllib.request.Request(url, headers={"User-Agent": "kartensammlung-who-audit/1", "Accept": accept})
	with urllib.request.urlopen(req, timeout=120) as response:
		return response.read()


def m49_from_iso3(iso3):
	country = pycountry.countries.get(alpha_3=iso3)
	return str(int(country.numeric)) if country else None


def name_from_m49(m49):
	country = pycountry.countries.get(numeric=str(m49).zfill(3))
	return country.name if country else "?"


def load_direct(spec):
	values = {}
	if spec["kind"] == "csv":
		raw = fetch(spec["url"], "text/csv,*/*")
		rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
		for row in rows:
			if row.get("DIM_GEO_CODE_TYPE") != "COUNTRY" or row.get("DIM_PUBLISH_STATE_CODE") != "PUBLISHED":
				continue
			m49_text = str(row.get("DIM_GEO_CODE_M49") or "").strip()
			year_text = str(row.get("DIM_TIME") or "").strip()
			value_text = str(row.get(spec["field"]) or "").strip()
			if not m49_text or not year_text.isdigit() or not value_text:
				continue
			key = (str(int(float(m49_text))), int(year_text))
			values[key] = float(value_text) * spec["scale"]
	else:
		url = "https://ghoapi.azureedge.net/api/" + spec["code"]
		payload = json.loads(fetch(url, "application/json,*/*").decode("utf-8"))
		for row in payload.get("value", []):
			if row.get("SpatialDimType") != "COUNTRY" or row.get("NumericValue") is None:
				continue
			m49 = m49_from_iso3(str(row.get("SpatialDim") or "").strip().upper())
			year = row.get("TimeDim")
			if not m49 or not isinstance(year, int):
				continue
			values[(m49, year)] = float(row["NumericValue"]) * spec["scale"]
	return values


def load_wdi(code):
	url = f"https://api.worldbank.org/v2/country/all/indicator/{code}?format=json&per_page=20000&date=1960:2026"
	payload = json.loads(fetch(url, "application/json,*/*").decode("utf-8"))
	if not isinstance(payload, list) or len(payload) < 2:
		raise RuntimeError(f"Unexpected WDI response for {code}")
	values = {}
	for row in payload[1]:
		if row.get("value") is None:
			continue
		iso3 = str(row.get("countryiso3code") or "").strip().upper()
		m49 = m49_from_iso3(iso3)
		year_text = str(row.get("date") or "").strip()
		if not m49 or not year_text.isdigit():
			continue
		values[(m49, int(year_text))] = float(row["value"])
	return values


for name, spec in SERIES.items():
	direct = load_direct(spec)
	wdi = load_wdi(spec["wdi"])
	common = sorted(set(direct) & set(wdi))
	direct_only = sorted(set(direct) - set(wdi))
	wdi_only = sorted(set(wdi) - set(direct))
	diffs = [abs(direct[key] - wdi[key]) for key in common]
	exact = sum(1 for key in common if direct[key] == wdi[key])
	tol1e9 = sum(1 for key in common if math.isclose(direct[key], wdi[key], abs_tol=1e-9, rel_tol=0.0))
	tol1e6 = sum(1 for key in common if math.isclose(direct[key], wdi[key], abs_tol=1e-6, rel_tol=0.0))
	tol005 = sum(1 for key in common if math.isclose(direct[key], wdi[key], abs_tol=0.0051, rel_tol=0.0))
	direct_years = sorted({year for _, year in direct})
	wdi_years = sorted({year for _, year in wdi})
	latest_common = max(set(direct_years) & set(wdi_years)) if set(direct_years) & set(wdi_years) else None
	print(f"=== {name} / {spec['wdi']} ===")
	print(f"direct={len(direct)} WDI={len(wdi)} common={len(common)} direct-only={len(direct_only)} WDI-only={len(wdi_only)}")
	print(f"years direct={direct_years[0]}-{direct_years[-1]} WDI={wdi_years[0]}-{wdi_years[-1]} latestCommon={latest_common}")
	if latest_common is not None:
		print(
			f"latest common coverage direct={len({m49 for m49,year in direct if year == latest_common})} "
			f"WDI={len({m49 for m49,year in wdi if year == latest_common})}"
		)
	print(
		f"exact={exact}/{len(common)} tol1e-9={tol1e9}/{len(common)} "
		f"tol1e-6={tol1e6}/{len(common)} tol0.0051={tol005}/{len(common)} "
		f"maxAbsDiff={max(diffs) if diffs else None}"
	)
	if common:
		worst = sorted(common, key=lambda key: abs(direct[key] - wdi[key]), reverse=True)[:5]
		for key in worst:
			print(f"diff {key}: direct={direct[key]} WDI={wdi[key]} abs={abs(direct[key]-wdi[key])}")
	wdi_gap = Counter(m49 for m49, _ in wdi_only)
	direct_gap = Counter(m49 for m49, _ in direct_only)
	print("WDI-only countries=" + repr([(m49, name_from_m49(m49), count) for m49, count in wdi_gap.most_common(12)]))
	print("direct-only countries=" + repr([(m49, name_from_m49(m49), count) for m49, count in direct_gap.most_common(12)]))
