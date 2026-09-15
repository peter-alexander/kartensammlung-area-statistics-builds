# Global Wind Atlas source policy

This document records the source and aggregation policy for country-level Global Wind Atlas statistics.

## Source

- Dataset: Global Wind Atlas 4.0 (GWA 4.0)
- Owner/operator: Technical University of Denmark (DTU)
- Partnership: World Bank Group / ESMAP
- License: CC BY 4.0
- Production height: 100 m above ground
- Production variables: mean wind speed and mean power density
- Native source grid: 0.0025° (~250 m nominal), EPSG:4326, Float32, NaN NoData

The production workflow uses the global GIS files exposed by the official Global Wind Atlas download/API service. It does not automate downloads of all individual country files. The GWA download page explicitly states that the API service must not be used for bulk downloads of all countries or datasets.

## Geometry and aggregation

Country statistics use the existing Kartensammlung country registry and its matching Overture Maps `is_land = TRUE` polygons. Offshore and EEZ areas are intentionally excluded so country values describe land territory consistently.

Aggregation is performed on the native GWA raster grid using:

- exact fractional source-cell coverage;
- `exactextract` raster-sequential processing;
- WGS84 geodetic source-cell area weighting by latitude row;
- no raster resampling;
- no source overviews for the statistic itself.

The exact Overture release used for geometry is recorded in every snapshot.

## Coverage

The audited GWA 4.0 global 100 m mean-wind-speed raster spans approximately 80°N to 64°S. It contains no valid coverage for `ATA`, `BVT`, `HMD`, and `SGS`. These areas are retained in the country registry but omitted from indicator values rather than assigned artificial zeroes.

## Source integrity

Each downloaded global raster is validated for CRS, data type, resolution, NoData metadata, dimensions and bounds. File size and SHA-256 are recorded in provenance. The workflow processes the two variables sequentially so the two roughly 14 GB source rasters do not need to coexist.

## Wind-speed audit baseline

Native 100 m mean-wind-speed audit against Overture release `2026-08-19.0`:

- source bytes: `14074635333`
- source SHA-256: `3ed2c0bce38cd681aa61729027f666e39bd1f356eade42e6b8199a9f7e7f1730`
- raster size: `144000 × 57600`
- transform: `[-180.00125, 0.0025, 0, 79.99875, 0, -0.0025]`
- countries with values: `246/250`
- extraction runtime in the audited GitHub Actions run: `314.754 s`
- download runtime in that run: `576 s`

Control weighted means (m/s):

- AUT: `5.283634382290039`
- NOR: `7.2152599085550415`
- USA: `6.3241818403143`
- CAN: `6.713752924710273`
- IND: `4.433333177248324`
- NAM: `5.453422682847788`
- XKX: `4.717885097074282`
- VAT: `4.48350390564016`

The power-density baseline is added after the corresponding full-source audit succeeds.
