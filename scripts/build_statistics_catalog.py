#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "statistics-providers.json"
DEFAULT_OUTPUT = ROOT / "dist" / "statistics" / "index.json"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build the global statistics provider catalog without rebuilding provider data."
	)
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
	return parser.parse_args()


def read_json(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def validate_catalog(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict) or payload.get("schema") != "kartensammlung.statistics-providers/v1":
		raise ValueError("Invalid statistics provider catalog schema.")

	providers = payload.get("providers")
	if not isinstance(providers, list) or not providers:
		raise ValueError("Statistics provider catalog must contain at least one provider.")

	ids: set[str] = set()
	indexes: set[str] = set()
	for provider in providers:
		if not isinstance(provider, dict):
			raise ValueError("Statistics provider entries must be objects.")
		provider_id = str(provider.get("id", "")).strip()
		name = str(provider.get("name", "")).strip()
		index = str(provider.get("index", "")).strip()
		if not provider_id or not name or not index:
			raise ValueError("Statistics provider entry requires id, name and index.")
		if provider_id in ids:
			raise ValueError(f"Duplicate statistics provider id: {provider_id}")
		if index in indexes:
			raise ValueError(f"Duplicate statistics provider index: {index}")
		if index.startswith("/") or ".." in Path(index).parts or not index.endswith("/index.json"):
			raise ValueError(f"Invalid statistics provider index path: {index}")
		ids.add(provider_id)
		indexes.add(index)

	return payload


def build_index(catalog: dict[str, Any]) -> dict[str, Any]:
	return {
		"schema": "kartensammlung.statistics-index/v1",
		"areaRegistry": "../area-registry-countries.json",
		"providers": catalog["providers"],
	}


def write_json(path: Path, payload: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		json.dumps(payload, ensure_ascii=False, indent="\t") + "\n",
		encoding="utf-8",
	)


def main() -> None:
	args = parse_args()
	catalog = validate_catalog(read_json(args.config))
	index = build_index(catalog)
	write_json(args.output, index)
	print(f"Built statistics catalog with {len(index['providers'])} providers: {args.output}")


if __name__ == "__main__":
	main()
