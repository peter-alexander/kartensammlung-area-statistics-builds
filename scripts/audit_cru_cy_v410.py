#!/usr/bin/env python3

import html.parser
import json
import re
import unicodedata
import urllib.request

REGISTRY_URL = "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
BASE = "https://crudata.uea.ac.uk/cru/data/hrg/cru_ts_4.10/crucy.2606161920.v4.10"
VARIABLES = ("tmp", "tmx", "tmn", "pre", "dtr", "frs", "wet", "pet", "cld", "vap")


class LinkParser(html.parser.HTMLParser):
	def __init__(self):
		super().__init__()
		self.links = []

	def handle_starttag(self, tag, attrs):
		if tag != "a":
			return
		for key, value in attrs:
			if key == "href" and value:
				self.links.append(value)


def fetch_text(url):
	req = urllib.request.Request(
		url,
		headers={"User-Agent": "kartensammlung-area-statistics-builds/cru-cy-audit"},
	)
	with urllib.request.urlopen(req, timeout=90) as response:
		body = response.read()
		return response.status, response.headers, body.decode("utf-8", errors="replace")


def fetch_json(url):
	status, headers, text = fetch_text(url)
	return status, headers, json.loads(text)


def normalize_name(value):
	value = unicodedata.normalize("NFKD", value)
	value = "".join(ch for ch in value if not unicodedata.combining(ch))
	value = value.lower().replace("&", " and ").replace("+", " and ")
	value = re.sub(r"\b(the|republic of|state of)\b", " ", value)
	value = re.sub(r"[^a-z0-9]+", " ", value)
	return " ".join(value.split())


def area_names(area):
	result = set()
	for key in ("name", "label", "display_name", "displayName", "title"):
		value = area.get(key)
		if isinstance(value, str) and value.strip():
			result.add(value.strip())
	for key in ("names", "labels"):
		value = area.get(key)
		if isinstance(value, dict):
			for nested in value.values():
				if isinstance(nested, str) and nested.strip():
					result.add(nested.strip())
	return result


def source_names(variable):
	status, _, text = fetch_text(f"{BASE}/countries/{variable}/")
	if status != 200:
		raise RuntimeError(f"Directory request failed for {variable}: HTTP {status}")
	parser = LinkParser()
	parser.feed(text)
	pattern = re.compile(rf"^crucy\.v4\.10\.1901\.2025\.(.+)\.{re.escape(variable)}\.per$")
	names = []
	for link in parser.links:
		filename = link.rsplit("/", 1)[-1]
		match = pattern.match(filename)
		if match:
			names.append(match.group(1))
	return sorted(set(names))


def inspect_country_file(variable, country="Austria"):
	filename = f"crucy.v4.10.1901.2025.{country}.{variable}.per"
	url = f"{BASE}/countries/{variable}/{filename}"
	status, headers, text = fetch_text(url)
	lines = [line.rstrip() for line in text.splitlines() if line.strip()]
	if status != 200 or len(lines) < 5:
		raise RuntimeError(f"Unexpected {variable}/{country} response: HTTP {status}, lines={len(lines)}")
	last = lines[-1].split()
	return {
		"url": url,
		"contentLength": headers.get("Content-Length"),
		"line1": lines[0],
		"line2": lines[1],
		"line3": lines[2],
		"header": lines[3],
		"firstData": lines[4],
		"lastData": lines[-1],
		"lastYear": int(last[0]),
		"lastAnnual": last[-1],
	}


def main():
	status, _, registry = fetch_json(REGISTRY_URL)
	areas = registry.get("areas") or []
	print(f"registry_http={status} schema={registry.get('schema')} areas={len(areas)}")
	print("registry_sample=" + json.dumps(areas[:3], ensure_ascii=False, sort_keys=True))

	registry_by_normalized = {}
	area_name_summary = {}
	for area in areas:
		if not isinstance(area, dict) or area.get("level") != "country":
			continue
		area_id = str(area.get("area_id", ""))
		names = area_names(area)
		area_name_summary[area_id] = sorted(names)
		for name in names:
			registry_by_normalized.setdefault(normalize_name(name), set()).add(area_id)

	all_sets = {}
	for variable in VARIABLES:
		names = source_names(variable)
		all_sets[variable] = set(names)
		info = inspect_country_file(variable)
		print(f"variable={variable} source_files={len(names)}")
		print("file_info=" + json.dumps(info, ensure_ascii=False, sort_keys=True))

	base_names = all_sets["tmp"]
	for variable in VARIABLES[1:]:
		missing = sorted(base_names - all_sets[variable])
		extra = sorted(all_sets[variable] - base_names)
		print(f"set_diff tmp_vs_{variable}: missing={len(missing)} extra={len(extra)}")
		if missing:
			print(f"  missing_sample={missing[:20]}")
		if extra:
			print(f"  extra_sample={extra[:20]}")

	matched_areas = set()
	ambiguous = {}
	unmatched_sources = []
	for source_name in sorted(base_names):
		if source_name == "all":
			continue
		key = normalize_name(source_name.replace("_", " "))
		matches = registry_by_normalized.get(key, set())
		if len(matches) == 1:
			matched_areas.update(matches)
		elif len(matches) > 1:
			ambiguous[source_name] = sorted(matches)
		else:
			unmatched_sources.append(source_name)

	country_area_ids = {
		str(area.get("area_id"))
		for area in areas
		if isinstance(area, dict) and area.get("level") == "country"
	}
	unmatched_registry = sorted(country_area_ids - matched_areas)
	print(f"exact_name_mapping matched_registry={len(matched_areas)} ambiguous_sources={len(ambiguous)}")
	print(f"unmatched_source_count={len(unmatched_sources)}")
	print("unmatched_sources=" + json.dumps(unmatched_sources, ensure_ascii=False))
	print(f"unmatched_registry_count={len(unmatched_registry)}")
	for area_id in unmatched_registry:
		print(f"unmatched_registry {area_id}: {area_name_summary.get(area_id, [])}")
	if ambiguous:
		print("ambiguous=" + json.dumps(ambiguous, ensure_ascii=False, sort_keys=True))

	for probe in ("Austria", "Germany", "USA", "United_States", "India", "China", "South_Africa", "Namibia", "Kosovo", "Falkland_Isl", "Western_Sahara"):
		print(f"probe {probe}={probe in base_names}")

	print("AUDIT_OK")


if __name__ == "__main__":
	main()
