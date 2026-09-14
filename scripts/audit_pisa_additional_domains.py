#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import io
import zipfile
from urllib.request import Request, urlopen

from openpyxl import load_workbook

# Temporary source audit. Remove this file before the production PR.
SOURCES = {
	"pisa-2025-core-and-digital": "https://stat.link/mrq53f",
	"pisa-2022-financial-literacy": "https://stat.link/4nx1lb",
	"pisa-2022-creative-thinking": "https://stat.link/opbe7a",
	"pisa-2018-global-competence": "https://doi.org/10.1787/888934171229",
	"pisa-2015-collaborative-problem-solving": "https://doi.org/10.1787/888933616769",
	"pisa-2012-creative-problem-solving": "https://doi.org/10.1787/888933003573",
	"pisa-2009-digital-reading": "https://doi.org/10.1787/888932436689",
	"pisa-2003-cross-curricular-problem-solving": "https://doi.org/10.1787/402381481733",
}


def fetch(url: str) -> tuple[bytes, str, str]:
	request = Request(url, headers={"User-Agent": "kartensammlung-pisa-source-audit/1"})
	with urlopen(request, timeout=120) as response:
		return response.read(), response.geturl(), response.headers.get("Content-Type", "")


def preview_xlsx(raw: bytes) -> None:
	workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
	print("sheets:")
	for sheet_name in workbook.sheetnames:
		sheet = workbook[sheet_name]
		print(f"  - {sheet_name!r}: {sheet.max_row}x{sheet.max_column}")
		shown = 0
		for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
			values = [value for value in row if value not in (None, "")]
			if not values:
				continue
			print(f"      row {row_number}: {values[:12]!r}")
			shown += 1
			if shown >= 8:
				break


def main() -> None:
	for name, url in SOURCES.items():
		print(f"\n===== {name} =====")
		print(f"requested: {url}")
		try:
			raw, effective_url, content_type = fetch(url)
		except Exception as error:
			print(f"ERROR: {type(error).__name__}: {error}")
			continue
		print(f"effective: {effective_url}")
		print(f"content-type: {content_type}")
		print(f"bytes: {len(raw)}")
		print(f"sha256: {hashlib.sha256(raw).hexdigest()}")
		print(f"magic: {raw[:16]!r}")
		if raw.startswith(b"PK") and zipfile.is_zipfile(io.BytesIO(raw)):
			try:
				preview_xlsx(raw)
			except Exception as error:
				print(f"XLSX ERROR: {type(error).__name__}: {error}")
		else:
			print(f"text-preview: {raw[:500]!r}")


if __name__ == "__main__":
	main()
