#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gettext
import json
import re
import shutil
import subprocess
from collections import defaultdict
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
DIRECT_SUBTYPES = ("country", "dependency")
COMPOSITION_SUBTYPES = {"country", "dependency", "region"}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description=(
			"Build the statistics-compatible ISO-3166-1 country geometry, labels and registry "
			"from Overture Maps divisions."
		)
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
		help="Directory for temporary GeoJSONSeq files."
	)
	parser.add_argument(
		"--tippecanoe",
		default="tippecanoe",
		help="Tippecanoe executable."
	)
	parser.add_argument(
		"--skip-tiles",
		action="store_true",
		help="Only extract and validate Overture data; do not run Tippecanoe."
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


def load_country_names(codes: dict[str, str]) -> dict[str, str]:
	translation = gettext.translation(
		"iso3166-1",
		pycountry.LOCALES_DIR,
		languages=["de"],
		fallback=True,
	)
	names: dict[str, str] = {}
	for iso2 in sorted(codes):
		country = pycountry.countries.get(alpha_2=iso2)
		if country is None:
			continue
		source_name = str(country.name).strip()
		translated = str(translation.gettext(source_name)).strip()
		names[iso2] = translated or source_name

	override_path = ROOT / "config" / "country-code-overrides.json"
	overrides = json.loads(override_path.read_text(encoding="utf-8"))
	for raw_iso2, entry in overrides.items():
		iso2 = str(raw_iso2).strip().upper()
		name = str(entry.get("name", "")).strip()
		if iso2 in codes and name:
			names[iso2] = name

	missing = sorted(set(codes) - set(names))
	if missing:
		raise RuntimeError("Missing country display names: " + ", ".join(missing))
	if names.get("AT") == "Austria" or names.get("DE") == "Germany":
		raise RuntimeError("German ISO-3166 country translations are unavailable.")
	return names


def load_country_compositions(codes: dict[str, str]) -> dict[str, dict]:
	path = ROOT / "config" / "country-compositions.json"
	payload = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(payload, dict) or not payload:
		raise ValueError("Country-composition config must be a non-empty object.")

	compositions: dict[str, dict] = {}
	for raw_iso2, raw_entry in payload.items():
		iso2 = str(raw_iso2).strip().upper()
		if iso2 not in codes:
			raise ValueError(f"Composition target is not a known statistics code: {iso2!r}")
		if not isinstance(raw_entry, dict):
			raise ValueError(f"Composition {iso2} must be an object.")

		name = str(raw_entry.get("name", "")).strip()
		wikidata = str(raw_entry.get("wikidata", "")).strip() or None
		raw_components = raw_entry.get("components")
		if not name or not isinstance(raw_components, list) or not raw_components:
			raise ValueError(f"Composition {iso2} requires name and at least one component.")

		components = []
		for index, raw_component in enumerate(raw_components):
			if not isinstance(raw_component, dict):
				raise ValueError(f"Composition {iso2} component {index} must be an object.")
			subtype = str(raw_component.get("subtype", "")).strip()
			source_country = str(raw_component.get("country", "")).strip().upper() or None
			source_wikidata = str(raw_component.get("wikidata", "")).strip() or None
			if subtype not in COMPOSITION_SUBTYPES:
				raise ValueError(
					f"Composition {iso2} component {index} has unsupported subtype {subtype!r}."
				)
			if source_country is not None and len(source_country) != 2:
				raise ValueError(
					f"Composition {iso2} component {index} has invalid country code {source_country!r}."
				)
			if source_country is None and source_wikidata is None:
				raise ValueError(
					f"Composition {iso2} component {index} needs country and/or Wikidata selector."
				)
			components.append(
				{
					"subtype": subtype,
					"country": source_country,
					"wikidata": source_wikidata,
				}
			)

		compositions[iso2] = {
			"name": name,
			"wikidata": wikidata,
			"components": components,
		}

	return compositions


def load_excluded_overture_country_codes() -> set[str]:
	path = ROOT / "config" / "overture-excluded-country-codes.json"
	payload = json.loads(path.read_text(encoding="utf-8"))
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


def create_iso_table(
	connection: duckdb.DuckDBPyConnection,
	codes: dict[str, str],
	names: dict[str, str],
) -> None:
	connection.execute(
		"CREATE TEMP TABLE iso_codes ("
		"iso2 VARCHAR PRIMARY KEY, iso3 VARCHAR NOT NULL, name_de VARCHAR NOT NULL);"
	)
	connection.executemany(
		"INSERT INTO iso_codes VALUES (?, ?, ?);",
		[(iso2, iso3, names[iso2]) for iso2, iso3 in sorted(codes.items())],
	)


def create_composition_tables(
	connection: duckdb.DuckDBPyConnection,
	compositions: dict[str, dict],
) -> None:
	connection.execute(
		"CREATE TEMP TABLE composition_targets ("
		"target_iso2 VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, wikidata VARCHAR);"
	)
	connection.execute(
		"CREATE TEMP TABLE composition_components ("
		"target_iso2 VARCHAR NOT NULL, component_index INTEGER NOT NULL, "
		"source_subtype VARCHAR NOT NULL, source_country VARCHAR, source_wikidata VARCHAR, "
		"PRIMARY KEY (target_iso2, component_index));"
	)

	target_rows = []
	component_rows = []
	for iso2, entry in sorted(compositions.items()):
		target_rows.append((iso2, entry["name"], entry["wikidata"]))
		for index, component in enumerate(entry["components"]):
			component_rows.append(
				(
					iso2,
					index,
					component["subtype"],
					component["country"],
					component["wikidata"],
				)
			)

	connection.executemany("INSERT INTO composition_targets VALUES (?, ?, ?);", target_rows)
	connection.executemany("INSERT INTO composition_components VALUES (?, ?, ?, ?, ?);", component_rows)


def validate_overture_country_policy(
	connection: duckdb.DuckDBPyConnection,
	excluded_codes: set[str],
) -> list[dict[str, str | None]]:
	unknown_rows = connection.execute(
		"""
		SELECT d.iso2, d.name, d.wikidata, d.overture_id
		FROM overture_country_divisions d
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
			"New or unreviewed Overture country code(s) require an explicit policy decision: " + details
		)

	if missing_expected_codes:
		raise RuntimeError(
			"Reviewed Overture synthetic country code(s) disappeared or became ISO-compatible; "
			"review the policy before continuing: " + ", ".join(missing_expected_codes)
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
	codes: dict[str, str],
	compositions: dict[str, dict],
	excluded_codes: set[str],
) -> tuple[dict[str, int], list[dict[str, str | None]]]:
	division_path = f"{S3_BASE}/{release}/theme=divisions/type=division/*.parquet"
	area_path = f"{S3_BASE}/{release}/theme=divisions/type=division_area/*.parquet"

	create_composition_tables(connection, compositions)

	connection.execute(
		f"""
		CREATE TEMP TABLE overture_country_divisions AS
		SELECT overture_id, iso2, name, wikidata
		FROM (
			SELECT
				id AS overture_id,
				country AS iso2,
				names.primary AS name,
				wikidata,
				ROW_NUMBER() OVER (
					PARTITION BY country
					ORDER BY CASE WHEN perspectives IS NULL THEN 0 ELSE 1 END, id
				) AS choice_rank
			FROM read_parquet('{division_path}', hive_partitioning=1)
			WHERE subtype = 'country'
		)
		WHERE choice_rank = 1;
		"""
	)

	excluded_entities = validate_overture_country_policy(connection, excluded_codes)

	connection.execute(
		f"""
		CREATE TEMP TABLE direct_country_divisions AS
		SELECT
			overture_id,
			iso2,
			name,
			wikidata,
			label_geometry,
			overture_subtype,
			parent_division_id,
			has_perspective
		FROM (
			SELECT
				d.id AS overture_id,
				d.country AS iso2,
				d.names.primary AS name,
				d.wikidata,
				d.geometry AS label_geometry,
				d.subtype AS overture_subtype,
				d.parent_division_id,
				d.perspectives IS NOT NULL AS has_perspective,
				ROW_NUMBER() OVER (
					PARTITION BY d.country
					ORDER BY
						CASE WHEN d.perspectives IS NULL THEN 0 ELSE 1 END,
						CASE WHEN d.subtype = 'country' THEN 0 ELSE 1 END,
						d.id
				) AS choice_rank
			FROM read_parquet('{division_path}', hive_partitioning=1) d
			INNER JOIN iso_codes c ON c.iso2 = d.country
			LEFT JOIN composition_targets t ON t.target_iso2 = d.country
			WHERE
				d.subtype IN ('country', 'dependency')
				AND t.target_iso2 IS NULL
		)
		WHERE choice_rank = 1;
		"""
	)

	connection.execute(
		f"""
		CREATE TEMP TABLE composition_candidate_divisions AS
		SELECT
			target_iso2,
			component_index,
			overture_id,
			source_subtype,
			source_country,
			name,
			wikidata,
			parent_division_id,
			has_perspective,
			choice_rank
		FROM (
			SELECT
				cc.target_iso2,
				cc.component_index,
				d.id AS overture_id,
				d.subtype AS source_subtype,
				d.country AS source_country,
				d.names.primary AS name,
				d.wikidata,
				d.parent_division_id,
				d.perspectives IS NOT NULL AS has_perspective,
				ROW_NUMBER() OVER (
					PARTITION BY cc.target_iso2, cc.component_index
					ORDER BY CASE WHEN d.perspectives IS NULL THEN 0 ELSE 1 END, d.id
				) AS choice_rank
			FROM composition_components cc
			INNER JOIN read_parquet('{division_path}', hive_partitioning=1) d
				ON d.subtype = cc.source_subtype
				AND (cc.source_country IS NULL OR d.country = cc.source_country)
				AND (cc.source_wikidata IS NULL OR d.wikidata = cc.source_wikidata)
		)
		"""
	)

	missing_components = connection.execute(
		"""
		SELECT cc.target_iso2, cc.component_index, cc.source_subtype, cc.source_country, cc.source_wikidata
		FROM composition_components cc
		LEFT JOIN composition_candidate_divisions d
			ON d.target_iso2 = cc.target_iso2
			AND d.component_index = cc.component_index
			AND d.choice_rank = 1
		WHERE d.overture_id IS NULL
		ORDER BY cc.target_iso2, cc.component_index;
		"""
	).fetchall()
	if missing_components:
		details = ", ".join(
			f"{target}[{index}] subtype={subtype} country={country or '-'} wikidata={wikidata or '-'}"
			for target, index, subtype, country, wikidata in missing_components
		)
		raise RuntimeError("Configured country-composition component(s) not found in Overture: " + details)

	connection.execute(
		"""
		CREATE TEMP TABLE composition_divisions AS
		SELECT * EXCLUDE (choice_rank)
		FROM composition_candidate_divisions
		WHERE choice_rank = 1;
		"""
	)

	direct_target_count = len(codes) - len(compositions)
	direct_division_count = connection.execute("SELECT COUNT(*) FROM direct_country_divisions;").fetchone()[0]
	if direct_division_count != direct_target_count:
		missing_direct = [
			row[0]
			for row in connection.execute(
				"""
				SELECT c.iso2
				FROM iso_codes c
				LEFT JOIN composition_targets t ON t.target_iso2 = c.iso2
				LEFT JOIN direct_country_divisions d ON d.iso2 = c.iso2
				WHERE t.target_iso2 IS NULL AND d.iso2 IS NULL
				ORDER BY c.iso2;
				"""
			).fetchall()
		]
		raise RuntimeError(
			f"Direct statistics-area coverage mismatch: expected={direct_target_count}, "
			f"found={direct_division_count}; missing=" + ",".join(missing_direct)
		)

	missing_labels = [
		row[0]
		for row in connection.execute(
			"""
			SELECT iso2 FROM direct_country_divisions
			WHERE label_geometry IS NULL
			ORDER BY iso2;
			"""
		).fetchall()
	]
	if missing_labels:
		raise RuntimeError("Direct statistics area(s) without label geometry: " + ", ".join(missing_labels))

	connection.execute(
		f"""
		CREATE TEMP TABLE direct_country_areas AS
		SELECT
			d.overture_id,
			d.iso2,
			d.name,
			d.wikidata,
			d.overture_subtype,
			d.parent_division_id,
			a.geometry
		FROM read_parquet('{area_path}', hive_partitioning=1) a
		INNER JOIN direct_country_divisions d
			ON a.division_id = d.overture_id
			AND a.subtype = d.overture_subtype
		WHERE a.is_land = TRUE;
		"""
	)

	direct_area_problems = connection.execute(
		"""
		SELECT d.iso2, COUNT(a.overture_id) AS area_count
		FROM direct_country_divisions d
		LEFT JOIN direct_country_areas a USING (iso2)
		GROUP BY d.iso2
		HAVING COUNT(a.overture_id) <> 1
		ORDER BY d.iso2;
		"""
	).fetchall()
	if direct_area_problems:
		details = ", ".join(f"{iso2}={count}" for iso2, count in direct_area_problems)
		raise RuntimeError(f"Expected exactly one land polygon per direct statistics area: {details}")

	connection.execute(
		f"""
		CREATE TEMP TABLE composition_component_areas AS
		SELECT
			d.target_iso2,
			d.component_index,
			d.overture_id,
			d.source_subtype,
			d.source_country,
			d.name,
			d.wikidata,
			a.geometry
		FROM composition_divisions d
		INNER JOIN read_parquet('{area_path}', hive_partitioning=1) a
			ON a.division_id = d.overture_id
			AND a.subtype = d.source_subtype
		WHERE a.is_land = TRUE;
		"""
	)

	component_area_problems = connection.execute(
		"""
		SELECT d.target_iso2, d.component_index, COUNT(a.overture_id) AS area_count
		FROM composition_divisions d
		LEFT JOIN composition_component_areas a
			ON a.target_iso2 = d.target_iso2
			AND a.component_index = d.component_index
		GROUP BY d.target_iso2, d.component_index
		HAVING COUNT(a.overture_id) <> 1
		ORDER BY d.target_iso2, d.component_index;
		"""
	).fetchall()
	if component_area_problems:
		details = ", ".join(
			f"{target}[{index}]={count}" for target, index, count in component_area_problems
		)
		raise RuntimeError(f"Expected exactly one land polygon per composition component: {details}")

	connection.execute(
		"""
		CREATE TEMP TABLE composed_country_areas AS
		SELECT
			t.target_iso2 AS iso2,
			t.name,
			t.wikidata,
			ST_Union_Agg(a.geometry) AS geometry
		FROM composition_targets t
		INNER JOIN composition_component_areas a ON a.target_iso2 = t.target_iso2
		GROUP BY t.target_iso2, t.name, t.wikidata;
		"""
	)

	connection.execute(
		"""
		CREATE TEMP TABLE country_features AS
		SELECT
			'country:' || c.iso3 AS area_id,
			c.name_de AS name,
			a.name AS name_local,
			a.iso2,
			c.iso3,
			a.wikidata,
			a.overture_id,
			a.overture_subtype,
			a.parent_division_id AS overture_parent_id,
			a.geometry
		FROM direct_country_areas a
		INNER JOIN iso_codes c USING (iso2)
		UNION ALL
		SELECT
			'country:' || c.iso3 AS area_id,
			c.name_de AS name,
			a.name AS name_local,
			a.iso2,
			c.iso3,
			a.wikidata,
			NULL AS overture_id,
			'composite' AS overture_subtype,
			NULL AS overture_parent_id,
			a.geometry
		FROM composed_country_areas a
		INNER JOIN iso_codes c USING (iso2);
		"""
	)

	connection.execute(
		"""
		CREATE TEMP TABLE country_labels AS
		SELECT
			'country:' || c.iso3 AS area_id,
			c.name_de AS name,
			d.name AS name_local,
			d.iso2,
			c.iso3,
			d.wikidata,
			d.overture_id,
			d.overture_subtype,
			d.parent_division_id AS overture_parent_id,
			d.label_geometry AS geometry
		FROM direct_country_divisions d
		INNER JOIN iso_codes c USING (iso2)
		UNION ALL
		SELECT
			'country:' || c.iso3 AS area_id,
			c.name_de AS name,
			a.name AS name_local,
			a.iso2,
			c.iso3,
			a.wikidata,
			NULL AS overture_id,
			'composite' AS overture_subtype,
			NULL AS overture_parent_id,
			ST_PointOnSurface(a.geometry) AS geometry
		FROM composed_country_areas a
		INNER JOIN iso_codes c USING (iso2);
		"""
	)

	target_count = len(codes)
	country_count = connection.execute("SELECT COUNT(*) FROM country_features;").fetchone()[0]
	label_count = connection.execute("SELECT COUNT(*) FROM country_labels;").fetchone()[0]
	source_country_count = connection.execute(
		"SELECT COUNT(*) FROM direct_country_divisions WHERE overture_subtype = 'country';"
	).fetchone()[0]
	source_dependency_count = connection.execute(
		"SELECT COUNT(*) FROM direct_country_divisions WHERE overture_subtype = 'dependency';"
	).fetchone()[0]
	composition_count = connection.execute("SELECT COUNT(*) FROM composed_country_areas;").fetchone()[0]
	composition_component_count = connection.execute("SELECT COUNT(*) FROM composition_divisions;").fetchone()[0]
	perspective_fallbacks = connection.execute(
		"""
		SELECT
			(SELECT COUNT(*) FROM direct_country_divisions WHERE has_perspective)
			+ (SELECT COUNT(*) FROM composition_divisions WHERE has_perspective);
		"""
	).fetchone()[0]

	if country_count != target_count or label_count != target_count:
		raise RuntimeError(
			f"Final statistics-area count mismatch: expected={target_count}, "
			f"polygons={country_count}, labels={label_count}"
		)
	if composition_count != len(compositions):
		raise RuntimeError(
			f"Composition count mismatch: expected={len(compositions)}, built={composition_count}"
		)

	for area_id in (
		"country:AUT",
		"country:XKX",
		"country:BES",
		"country:SJM",
		"country:PSE",
		"country:ESH",
	):
		if connection.execute(
			"SELECT COUNT(*) FROM country_features WHERE area_id = ?;",
			[area_id],
		).fetchone()[0] != 1:
			raise RuntimeError(f"Sanity check failed: {area_id} is missing or duplicated.")

	for area_id, expected_name in (
		("country:AUT", "Österreich"),
		("country:DEU", "Deutschland"),
		("country:XKX", "Kosovo"),
	):
		row = connection.execute(
			"SELECT name FROM country_labels WHERE area_id = ?;",
			[area_id],
		).fetchone()
		if row is None or row[0] != expected_name:
			raise RuntimeError(
				f"German display-name sanity check failed for {area_id}: {row[0] if row else None!r}."
			)

	if connection.execute(
		"SELECT COUNT(*) FROM country_features WHERE area_id = 'country:PRI' AND overture_subtype = 'dependency';"
	).fetchone()[0] != 1:
		raise RuntimeError("Sanity check failed: country:PRI is not present as an Overture dependency.")

	return (
		{
			"countries": country_count,
			"labels": label_count,
			"iso3166Countries": len(list(pycountry.countries)),
			"reviewedAdditionalAreas": target_count - len(list(pycountry.countries)),
			"directOvertureCountries": source_country_count,
			"directOvertureDependencies": source_dependency_count,
			"composedAreas": composition_count,
			"compositionComponents": composition_component_count,
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
				name_local,
				iso2,
				iso3,
				wikidata,
				overture_id,
				overture_subtype,
				overture_parent_id,
				geometry
			FROM {table_name}
			ORDER BY iso3
		)
		TO '{output_sql_path}'
		WITH (FORMAT GDAL, DRIVER 'GeoJSONSeq');
		"""
	)


def resolved_composition_components(connection: duckdb.DuckDBPyConnection) -> dict[str, list[dict]]:
	rows = connection.execute(
		"""
		SELECT
			target_iso2,
			component_index,
			overture_id,
			source_subtype,
			source_country,
			name,
			wikidata,
			parent_division_id
		FROM composition_divisions
		ORDER BY target_iso2, component_index;
		"""
	).fetchall()
	components: dict[str, list[dict]] = defaultdict(list)
	for target, index, overture_id, subtype, country, name, wikidata, parent_id in rows:
		entry = {
			"index": index,
			"overtureId": overture_id,
			"subtype": subtype,
			"country": country,
			"name": name,
		}
		if wikidata:
			entry["wikidata"] = wikidata
		if parent_id:
			entry["parentId"] = parent_id
		components[target].append(entry)
	return dict(components)


def write_registry(
	connection: duckdb.DuckDBPyConnection,
	output_path: Path,
	release: str,
	generated_at: str,
) -> None:
	rows = connection.execute(
		"""
		SELECT area_id, name, name_local, iso2, iso3, wikidata, overture_id, overture_subtype, overture_parent_id
		FROM country_labels
		ORDER BY iso3;
		"""
	).fetchall()
	composition_components = resolved_composition_components(connection)

	areas = []
	for area_id, name, name_local, iso2, iso3, wikidata, overture_id, overture_subtype, overture_parent_id in rows:
		codes = {"iso2": iso2, "iso3": iso3}
		if overture_id:
			codes["overture"] = overture_id
		if wikidata:
			codes["wikidata"] = wikidata

		metadata = {
			"overtureSubtype": overture_subtype,
			"sourceName": name_local,
		}
		if overture_parent_id:
			metadata["overtureParentId"] = overture_parent_id
		if iso2 in composition_components:
			metadata["composition"] = composition_components[iso2]

		areas.append(
			{
				"area_id": area_id,
				"level": "country",
				"name": {
					"default": name,
					"de": name,
				},
				"codes": codes,
				"metadata": metadata,
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
		"--description=Statistics-compatible ISO-3166-1 country geometries and label points",
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
	compositions: dict[str, dict],
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
			"directSourceSubtypes": list(DIRECT_SUBTYPES),
			"compositionTargets": sorted(compositions),
			"displayNameLanguage": "de",
			"sourceNameProperty": "name_local",
			"policy": (
				"Complete ISO-3166-1 area-code set plus explicitly reviewed mappings. "
				"Direct Overture country/dependency representations are preferred; configured composite "
				"areas are built from reviewed Overture components."
			),
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

	codes = load_country_codes()
	names = load_country_names(codes)
	compositions = load_country_compositions(codes)

	print(f"Overture release: {release}", flush=True)
	print("Configured composite ISO areas: " + ", ".join(sorted(compositions)), flush=True)
	connection = open_duckdb()
	try:
		create_iso_table(connection, codes, names)
		counts, excluded_entities = create_country_tables(
			connection,
			release,
			codes,
			compositions,
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
		compositions,
		final_pmtiles_path,
	)

	print(
		"Built "
		f"{counts['countries']} statistics areas and {counts['labels']} labels; "
		f"direct sources: {counts['directOvertureCountries']} country + "
		f"{counts['directOvertureDependencies']} dependency; "
		f"composed: {counts['composedAreas']} from {counts['compositionComponents']} components; "
		f"excluded standalone synthetic country entities: {counts['excludedSyntheticCountries']}"
		+ (
			f"; PMTiles: {pmtiles_path.stat().st_size:,} bytes"
			if final_pmtiles_path
			else "; PMTiles skipped"
		)
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
