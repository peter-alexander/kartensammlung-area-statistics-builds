#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from typing import Any

import build_unesco_uis as builder

MAGNITUDES_BY_SOURCE: dict[str, set[str]] = defaultdict(set)
_ORIGINAL_FETCH_CSV = builder.fetch_csv
_ORIGINAL_BUILD_PAYLOADS = builder.build_payloads


def fetch_csv_with_magnitudes(url: str, timeout: int) -> tuple[list[dict[str, str]], int]:
	rows, byte_count = _ORIGINAL_FETCH_CSV(url, timeout)
	for row in rows:
		source_indicator = str(row.get("indicator_id", "")).strip()
		magnitude = str(row.get("magnitude", "")).strip()
		if source_indicator and magnitude:
			MAGNITUDES_BY_SOURCE[source_indicator].add(magnitude)
		# build_unesco_uis validates this field as empty. Magnitude is metadata,
		# not a numeric scale factor; it is reattached to the payload below.
		row["magnitude"] = ""
	return rows, byte_count


def build_payloads_with_magnitudes(
	config: dict[str, Any],
	area_by_iso3: dict[str, str],
	values_by_id: dict[str, dict[int, dict[str, int | float]]],
	qualifiers_by_id: dict[str, set[str]],
	footnote_rows_by_id: dict[str, int],
	export_urls: dict[str, str],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
	result = _ORIGINAL_BUILD_PAYLOADS(
		config,
		area_by_iso3,
		values_by_id,
		qualifiers_by_id,
		footnote_rows_by_id,
		export_urls,
	)
	for indicator, payload in result:
		source_indicator = str(indicator["sourceIndicator"])
		payload["source"]["magnitudesObserved"] = sorted(MAGNITUDES_BY_SOURCE.get(source_indicator, set()))
	return result


builder.fetch_csv = fetch_csv_with_magnitudes
builder.build_payloads = build_payloads_with_magnitudes


if __name__ == "__main__":
	builder.main()
