#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from urllib.request import Request, urlopen

import duckdb
import pycountry

STAC_URL = "https://stac.overturemaps.org/catalog.json"
S3_BASE = "s3://overturemaps-us-west-2/release"
RELEASE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Inspect Overture country/dependency coverage before defining Kartensammlung crosswalks."
	)
	parser.add_argument("--release", default="latest")
	return parser.parse_args()


def validate_release(value: str) -> str:
	release = str(value or "").strip().rstrip("/")
	if not RELEASE_RE.fullmatch(release):
		raise ValueError(f"Invalid Overture release: {release!r}")
	return release


def resolve_latest_release() -> str:
	request = Request(
		STAC_URL,
		headers={"User-Agent": "kartensammlung-area-statistics-builds/1"},
	)
	with urlopen(request, timeout=30) as response:
		payload = json.load(response)
	return validate_release(payload.get("latest", ""))


def main() -> int:
	args = parse_args()
	release = resolve_latest_release() if args.release == "latest" else validate_release(args.release)
	division_path = f"{S3_BASE}/{release}/theme=divisions/type=division/*.parquet"
	area_path = f"{S3_BASE}/{release}/theme=divisions/type=division_area/*.parquet"

	connection = duckdb.connect()
	connection.execute("INSTALL httpfs;")
	connection.execute("LOAD httpfs;")
	connection.execute("SET s3_region='us-west-2';")

	synthetic_rows = connection.execute(
		f"""
		WITH division_rows AS (
			SELECT
				country AS code,
				names.primary AS name,
				wikidata,
				id AS overture_id,
				perspectives IS NOT NULL AS has_perspective
			FROM read_parquet('{division_path}', hive_partitioning=1)
			WHERE subtype = 'country' AND country LIKE 'X%'
		),
		area_counts AS (
			SELECT
				division_id,
				COUNT(*) FILTER (WHERE is_land = TRUE) AS land_areas,
				COUNT(*) AS all_areas
			FROM read_parquet('{area_path}', hive_partitioning=1)
			WHERE subtype = 'country'
			GROUP BY division_id
		)
		SELECT
			d.code,
			d.name,
			d.wikidata,
			d.overture_id,
			d.has_perspective,
			COALESCE(a.land_areas, 0) AS land_areas,
			COALESCE(a.all_areas, 0) AS all_areas
		FROM division_rows d
		LEFT JOIN area_counts a ON a.division_id = d.overture_id
		ORDER BY d.code, d.has_perspective, d.name, d.overture_id;
		"""
	).fetchall()

	dependency_rows = connection.execute(
		f"""
		WITH dependency_rows AS (
			SELECT
				country AS code,
				names.primary AS name,
				wikidata,
				id AS overture_id,
				parent_division_id,
				perspectives IS NOT NULL AS has_perspective,
				ROW_NUMBER() OVER (
					PARTITION BY country
					ORDER BY CASE WHEN perspectives IS NULL THEN 0 ELSE 1 END, id
				) AS choice_rank
			FROM read_parquet('{division_path}', hive_partitioning=1)
			WHERE subtype = 'dependency'
		),
		area_counts AS (
			SELECT
				division_id,
				COUNT(*) FILTER (WHERE is_land = TRUE) AS land_areas,
				COUNT(*) AS all_areas
			FROM read_parquet('{area_path}', hive_partitioning=1)
			WHERE subtype = 'dependency'
			GROUP BY division_id
		)
		SELECT
			d.code,
			d.name,
			d.wikidata,
			d.overture_id,
			d.parent_division_id,
			d.has_perspective,
			COALESCE(a.land_areas, 0) AS land_areas,
			COALESCE(a.all_areas, 0) AS all_areas
		FROM dependency_rows d
		LEFT JOIN area_counts a ON a.division_id = d.overture_id
		WHERE d.choice_rank = 1
		ORDER BY d.code;
		"""
	).fetchall()

	covered_rows = connection.execute(
		f"""
		SELECT DISTINCT country
		FROM read_parquet('{division_path}', hive_partitioning=1)
		WHERE subtype IN ('country', 'dependency');
		"""
	).fetchall()
	connection.close()

	iso_codes = {country.alpha_2.upper() for country in pycountry.countries}
	covered_codes = {row[0] for row in covered_rows if row[0]}
	missing_iso_codes = sorted(iso_codes - covered_codes)

	print(f"Overture release: {release}")
	print("Synthetic Overture country codes:")
	for code, name, wikidata, overture_id, has_perspective, land_areas, all_areas in synthetic_rows:
		print(
			f"{code}\t{name}\twikidata={wikidata or '-'}\t"
			f"perspective={'yes' if has_perspective else 'no'}\t"
			f"land_areas={land_areas}\tall_areas={all_areas}\t{overture_id}"
		)

	print(f"Dependencies: {len(dependency_rows)}")
	for code, name, wikidata, overture_id, parent_id, has_perspective, land_areas, all_areas in dependency_rows:
		print(
			f"dependency\t{code}\t{name}\twikidata={wikidata or '-'}\t"
			f"perspective={'yes' if has_perspective else 'no'}\t"
			f"land_areas={land_areas}\tall_areas={all_areas}\t"
			f"parent={parent_id or '-'}\t{overture_id}"
		)

	print(f"ISO-3166-1 codes not covered by country/dependency: {len(missing_iso_codes)}")
	print("missing_iso2=" + ",".join(missing_iso_codes))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
