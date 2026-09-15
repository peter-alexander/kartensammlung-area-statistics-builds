# DLR Global SnowPack source policy

## Purpose

This provider publishes country-level snow-cover duration derived directly from the DLR Earth Observation Center Global SnowPack yearly Snow Cover Duration (SCD) product.

## Canonical source

- Dataset: DLR Global SnowPack (GSP), yearly Snow Cover Duration
- Product version: 2
- Dataset page: https://geoservice.dlr.de/web/datasets/gsp_modis_p1y
- Dataset overview: https://b.geoservice.dlr.de/web/datasets/globalsnowpack
- Download root: https://download.geoservice.dlr.de/GSP/files/yearly/SCD/
- License: CC BY 4.0

The workflow discovers the available yearly SCD directories from the canonical DLR download root. The series must be contiguous from 2001 onward and must include at least 2024. A newly published complete year is picked up automatically.

## Meaning of the year label

The yearly SCD product is not a calendar-year statistic.

- Northern hemisphere: 1 September of the previous year through 31 August of the labelled year.
- Southern hemisphere: 1 March of the previous year through 28/29 February of the labelled year.

The published indicator therefore describes the DLR snow year. Countries spanning both hemispheres inherit the hemisphere-dependent source-product definition at raster-cell level.

## Spatial aggregation

The country statistic is the land-area-weighted mean number of snow-covered days.

1. Use the native DLR WGS84 raster (`86400 × 43200`, `1/240°`) without reprojection or resampling.
2. Do not use the GeoTIFF overview levels for quantitative aggregation.
3. Treat source value `0` as a valid value meaning zero snow-covered days. The source currently declares `0` as NoData; analysis therefore removes only that NoData metadata in a VRT while leaving all raster values unchanged.
4. Use the country land polygons from the exact Overture release named by the published country area registry. Do not resolve an independent `latest` release for SnowPack.
5. Calculate exact fractional raster-cell coverage for each country using `exactextract`.
6. Weight every covered source cell by its WGS84 geodesic cell area. This is required because a `1/240°` longitude cell has different physical area at different latitudes.
7. Publish only the weighted mean SCD in days. Minima, maxima and covered-cell equivalents remain build-time validation diagnostics.

## Reproducibility and validation

Every yearly intermediate records:

- source URL
- source byte size
- SHA256 of the downloaded GeoTIFF
- source grid metadata
- Overture release
- extraction method and runtime

The final statistics snapshot includes the source URL, size and SHA256 for every year. The source-file provenance is part of the hashed indicator payload, so a revised upstream raster produces a new snapshot even when rounded country means happen to remain unchanged.

The build fails if any of the following changes unexpectedly:

- raster dimensions, resolution, global extent, CRS or data type
- declared source NoData value
- country set or country count
- Overture release between geometry and registry
- a missing year inside the series
- a country mean/minimum/maximum outside `0…366` days
- zero raster coverage for any country

## Audited baseline

The full native-resolution audit for 2001–2024 succeeded for all 250 country areas (6,000 country-year means) using Overture release `2026-08-19.0`. No source year required a special-case aggregation rule.
