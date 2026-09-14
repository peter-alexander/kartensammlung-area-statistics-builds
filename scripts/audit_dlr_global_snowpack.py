#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

STAC_BASE = "https://geoservice.dlr.de/eoc/ogc/stac/v1"
COLLECTIONS = (
	"GSP_SCD_P1Y",
	"GSP_SCDE_P1Y",
	"GSP_SCDL_P1Y",
)
USER_AGENT = "kartensammlung-area-statistics-builds/1"


def fetch_json(url: str, attempts: int = 4) -> dict:
	last_error: Exception | None = None
	for attempt in range(attempts):
		try:
			request = Request(
				url,
				headers={
					"Accept": "application/json, application/geo+json;q=0.9, */*;q=0.1",
					"User-Agent": USER_AGENT,
				},
			)
			with urlopen(request, timeout=60) as response:
				return json.load(response)
		except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
			last_error = exc
			if attempt + 1 < attempts:
				time.sleep((2, 5, 15)[min(attempt, 2)])
	assert last_error is not None
	raise last_error


def fetch_all_items(collection_id: str) -> list[dict]:
	query = urlencode({"limit": 1000, "f": "application/geo+json"})
	url = f"{STAC_BASE}/collections/{collection_id}/items?{query}"
	items: list[dict] = []
	seen_urls: set[str] = set()
	while url:
		if url in seen_urls:
			raise RuntimeError(f"Pagination loop detected for {collection_id}: {url}")
		seen_urls.add(url)
		payload = fetch_json(url)
		features = payload.get("features", [])
		if not isinstance(features, list):
			raise RuntimeError(f"Invalid STAC feature list for {collection_id}")
		items.extend(features)
		next_links = [
			link.get("href")
			for link in payload.get("links", [])
			if link.get("rel") == "next" and link.get("href")
		]
		url = next_links[0] if next_links else ""
	return items


def item_time_key(item: dict) -> str:
	properties = item.get("properties", {})
	return str(
		properties.get("datetime")
		or properties.get("end_datetime")
		or properties.get("start_datetime")
		or ""
	)


def data_assets(item: dict) -> list[tuple[str, dict]]:
	result: list[tuple[str, dict]] = []
	for key, asset in item.get("assets", {}).items():
		href = str(asset.get("href", ""))
		roles = asset.get("roles") or []
		media_type = str(asset.get("type", ""))
		if "data" in roles or href.lower().endswith((".tif", ".tiff")) or "geotiff" in media_type.lower():
			result.append((key, asset))
	return result


def http_probe(url: str) -> dict:
	result: dict[str, object] = {"url": url}
	for method in ("HEAD", "GET"):
		headers = {"User-Agent": USER_AGENT}
		if method == "GET":
			headers["Range"] = "bytes=0-0"
		request = Request(url, method=method, headers=headers)
		try:
			with urlopen(request, timeout=60) as response:
				result.update(
					{
						"probeMethod": method,
						"status": response.status,
						"contentLength": response.headers.get("Content-Length"),
						"contentRange": response.headers.get("Content-Range"),
						"acceptRanges": response.headers.get("Accept-Ranges"),
						"etag": response.headers.get("ETag"),
						"lastModified": response.headers.get("Last-Modified"),
						"contentType": response.headers.get("Content-Type"),
					}
				)
				return result
		except HTTPError as exc:
			result[f"{method.lower()}Error"] = f"HTTP {exc.code}: {exc.reason}"
		except URLError as exc:
			result[f"{method.lower()}Error"] = str(exc.reason)
	return result


def gdal_probe(url: str) -> dict:
	command = [
		"gdalinfo",
		"-json",
		"-stats",
		f"/vsicurl/{url}",
	]
	completed = subprocess.run(
		command,
		check=False,
		capture_output=True,
		text=True,
		timeout=180,
	)
	result: dict[str, object] = {
		"returnCode": completed.returncode,
	}
	if completed.stderr.strip():
		result["stderr"] = completed.stderr.strip()
	if completed.returncode == 0:
		try:
			payload = json.loads(completed.stdout)
			result["driverShortName"] = payload.get("driverShortName")
			result["size"] = payload.get("size")
			result["coordinateSystem"] = payload.get("coordinateSystem", {}).get("wkt")
			result["geoTransform"] = payload.get("geoTransform")
			bands = []
			for band in payload.get("bands", []):
				bands.append(
					{
						"band": band.get("band"),
						"type": band.get("type"),
						"noDataValue": band.get("noDataValue"),
						"minimum": band.get("minimum"),
						"maximum": band.get("maximum"),
						"mean": band.get("mean"),
						"stdDev": band.get("stdDev"),
						"overviews": band.get("overviews"),
					}
				)
			result["bands"] = bands
			except json.JSONDecodeError:
			result["stdout"] = completed.stdout[-4000:]
	else:
		result["stdout"] = completed.stdout[-4000:]
	return result


def compact_item(item: dict) -> dict:
	properties = item.get("properties", {})
	assets = {}
	for key, asset in item.get("assets", {}).items():
		assets[key] = {
			"href": asset.get("href"),
			"type": asset.get("type"),
			"roles": asset.get("roles"),
			"title": asset.get("title"),
			"fileSize": asset.get("file:size"),
			"rasterBands": asset.get("raster:bands"),
		}
	return {
		"id": item.get("id"),
		"datetime": properties.get("datetime"),
		"startDatetime": properties.get("start_datetime"),
		"endDatetime": properties.get("end_datetime"),
		"bbox": item.get("bbox"),
		"assets": assets,
	}


def audit_collection(collection_id: str, probe_gdal: bool) -> dict:
	collection_url = f"{STAC_BASE}/collections/{collection_id}?f=application/json"
	collection = fetch_json(collection_url)
	items = fetch_all_items(collection_id)
	if not items:
		raise RuntimeError(f"No STAC items returned for {collection_id}")
	items_sorted = sorted(items, key=item_time_key)
	latest = items_sorted[-1]
	latest_assets = data_assets(latest)
	if not latest_assets:
		raise RuntimeError(f"No data asset found in latest {collection_id} item {latest.get('id')}")

	probe_results = []
	for key, asset in latest_assets:
		href = str(asset.get("href", ""))
		probe = {
			"assetKey": key,
			"http": http_probe(href),
		}
		if probe_gdal:
			probe["gdal"] = gdal_probe(href)
		probe_results.append(probe)

	result = {
		"collection": {
			"id": collection.get("id"),
			"title": collection.get("title"),
			"description": collection.get("description"),
			"license": collection.get("license"),
			"extent": collection.get("extent"),
			"providers": collection.get("providers"),
		},
		"itemCount": len(items_sorted),
		"firstItem": compact_item(items_sorted[0]),
		"latestItem": compact_item(latest),
		"itemIds": [item.get("id") for item in items_sorted],
		"probeResults": probe_results,
	}
	print(
		f"{collection_id}: items={len(items_sorted)} "
		f"first={items_sorted[0].get('id')} latest={latest.get('id')} "
		f"latestTime={item_time_key(latest)}",
		flush=True,
	)
	for probe in probe_results:
		http = probe["http"]
		print(
			f"  asset={probe['assetKey']} status={http.get('status')} "
			f"length={http.get('contentLength')} range={http.get('acceptRanges')} "
			f"contentRange={http.get('contentRange')}",
			flush=True,
		)
		if probe_gdal:
			gdal = probe.get("gdal", {})
			print(
				f"  gdal rc={gdal.get('returnCode')} size={gdal.get('size')} "
				f"bands={gdal.get('bands')}",
				flush=True,
			)
	return result


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Audit DLR/EOC Global SnowPack yearly STAC collections.")
	parser.add_argument(
		"--output",
		type=Path,
		default=Path("diagnostics/dlr-global-snowpack-audit.json"),
	)
	parser.add_argument("--probe-gdal", action="store_true")
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	result = {
		"stacBase": STAC_BASE,
		"collections": {},
	}
	for collection_id in COLLECTIONS:
		result["collections"][collection_id] = audit_collection(collection_id, args.probe_gdal)
	args.output.parent.mkdir(parents=True, exist_ok=True)
	args.output.write_text(json.dumps(result, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
	print(f"Wrote {args.output}", flush=True)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
