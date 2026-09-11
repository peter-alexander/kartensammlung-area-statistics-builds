#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
from urllib.request import Request, urlopen

URLS = {
	"SDGIPV12M": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/F8524F2_ALL_LATEST.csv",
	"SDGIPVLT": "https://srhdpeuwpubsa.blob.core.windows.net/whdh/DATADOT/INDICATOR/E0D4E17_ALL_LATEST.csv",
}
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def main() -> None:
	for indicator, url in URLS.items():
		request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"})
		with urlopen(request, timeout=90) as response:
			data = response.read()
		text = data.decode("utf-8-sig")
		rows = list(csv.DictReader(io.StringIO(text)))
		print(f"\n{indicator}: bytes={len(data)} rows={len(rows)}")
		print(f"fields={rows[0].keys() if rows else []}")
		for row in rows[:8]:
			print(row)
		if rows:
			for field in rows[0]:
				values = sorted({str(row.get(field, '')).strip() for row in rows if str(row.get(field, '')).strip()})
				print(f"FIELD {field!r}: unique={len(values)} sample={values[:30]}")


if __name__ == "__main__":
	main()
