#!/usr/bin/env python3
import csv
import io
import json
import math
import urllib.request
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

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


def m49_name(m49):
	country = pycountry.countries.get(numeric=str(m49).zfill(3))
	return country.name if country else "?"


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


def round2_half_up(value):
	return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


cache = {}
for name, spec in WHO.items():
	who = load_who(spec, cache)
	wdi = load_wdi(spec["wdi"])
	common = sorted(set(who) & set(wdi))
	who_only = sorted(set(who) - set(wdi))
	wdi_only = sorted(set(wdi) - set(who))
	diffs = [abs(who[key] - wdi[key]) for key in common]
	exact = sum(1 for key in common if who[key] == wdi[key])
	round2 = sum(1 for key in common if round2_half_up(who[key]) == Decimal(str(wdi[key])).quantize(Decimal("0.01")))
	tol00051 = sum(1 for key in common if math.isclose(who[key], wdi[key], abs_tol=0.0051, rel_tol=0.0))
	latest_year = max(year for _, year in set(who) | set(wdi))
	who_latest = len({m49 for m49, year in who if year == latest_year})
	wdi_latest = len({m49 for m49, year in wdi if year == latest_year})
	print(f"=== {name} / {spec['wdi']} ===")
	print(f"WHO={len(who)} WDI={len(wdi)} common={len(common)} WHO-only={len(who_only)} WDI-only={len(wdi_only)}")
	print(f"years WHO={min(y for _,y in who)}-{max(y for _,y in who)} WDI={min(y for _,y in wdi)}-{max(y for _,y in wdi)}")
	print(f"latest={latest_year} WHO countries={who_latest} WDI countries={wdi_latest}")
	print(f"exact={exact}/{len(common)} round2-half-up={round2}/{len(common)} tol0.0051={tol00051}/{len(common)} maxAbsDiff={max(diffs) if diffs else None}")
	wdi_gap_counts = Counter(m49 for m49, _ in wdi_only)
	who_gap_counts = Counter(m49 for m49, _ in who_only)
	print("WDI-only countries=" + repr([(m49, m49_name(m49), count) for m49, count in sorted(wdi_gap_counts.items())]))
	print("WHO-only countries=" + repr([(m49, m49_name(m49), count) for m49, count in sorted(who_gap_counts.items())]))
	if common:
		worst = sorted(common, key=lambda key: abs(who[key] - wdi[key]), reverse=True)[:5]
		for key in worst:
			print(f"diff {key}: WHO={who[key]} WDI={wdi[key]} abs={abs(who[key]-wdi[key])}")
