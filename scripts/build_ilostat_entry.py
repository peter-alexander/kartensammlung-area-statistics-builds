#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

import build_ilostat as builder

_ORIGINAL_LOAD_SOURCE_ROWS = builder.load_source_rows


def load_source_rows_without_channel_islands(
	config: dict[str, Any],
	timeout: int,
):
	rows_by_dataset, urls = _ORIGINAL_LOAD_SOURCE_ROWS(config, timeout)
	removed = 0
	for dataset_id, rows in rows_by_dataset.items():
		filtered = [row for row in rows if str(row.get("ref_area", "")).strip().upper() != "CHA"]
		removed_here = len(rows) - len(filtered)
		if removed_here:
			print(f"ILOSTAT {dataset_id}: ignored {removed_here} Channel Islands aggregate rows (CHA)")
			removed += removed_here
		rows_by_dataset[dataset_id] = filtered
	if not removed:
		print("ILOSTAT Channel Islands aggregate (CHA) not present in selected source datasets.")
	return rows_by_dataset, urls


builder.load_source_rows = load_source_rows_without_channel_islands


if __name__ == "__main__":
	builder.main()
