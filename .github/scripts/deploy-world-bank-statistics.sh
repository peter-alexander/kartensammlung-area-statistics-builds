#!/usr/bin/env bash
set -euo pipefail

DIST_DIR="${1:-dist/statistics}"
PROVIDER_ID="${PROVIDER_ID:-world-bank}"
REMOTE_BASE="AreaStatistics/statistics"
UPLOAD_SCRIPT=".github/scripts/lftp-upload.sh"

GLOBAL_INDEX="${DIST_DIR}/index.json"
PROVIDER_DIR="${DIST_DIR}/${PROVIDER_ID}"
PROVIDER_INDEX="${PROVIDER_DIR}/index.json"
RELEASE_DIR="${PROVIDER_DIR}/releases"

for path in "$GLOBAL_INDEX" "$PROVIDER_INDEX"; do
	if [ ! -s "$path" ]; then
		echo "Missing or empty deployment file: $path" >&2
		exit 1
	fi
done

if [ ! -d "$RELEASE_DIR" ]; then
	echo "Missing statistics release directory: $RELEASE_DIR" >&2
	exit 1
fi

mapfile -d '' RELEASE_FILES < <(find "$RELEASE_DIR" -type f -name '*.json' -print0 | sort -z)

if [ "${#RELEASE_FILES[@]}" -eq 0 ]; then
	echo "No statistics release files found in $RELEASE_DIR" >&2
	exit 1
fi

chmod +x "$UPLOAD_SCRIPT"

for local_path in "${RELEASE_FILES[@]}"; do
	relative_path="${local_path#"${DIST_DIR}/"}"
	"$UPLOAD_SCRIPT" "$local_path" "${REMOTE_BASE}/${relative_path}"
done

"$UPLOAD_SCRIPT" "$PROVIDER_INDEX" "${REMOTE_BASE}/${PROVIDER_ID}/index.json"
"$UPLOAD_SCRIPT" "$GLOBAL_INDEX" "${REMOTE_BASE}/index.json"

echo "Deployed ${#RELEASE_FILES[@]} ${PROVIDER_ID} statistics files and manifests to /${REMOTE_BASE}/"
