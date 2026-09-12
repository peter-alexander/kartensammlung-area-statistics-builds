#!/usr/bin/env python3
import csv
import io
import json
import math
import urllib.request

import pycountry

WHO = {
	"suicide.total": {
		"url": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/16BBF41_ALL_LATEST.csv",
		"sex": "TOTAL",
		"age": "TOTAL",
		"field": "RATE_PER_100000_N",
		"wdi": "SH.STA.SUIC.P5",
	},
	"suicide.male": {
		"url": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/16BBF41_ALL_LATEST.csv",
		"sex": "MALE",
		"age": "TOTAL",
		"field": "RATE_PER_100000_N",
		"wdi": "SH.STA.SUIC.MA.P5",
	},
	"suicide.female": {
		"url": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/16BBF41_ALL_LATEST.csv",
		"sex": "FEMALE",
		"age": "TOTAL",
		"field": "RATE_PER_100000_N",
		"wdi": "SH.STA.SUIC.FE.P5",
	},
	"ncd.total": {
		"url": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/1F96863_ALL_LATEST.csv",
		"sex": "TOTAL",
		"age": "YEARS30-69",
		"field": "RATE_PER_100_N",
		"wdi": "SH.DYN.NCOM.ZS",
	},
}


def fetch_bytes(url):
	req = urllib.request.Request(url, headers={"User-Agent": "kartensammlung-who-audit/1", "Accept": "*/*"})
	with urllib.request.urlopen(req, timeout=120) as response:
		return response.read()


def normalize_m49(value):
	return str(int(float(str(value).strip())))


def load_who(spec, cache):
	url = spec["url"]
	if url not in cache:
		raw = fetch_bytes(url)
		cache[url] = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
	values = {}
	for row in cache[url]:
		if row.get("DIM_GEO_CODE_TYPE") != "COUNTRY" or row.get("DIM_PUBLISH_STATE_CODE") != "PUBLISHED":
			continue
		if row.get("DIM_SEX") != spec["sex"] or row.get("DIM_AGE") != spec["age"]:
			continue
		year = int(row["DIM_TIME"])
		if not 2000 <= year <= 2021:
			continue
		m49 = normalize_m49(row["DIM_GEO_CODE_M49"])
		key = (m49, year)
		if key in values:
			raise RuntimeError(f"duplicate WHO key {key}")
		values[key] = float(row[spec["field"]])
	return values


def load_wdi(code):
	url = f"https://api.worldbank.org/v2/country/all/indicator/{code}?format=json&per_page=20000&date=2000:2021"
	payload = json.loads(fetch_bytes(url).decode("utf-8"))
	rows = payload[1]
	values = {}
	for row in rows:
		value = row.get("value")
		iso3 = str(row.get("countryiso3code") or "").strip().upper()
		if value is None or not iso3:
			continue
		country = pycountry.countries.get(alpha_3=iso3)
		if country is None:
			continue
		m49 = normalize_m49(country.numeric)
		year = int(row["date"])
		values[(m49, year)] = float(value)
	return values


cache = {}
for name, spec in WHO.items():
	who = load_who(spec, cache)
	wdi = load_wdi(spec["wdi"])
	common = sorted(set(who) & set(wdi))
	who_only = sorted(set(who) - set(wdi))
	wdi_only = sorted(set(wdi) - set(who))
	diffs = [abs(who[key] - wdi[key]) for key in common]
	exact = sum(1 for key in common if who[key] == wdi[key])
	round1 = sum(1 for key in common if round(who[key], 1) == round(wdi[key], 1))
	tol001 = sum(1 for key in common if math.isclose(who[key], wdi[key], abs_tol=0.001, rel_tol=0.0))
	latest_year = max(year for _, year in set(who) | set(wdi))
	who_latest = len({m49 for m49, year in who if year == latest_year})
	wdi_latest = len({m49 for m49, year in wdi if year == latest_year})
	print(f"=== {name} / {spec['wdi']} ===")
	print(f"WHO={len(who)} WDI={len(wdi)} common={len(common)} WHO-only={len(who_only)} WDI-only={len(wdi_only)}")
	print(f"years WHO={min(y for _,y in who)}-{max(y for _,y in who)} WDI={min(y for _,y in wdi)}-{max(y for _,y in wdi)}")
	print(f"latest={latest_year} WHO countries={who_latest} WDI countries={wdi_latest}")
	print(f"exact={exact}/{len(common)} round1={round1}/{len(common)} tol0.001={tol001}/{len(common)} maxAbsDiff={max(diffs) if diffs else None}")
	if common:
		worst = sorted(common, key=lambda key: abs(who[key] - wdi[key]), reverse=True)[:10]
		for key in worst:
			print(f"diff {key}: WHO={who[key]} WDI={wdi[key]} abs={abs(who[key]-wdi[key])}")
	print(f"WHO-only sample={who_only[:20]}")
	print(f"WDI-only sample={wdi_only[:20]}")
