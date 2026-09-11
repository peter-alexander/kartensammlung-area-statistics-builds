#!/usr/bin/env bash
set -euo pipefail

# Country label points are semantic anchors. Keep every point at every zoom;
# MapLibre handles collision and label priority at render time.
exec tippecanoe --drop-rate=1 "$@"
