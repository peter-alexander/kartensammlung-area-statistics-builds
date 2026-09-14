#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://wid.world/bulk_download"
COUNTRIES = ["AT", "US", "FR", "DE", "BR", "ZA", "IN", "CN"]
TARGET_CONCEPTS = ("ptinc", "hweal")
TARGET_PERCENTILES = {"p0p50", "p50p90", "p90p100", "p99p100"}


def fetch(url: str) -> tuple[bytes, str, dict[str, str]]:
	request = Request(url, headers={"User-Agent": "kartensammlung-wid-source-audit/1"})
	with urlopen(request, timeout=90) as response:
		return (
			response.read(),
			response.geturl(),
			{key.lower(): value for key, value in response.headers.items()},
		)


def normalize_variable(variable: str) -> str:
	# WID's own bulk-downloader currently rewrites website codes by moving the
	# population-unit letter behind the age code. Keep both raw and normalized
	# forms visible during this audit rather than assuming one convention.
	return re.sub(r"(.*?)([a-z])([0-9]+)$", r"\1\3\2", variable)


def parse(raw: bytes) -> list[dict[str, str]]:
	text = raw.decode("utf-8-sig")
	reader = csv.DictReader(io.StringIO(text), delimiter=";")
	rows = list(reader)
	if reader.fieldnames is None:
		raise RuntimeError("WID CSV has no header")
	print(f"columns={reader.fieldnames}")
	return rows


def target_kind(variable: str) -> str | None:
	for concept in TARGET_CONCEPTS:
		if concept in variable:
			return concept
	return None


def quality_label(value: str | None) -> str:
	label = (value or "").strip()
	return label if label else "<empty>"


def main() -> None:
	for country in COUNTRIES:
		url = f"{BASE_URL}/WID_data_{country}.csv"
		print(f"\n===== {country} =====")
		print(f"url={url}")
		try:
			raw, effective_url, headers = fetch(url)
		except (HTTPError, URLError, TimeoutError, OSError) as error:
			print(f"ERROR {type(error).__name__}: {error}")
			continue
		print(f"effective={effective_url}")
		print(f"bytes={len(raw)} content-type={headers.get('content-type')} last-modified={headers.get('last-modified')} etag={headers.get('etag')}")
		rows = parse(raw)
		print(f"rows={len(rows)}")
		print(f"firstRows={rows[:3]!r}")

		raw_variables = Counter(row.get("variable", "") for row in rows)
		normalized_variables = Counter(normalize_variable(value) for value in raw_variables if value)
		print(f"variableCountRaw={len(raw_variables)} variableCountNormalized={len(normalized_variables)}")
		print("targetVariableCandidatesRaw=" + repr(sorted(value for value in raw_variables if target_kind(value))))
		print("targetVariableCandidatesNormalized=" + repr(sorted(value for value in normalized_variables if target_kind(value))))

		matches: dict[tuple[str, str], list[tuple[int, float, str, str]]] = defaultdict(list)
		target_quality = Counter()
		for row in rows:
			raw_variable = row.get("variable", "")
			variable = normalize_variable(raw_variable)
			concept = target_kind(variable)
			percentile = row.get("percentile", "")
			if concept is None or percentile not in TARGET_PERCENTILES:
				continue
			if not variable.startswith("s"):
				continue
			if "992j" not in variable:
				continue
			try:
				year = int(row["year"])
				value = float(row["value"])
			except (KeyError, TypeError, ValueError):
				continue
			quality = quality_label(row.get("data_quality"))
			target_quality[quality] += 1
			matches[(concept, percentile)].append((year, value, raw_variable, quality))

		print(f"targetDataQuality={dict(sorted(target_quality.items()))}")
		for concept in TARGET_CONCEPTS:
			for percentile in sorted(TARGET_PERCENTILES):
				values = sorted(matches.get((concept, percentile), []))
				if not values:
					print(f"{concept} {percentile}: MISSING")
					continue
				years = [item[0] for item in values]
				quality_counts = Counter(item[3] for item in values)
				print(
					f"{concept} {percentile}: observations={len(values)} years={min(years)}..{max(years)} "
					f"latest={values[-1][0]}:{values[-1][1]} rawVariable={values[-1][2]} "
					f"latestQuality={values[-1][3]} quality={dict(sorted(quality_counts.items()))}"
				)

		unexpected_columns = sorted(
			set(rows[0]) - {"country", "variable", "percentile", "year", "value", "age", "pop"}
		) if rows else []
		print(f"unexpectedColumns={unexpected_columns}")

	for name in ("WID_metadata_AT.csv", "WID_metadata_US.csv", "WID_metadata.csv", "WID_countries.csv"):
		url = f"{BASE_URL}/{name}"
		print(f"\n===== metadata probe {name} =====")
		try:
			raw, effective_url, headers = fetch(url)
			print(f"OK effective={effective_url} bytes={len(raw)} content-type={headers.get('content-type')} preview={raw[:300]!r}")
		except (HTTPError, URLError, TimeoutError, OSError) as error:
			print(f"ERROR {type(error).__name__}: {error}")


if __name__ == "__main__":
	main()
