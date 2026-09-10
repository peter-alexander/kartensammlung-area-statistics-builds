#!/usr/bin/env bash
set -euo pipefail

DIST_DIR="${1:-dist}"
REMOTE_DIR="AreaStatistics"
UPLOAD_SCRIPT=".github/scripts/lftp-upload.sh"

for file in world-admin.pmtiles area-registry-countries.json build-metadata.json; do
	if [ ! -s "${DIST_DIR}/${file}" ]; then
		echo "Missing or empty deployment file: ${DIST_DIR}/${file}" >&2
		exit 1
	fi
done

chmod +x "$UPLOAD_SCRIPT"

"$UPLOAD_SCRIPT" "${DIST_DIR}/area-registry-countries.json" "${REMOTE_DIR}/area-registry-countries.json"
"$UPLOAD_SCRIPT" "${DIST_DIR}/build-metadata.json" "${REMOTE_DIR}/build-metadata.json"
"$UPLOAD_SCRIPT" "${DIST_DIR}/world-admin.pmtiles" "${REMOTE_DIR}/world-admin.pmtiles"

echo "Deployed area statistics to /${REMOTE_DIR}/"
