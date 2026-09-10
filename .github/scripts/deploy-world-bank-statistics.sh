#!/usr/bin/env bash
set -euo pipefail

DIST_DIR="${1:-dist/statistics}"
PROVIDER_ID="${PROVIDER_ID:-world-bank}"
REMOTE_BASE="AreaStatistics/statistics"

GLOBAL_INDEX="${DIST_DIR}/index.json"
PROVIDER_DIR="${DIST_DIR}/${PROVIDER_ID}"
PROVIDER_INDEX="${PROVIDER_DIR}/index.json"
RELEASE_DIR="${PROVIDER_DIR}/releases"

: "${FTP_HOST:?FTP_HOST is required}"
: "${FTP_USER:?FTP_USER is required}"
: "${FTP_PASS:?FTP_PASS is required}"

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

mapfile -d '' RELEASE_DIRS < <(find "$RELEASE_DIR" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
if [ "${#RELEASE_DIRS[@]}" -eq 0 ]; then
	echo "No statistics release directories found in $RELEASE_DIR" >&2
	exit 1
fi

RELEASE_FILE_COUNT=0
for local_dir in "${RELEASE_DIRS[@]}"; do
	file_count="$(find "$local_dir" -maxdepth 1 -type f -name '*.json' -print | wc -l)"
	if [ "$file_count" -eq 0 ]; then
		echo "No statistics JSON files found in $local_dir" >&2
		exit 1
	fi
	RELEASE_FILE_COUNT=$((RELEASE_FILE_COUNT + file_count))
done

if ! command -v lftp >/dev/null 2>&1; then
	echo "lftp is required for statistics deployment." >&2
	exit 1
fi

SSL_VERIFY="${LFTP_SSL_VERIFY:-no}"
LFTP_RETRIES="${LFTP_RETRIES:-10}"
LFTP_RETRY_DELAY="${LFTP_RETRY_DELAY:-15}"
LFTP_NET_TIMEOUT="${LFTP_NET_TIMEOUT:-30}"

LFTP_CMDS="$(mktemp)"
trap 'rm -f "$LFTP_CMDS"' EXIT

{
	echo "set cmd:fail-exit true"
	echo "set ftp:ssl-force true"
	echo "set ftp:passive-mode true"
	echo "set ssl:verify-certificate $SSL_VERIFY"
	echo "set net:max-retries $LFTP_RETRIES"
	echo "set net:timeout $LFTP_NET_TIMEOUT"
	echo "set net:reconnect-interval-base $LFTP_RETRY_DELAY"
	echo "set net:reconnect-interval-multiplier 1"
	echo "open \"$FTP_HOST\""
	echo "user \"$FTP_USER\" \"$FTP_PASS\""
	echo "mkdir -p -f \"${REMOTE_BASE}/${PROVIDER_ID}/releases\""

	for local_dir in "${RELEASE_DIRS[@]}"; do
		snapshot="$(basename -- "$local_dir")"
		remote_dir="${REMOTE_BASE}/${PROVIDER_ID}/releases/${snapshot}"
		echo "mkdir -p -f \"$remote_dir\""
		echo "mirror -R --delete --verbose \"$local_dir\" \"$remote_dir\""
	done

	# Publish manifests only after every release file is in place.
	echo "mkdir -p -f \"${REMOTE_BASE}/${PROVIDER_ID}\""
	echo "put \"$PROVIDER_INDEX\" -o \"${REMOTE_BASE}/${PROVIDER_ID}/index.json\""
	echo "put \"$GLOBAL_INDEX\" -o \"${REMOTE_BASE}/index.json\""
	echo "bye"
} > "$LFTP_CMDS"

lftp -f "$LFTP_CMDS"

echo "Deployed ${RELEASE_FILE_COUNT} ${PROVIDER_ID} statistics files and manifests to /${REMOTE_BASE}/"
