#!/usr/bin/env bash
set -euo pipefail

: "${EASYNAME_FTP_HOST:?EASYNAME_FTP_HOST is required}"
: "${EASYNAME_FTP_USER:?EASYNAME_FTP_USER is required}"
: "${EASYNAME_FTP_PASSWORD:?EASYNAME_FTP_PASSWORD is required}"

DIST_DIR="${1:-dist}"
REMOTE_DIR="AreaStatistics"
UPLOAD_ID="${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-1}"

for file in world-admin.pmtiles area-registry-countries.json build-metadata.json; do
	if [ ! -s "${DIST_DIR}/${file}" ]; then
		echo "Missing or empty deployment file: ${DIST_DIR}/${file}" >&2
		exit 1
	fi
done

if ! command -v lftp >/dev/null 2>&1; then
	echo "lftp is required for deployment." >&2
	exit 1
fi

export LFTP_PASSWORD="${EASYNAME_FTP_PASSWORD}"

LFTP_CMDS=$(mktemp)
trap 'rm -f "$LFTP_CMDS"' EXIT

{
	echo "set cmd:fail-exit yes"
	echo "set ftp:ssl-force true"
	echo "set ftp:ssl-protect-data true"
	echo "set ftp:passive-mode true"
	echo "set ssl:verify-certificate no"
	echo "set net:max-retries 10"
	echo "set net:timeout 30"
	echo "set net:reconnect-interval-base 30"
	echo "set net:reconnect-interval-multiplier 1"
	echo "open --user \"${EASYNAME_FTP_USER}\" --env-password \"${EASYNAME_FTP_HOST}\""
	echo "mkdir -p \"${REMOTE_DIR}\""
	echo "put \"${DIST_DIR}/area-registry-countries.json\" -o \"${REMOTE_DIR}/.area-registry-countries.json.${UPLOAD_ID}.tmp\""
	echo "put \"${DIST_DIR}/build-metadata.json\" -o \"${REMOTE_DIR}/.build-metadata.json.${UPLOAD_ID}.tmp\""
	echo "put \"${DIST_DIR}/world-admin.pmtiles\" -o \"${REMOTE_DIR}/.world-admin.pmtiles.${UPLOAD_ID}.tmp\""
	echo "rm -f \"${REMOTE_DIR}/area-registry-countries.json\""
	echo "mv \"${REMOTE_DIR}/.area-registry-countries.json.${UPLOAD_ID}.tmp\" \"${REMOTE_DIR}/area-registry-countries.json\""
	echo "rm -f \"${REMOTE_DIR}/build-metadata.json\""
	echo "mv \"${REMOTE_DIR}/.build-metadata.json.${UPLOAD_ID}.tmp\" \"${REMOTE_DIR}/build-metadata.json\""
	echo "rm -f \"${REMOTE_DIR}/world-admin.pmtiles\""
	echo "mv \"${REMOTE_DIR}/.world-admin.pmtiles.${UPLOAD_ID}.tmp\" \"${REMOTE_DIR}/world-admin.pmtiles\""
	echo "bye"
} > "$LFTP_CMDS"

lftp -f "$LFTP_CMDS"

echo "Deployed area statistics to /${REMOTE_DIR}/"
