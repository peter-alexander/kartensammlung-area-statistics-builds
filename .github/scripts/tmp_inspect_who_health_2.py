#!/usr/bin/env python3
import csv
import io
import json
import urllib.parse
import urllib.request

CSV_SOURCES = {
	"physicians": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/217795A_ALL_LATEST.csv",
	"nurses_midwives": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/5C8435F_ALL_LATEST.csv",
	"dtp3": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/F8E084C_ALL_LATEST.csv",
}

GHO_CODES = [
	"WHS8_110",
	"GHED_CHEGDP_SHA2011",
	"GHED_CHE_pc_US_SHA2011",
	"GHED_CHE_pc_PPP_SHA2011",
]


def fetch(url, accept="*/*"):
	req = urllib.request.Request(url, headers={"User-Agent": "kartensammlung-who-audit/1", "Accept": accept})
	with urllib.request.urlopen(req, timeout=120) as response:
		return response.read()


for name, url in CSV_SOURCES.items():
	raw = fetch(url, "text/csv,*/*")
	rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
	print(f"=== CSV {name}: bytes={len(raw)} rows={len(rows)} ===")
	print("fields=" + ",".join(rows[0].keys()))
	for field in rows[0].keys():
		if field.startswith("DIM_") or field.endswith("_N") or field.endswith("_NL") or field.endswith("_NU"):
			values = sorted({str(row.get(field, "")).strip() for row in rows if str(row.get(field, "")).strip()})
			if field == "DIM_TIME":
				print(f"{field}: count={len(values)} first={values[:5]} last={values[-5:]}")
			elif field.startswith("DIM_"):
				print(f"{field}: count={len(values)} values={values[:30]}")
			else:
				print(f"{field}: count={len(values)} sample={values[:10]}")
	print("sample=" + repr(rows[0]))

for code in GHO_CODES:
	url = "https://ghoapi.azureedge.net/api/" + urllib.parse.quote(code, safe="-_()")
	try:
		raw = fetch(url, "application/json,*/*")
		payload = json.loads(raw.decode("utf-8"))
		rows = payload.get("value", []) if isinstance(payload, dict) else []
		print(f"=== GHO {code}: bytes={len(raw)} rows={len(rows)} ===")
		if rows:
			print("fields=" + ",".join(rows[0].keys()))
			years = sorted({row.get("TimeDim") for row in rows if isinstance(row.get("TimeDim"), int)})
			spatial = sorted({str(row.get("SpatialDim", "")) for row in rows if row.get("SpatialDim")})
			print(f"years={years[:5]}...{years[-5:] if years else []} count={len(years)} spatial={len(spatial)}")
			print("sample=" + repr(rows[0]))
	except Exception as error:
		print(f"=== GHO {code}: ERROR {type(error).__name__}: {error} ===")
