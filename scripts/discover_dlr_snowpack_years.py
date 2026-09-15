#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "dlr-snowpack-indicators.json"
YEAR_HREF_RE = re.compile(r'href=["\'](?:\./)?(\d{4})/["\']', re.IGNORECASE)
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Discover complete DLR Global SnowPack yearly SCD directories.")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--github-output", type=Path)
	return parser.parse_args()


def fetch_text(url: str) -> str:
	last_error: Exception | None = None
	for attempt, delay in enumerate((0, 5, 15, 30), start=1):
		if delay:
			time.sleep(delay)
		request = Request(url, headers={"User-Agent": USER_AGENT})
		try:
			with urlopen(request, timeout=30) as response:
				return response.read().decode("utf-8", errors="replace")
		except (HTTPError, URLError, TimeoutError) as error:
			last_error = error
			print(f"DLR directory request failed ({attempt}/4): {error}", flush=True)
	if last_error is None:
		raise RuntimeError("DLR directory request failed without an exception.")
	raise RuntimeError("DLR directory request failed after 4 attempts.") from last_error


def main() -> int:
	args = parse_args()
	config = json.loads(args.config.read_text(encoding="utf-8"))
	if config.get("schema") != "kartensammlung.dlr-snowpack-statistics/v1":
		raise ValueError("Invalid DLR SnowPack config.")
	base = str(config["downloadBase"]).rstrip("/") + "/"
	start_year = int(config["startYear"])
	minimum_latest_year = int(config["minimumLatestYear"])
	html = fetch_text(base)
	years = sorted({int(match) for match in YEAR_HREF_RE.findall(html) if int(match) >= start_year})
	if not years:
		raise RuntimeError(f"No SnowPack year directories found at {base}")
	latest = years[-1]
	if latest < minimum_latest_year:
		raise RuntimeError(
			f"Latest SnowPack year {latest} is older than required minimum {minimum_latest_year}."
		)
	expected = list(range(start_year, latest + 1))
	if years != expected:
		raise RuntimeError(f"SnowPack year directory sequence is not contiguous: {years}")

	matrix_json = json.dumps(years, separators=(",", ":"))
	print(f"DLR Global SnowPack years: {years[0]}-{latest} ({len(years)})")
	if args.github_output:
		with args.github_output.open("a", encoding="utf-8") as handle:
			handle.write(f"years={matrix_json}\n")
			handle.write(f"latest={latest}\n")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
