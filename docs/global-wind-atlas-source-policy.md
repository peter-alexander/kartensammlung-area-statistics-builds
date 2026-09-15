# Global Wind Atlas source policy

This document records the source and aggregation policy for country-level Global Wind Atlas statistics.

## Source

- Dataset: Global Wind Atlas 4.0 (GWA 4.0)
- Release: June 2025
- Owner/operator: Technical University of Denmark (DTU)
- Partnership: World Bank Group / ESMAP
- Data provider attribution: Vortex
- License: CC BY 4.0
- Production height: 100 m above ground
- Production variables: mean wind speed and mean power density
- Native source grid: 0.0025° (~250 m nominal), EPSG:4326, Float32, NaN NoData
- Atmospheric reference period: 2008-2017

GWA 4.0 is a wind-climate snapshot, not an annual time series. The published country statistics therefore use 2025 as the snapshot/version year, reflecting the June 2025 GWA 4.0 release. The underlying large-scale ERA5 data and mesoscale simulations represent 2008-2017 and are recorded separately as the reference period.

The production workflow uses the global GIS files exposed by the official Global Wind Atlas download/API service. It does not automate downloads of all individual country files. The GWA download page explicitly states that the API service must not be used for bulk downloads of all countries or datasets.

Attribution in published metadata names DTU, World Bank Group / ESMAP and Vortex in accordance with the Global Wind Atlas terms.

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
- Rasterio/Affine transform coefficients `(a, b, c, d, e, f)`: `[0.002500000000000001, 0.0, -180.00125, 0.0, -0.002500000000000001, 79.99875]`
- bounds `(left, bottom, right, top)`: `[-180.00125, -64.00125000000006, 179.99875000000011, 79.99875]`
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