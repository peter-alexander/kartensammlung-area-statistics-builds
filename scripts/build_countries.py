#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import duckdb
import pycountry

ROOT = Path(__file__).resolve().parents[1]
STAC_URL = "https://stac.overturemaps.org/catalog.json"
S3_BASE = "s3://overturemaps-us-west-2/release"
RELEASE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")
ATTRIBUTION = "© OpenStreetMap contributors, Overture Maps Foundation"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Build country polygons, label points and the country area registry from Overture Maps."
	)
	parser.add_argument(
		"--release",
		default="latest",
		help="Overture release such as 2026-08-19.0. Default: resolve latest from the STAC catalog.",
	)
	parser.add_argument(
		"--output-dir",
		type=Path,
		default=ROOT / "dist",
		help="Directory for world-admin.pmtiles, registry and metadata.",
	)
	parser.add_argument(
		"--work-dir",
		type=Path,
		default=ROOT / "build" / "country-geometry",
		help="Directory for temporary GeoJSONSeq files.",
	)
	parser.add_argument(
		"--tippecanoe",
		default="tippecanoe",
		help="Tippecanoe executable.",
	)
	parser.add_argument(
		"--skip-tiles",
		action="store_true",
		help="Only extract and validate Overture data; do not run Tippecanoe.",
	)
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


def load_country_codes() -> dict[str, str]:
	codes = {
		country.alpha_2.upper(): country.alpha_3.upper()
		for country in pycountry.countries
	}
	override_path = ROOT / "config" / "country-code-overrides.json"
	overrides = json.loads(override_path.read_text(encoding="utf-8"))

	for raw_iso2, entry in overrides.items():
		iso2 = str(raw_iso2).strip().upper()
		iso3 = str(entry.get("iso3", "")).strip().upper()
		if len(iso2) != 2 or len(iso3) != 3:
			raise ValueError(f"Invalid country code override: {raw_iso2!r} -> {iso3!r}")
		codes[iso2] = iso3

	return codes


def load_excluded_overture_country_codes() -> set[str]:
	policy_path = ROOT / "config" / "overture-excluded-country-codes.json"
	payload = json.loads(policy_path.read_text(encoding="utf-8"))
	codes = {
		str(code).strip().upper()
		for code in payload.get("codes", [])
		if str(code).strip()
	}
	if not codes:
		raise ValueError("Overture excluded-country policy must contain at least one code.")
	if any(len(code) != 2 for code in codes):
		raise ValueError("Overture excluded-country codes must be two characters long.")
	return codes


def open_duckdb() -> duckdb.DuckDBPyConnection:
	connection = duckdb.connect()
	connection.execute("INSTALL spatial;")
	connection.execute("LOAD spatial;")
	connection.execute("INSTALL httpfs;")
	connection.execute("LOAD httpfs;")
	connection.execute("SET s3_region='us-west-2';")
	return connection


def create_iso_table(connection: duckdb.DuckDBPyConnection, codes: dict[str, str]) -> None:
	connection.execute("CREATE TEMP TABLE iso_codes (iso2 VARCHAR PRIMARY KEY, iso3 VARCHAR NOT NULL);")
	connection.executemany(
		"INSERT INTO iso_codes VALUES (?, ?);",
		sorted(codes.items()),
	)


def validate_overture_country_policy(
	connection: duckdb.DuckDBPyConnection,
	excluded_codes: set[str],
) -> list[dict[str, str | None]]:
	unknown_rows = connection.execute(
		"""
		SELECT
			d.iso2,
			d.name,
			d.wikidata,
			d.overture_id
		FROM country_divisions d
		LEFT JOIN iso_codes c USING (iso2)
		WHERE c.iso3 IS NULL
		ORDER BY d.iso2;
		"""
	).fetchall()
	observed_codes = {row[0] for row in unknown_rows}
	unexpected_codes = sorted(observed_codes - excluded_codes)
	missing_expected_codes = sorted(excluded_codes - observed_codes)

	if unexpected_codes:
		details = ", ".join(
			f"{code} ({name or 'unnamed'}, {wikidata or 'no Wikidata'})"
			for code, name, wikidata, _ in unknown_rows
			if code in unexpected_codes
		)
		raise RuntimeError(
			"New or unreviewed Overture country code(s) require an explicit policy decision: "
			+ details
		)

	if missing_expected_codes:
		raise RuntimeError(
			"Reviewed Overture synthetic country code(s) disappeared or became ISO-compatible; "
			"review the policy before continuing: "
			+ ", ".join(missing_expected_codes)
		)

	return [
		{
			"code": code,
			"name": name,
			"wikidata": wikidata,
			"overtureId": overture_id,
		}
		for code, name, wikidata, overture_id in unknown_rows
	]


def create_country_tables(
	connection: duckdb.DuckDBPyConnection,
	release: str,
	excluded_codes: set[str],
) -> tuple[dict[str, int], list[dict[str, str | None]]]:
	division_path = f"{S3_BASE}/{release}/theme=divisions/type=division/*.parquet"
	area_path = f"{S3_BASE}/{release}/theme=divisions/type=division_area/*.parquet"

	connection.execute(
		f"""
		CREATE TEMP TABLE country_divisions AS
		SELECT
			overture_id,
			iso2,
			name,
			wikidata,
			label_geometry,
			has_perspective
		FROM (
			SELECT
				id AS overture_id,
				country AS iso2,
				names.primary AS name,
				wikidata,
				geometry AS label_geometry,
				perspectives IS NOT NULL AS has_perspective,
				ROW_NUMBER() OVER (
					PARTITION BY country
					ORDER BY
						CASE WHEN perspectives IS NULL THEN 0 ELSE 1 END,
						id
				) AS choice_rank
			FROM read_parquet('{division_path}', hive_partitioning=1)
			WHERE subtype = 'country'
		)
		WHERE choice_rank = 1;
		"""
	)

	excluded_entities = validate_overture_country_policy(connection, excluded_codes)

	connection.execute(
		"""
		CREATE TEMP TABLE statistics_country_divisions AS
		SELECT d.*
		FROM country_divisions d
		INNER JOIN iso_codes c USING (iso2);
		"""
	)

	connection.execute(
		f"""
		CREATE TEMP TABLE country_areas AS
		SELECT
			d.overture_id,
			d.iso2,
			d.name,
			d.wikidata,
			a.geometry
		FROM read_parquet('{area_path}', hive_partitioning=1) a
		INNER JOIN statistics_country_divisions d
			ON a.division_id = d.overture_id
		WHERE
			a.subtype = 'country'
			AND a.is_land = TRUE;
		"""
	)

	duplicate_areas = connection.execute(
		"""
		SELECT iso2, COUNT(*) AS area_count
		FROM country_areas
		GROUP BY iso2
		HAVING COUNT(*) <> 1
		ORDER BY iso2;
		"""
	).fetchall()
	if duplicate_areas:
		details = ", ".join(f"{iso2}={count}" for iso2, count in duplicate_areas)
		raise RuntimeError(f"Expected exactly one land polygon per statistics country: {details}")

	missing_areas = [
		row[0]
		for row in connection.execute(
			"""
			SELECT d.iso2
			FROM statistics_country_divisions d
			LEFT JOIN country_areas a USING (iso2)
			WHERE a.iso2 IS NULL
			ORDER BY d.iso2;
			"""
		).fetchall()
	]
	if missing_areas:
		raise RuntimeError(
			"Statistics country division(s) without land polygon: " + ", ".join(missing_areas)
		)

	connection.execute(
		"""
		CREATE TEMP TABLE country_features AS
		SELECT
			'country:' || c.iso3 AS area_id,
			a.name,
			a.iso2,
			c.iso3,
			a.wikidata,
			a.overture_id,
			a.geometry
		FROM country_areas a
		INNER JOIN iso_codes c USING (iso2);
		"""
	)

	connection.execute(
		"""
		CREATE TEMP TABLE country_labels AS
		SELECT
			'country:' || c.iso3 AS area_id,
			d.name,
			d.iso2,
			c.iso3,
			d.wikidata,
			d.overture_id,
			d.label_geometry AS geometry
		FROM statistics_country_divisions d
		INNER JOIN iso_codes c USING (iso2);
		"""
	)

	country_count = connection.execute("SELECT COUNT(*) FROM country_features;").fetchone()[0]
	label_count = connection.execute("SELECT COUNT(*) FROM country_labels;").fetchone()[0]
	perspective_fallbacks = connection.execute(
		"SELECT COUNT(*) FROM statistics_country_divisions WHERE has_perspective;"
	).fetchone()[0]

	if not 180 <= country_count <= 260:
		raise RuntimeError(f"Unexpected statistics-country count: {country_count}")
	if country_count != label_count:
		raise RuntimeError(
			f"Country/label count mismatch: polygons={country_count}, labels={label_count}"
		)
	if connection.execute(
		"SELECT COUNT(*) FROM country_features WHERE area_id = 'country:AUT';"
	).fetchone()[0] != 1:
		raise RuntimeError("Sanity check failed: country:AUT is missing.")
	if connection.execute(
		"SELECT COUNT(*) FROM country_features WHERE area_id = 'country:XKX';"
	).fetchone()[0] != 1:
		raise RuntimeError("Sanity check failed: reviewed Kosovo mapping country:XKX is missing.")

	return (
		{
			"countries": country_count,
			"labels": label_count,
			"excludedSyntheticCountries": len(excluded_entities),
			"perspectiveFallbacks": perspective_fallbacks,
		},
		excluded_entities,
	)


def export_geojsonseq(
	connection: duckdb.DuckDBPyConnection,
	table_name: str,
	output_path: Path,
) -> None:
	output_sql_path = output_path.resolve().as_posix().replace("'", "''")
	connection.execute(
		f"""
		COPY (
			SELECT
				area_id,
				name,
				iso2,
				iso3,
				wikidata,
				overture_id,
				geometry
			FROM {table_name}
			ORDER BY iso3
		)
		TO '{output_sql_path}'
		WITH (
			FORMAT GDAL,
			DRIVER 'GeoJSONSeq'
		);
		"""
	)


def write_registry(
	connection: duckdb.DuckDBPyConnection,
	output_path: Path,
	release: str,
	generated_at: str,
) -> None:
	rows = connection.execute(
		"""
		SELECT area_id, name, iso2, iso3, wikidata, overture_id
		FROM country_labels
		ORDER BY iso3;
		"""
	).fetchall()

	areas = []
	for area_id, name, iso2, iso3, wikidata, overture_id in rows:
		codes = {
			"iso2": iso2,
			"iso3": iso3,
			"overture": overture_id,
		}
		if wikidata:
			codes["wikidata"] = wikidata
		areas.append(
			{
				"area_id": area_id,
				"level": "country",
				"name": {"default": name},
				"codes": codes,
			}
		)

	payload = {
		"schema": "kartensammlung.area-registry/v1",
		"generatedAt": generated_at,
		"source": {
			"name": "Overture Maps divisions",
			"release": release,
			"license": "ODbL-1.0",
			"attribution": ATTRIBUTION,
		},
		"areas": areas,
	}
	output_path.write_text(
		json.dumps(payload, ensure_ascii=False, indent="\t") + "\n",
		encoding="utf-8",
	)


def build_pmtiles(
	tippecanoe: str,
	country_path: Path,
	label_path: Path,
	output_path: Path,
) -> None:
	command = [
		tippecanoe,
		"--force",
		"--output",
		str(output_path),
		"--minimum-zoom=0",
		"--maximum-zoom=8",
		"--projection=EPSG:4326",
		"--read-parallel",
		"--detect-shared-borders",
		"--no-feature-limit",
		"--no-tile-size-limit",
		"--name=Kartensammlung world admin",
		"--description=Statistics-compatible country geometries and label points",
		f"--attribution={ATTRIBUTION}",
		"-L",
		f"country:{country_path}",
		"-L",
		f"country_label:{label_path}",
	]
	subprocess.run(command, check=True)

	if not output_path.is_file() or output_path.stat().st_size <= 0:
		raise RuntimeError(f"Tippecanoe did not create a valid PMTiles file: {output_path}")


def write_metadata(
	output_path: Path,
	release: str,
	generated_at: str,
	counts: dict[str, int],
	excluded_entities: list[dict[str, str | None]],
	pmtiles_path: Path | None,
) -> None:
	payload = {
		"schema": "kartensammlung.area-statistics-build/v1",
		"generatedAt": generated_at,
		"overtureRelease": release,
		"geography": {
			"level": "country",
			"areaId": "country:<ISO-3166-1 alpha-3>",
			"sourceLayers": ["country", "country_label"],
			"policy": "ISO-compatible statistics countries plus explicitly reviewed mappings only",
		},
		"counts": counts,
		"excludedOvertureCountryEntities": excluded_entities,
		"source": {
			"name": "Overture Maps divisions",
			"license": "ODbL-1.0",
			"attribution": ATTRIBUTION,
		},
		"files": {
			"pmtiles": {
				"name": pmtiles_path.name if pmtiles_path else None,
				"bytes": pmtiles_path.stat().st_size if pmtiles_path else None,
			},
			"registry": "area-registry-countries.json",
		},
	}
	output_path.write_text(
		json.dumps(payload, ensure_ascii=False, indent="\t") + "\n",
		encoding="utf-8",
	)


def main() -> int:
	args = parse_args()
	release = resolve_latest_release() if args.release == "latest" else validate_release(args.release)
	output_dir = args.output_dir.resolve()
	work_dir = args.work_dir.resolve()

	if work_dir.exists():
		shutil.rmtree(work_dir)
	if output_dir.exists():
		shutil.rmtree(output_dir)
	work_dir.mkdir(parents=True, exist_ok=True)
	output_dir.mkdir(parents=True, exist_ok=True)

	generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
	country_path = work_dir / "country.geojsonseq"
	label_path = work_dir / "country-label.geojsonseq"
	registry_path = output_dir / "area-registry-countries.json"
	pmtiles_path = output_dir / "world-admin.pmtiles"

	print(f"Overture release: {release}", flush=True)
	connection = open_duckdb()
	try:
		create_iso_table(connection, load_country_codes())
		counts, excluded_entities = create_country_tables(
			connection,
			release,
			load_excluded_overture_country_codes(),
		)
		export_geojsonseq(connection, "country_features", country_path)
		export_geojsonseq(connection, "country_labels", label_path)
		write_registry(connection, registry_path, release, generated_at)
	finally:
		connection.close()

	if args.skip_tiles:
		final_pmtiles_path = None
	else:
		build_pmtiles(args.tippecanoe, country_path, label_path, pmtiles_path)
		final_pmtiles_path = pmtiles_path

	write_metadata(
		output_dir / "build-metadata.json",
		release,
		generated_at,
		counts,
		excluded_entities,
		final_pmtiles_path,
	)

	print(
		"Built "
		f"{counts['countries']} statistics countries and {counts['labels']} labels; "
		f"excluded {counts['excludedSyntheticCountries']} reviewed Overture synthetic entities"
		+ (
			f"; PMTiles: {pmtiles_path.stat().st_size:,} bytes"
			if final_pmtiles_path
			else "; PMTiles skipped"
		)
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
