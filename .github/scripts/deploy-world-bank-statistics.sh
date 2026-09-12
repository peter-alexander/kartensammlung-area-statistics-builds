#!/usr/bin/env bash
set -euo pipefail

DIST_DIR="${1:-dist/statistics}"
PROVIDER_ID="${PROVIDER_ID:-world-bank}"
REMOTE_BASE="AreaStatistics/statistics"
PUBLIC_BASE="${STATISTICS_PUBLIC_BASE:-https://tiles.radlobby.at/AreaStatistics/statistics}"
PUBLIC_BASE="${PUBLIC_BASE%/}"

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

ACTIVE_SNAPSHOT="$(python - "$PROVIDER_INDEX" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("activeSnapshot", ""))
PY
)"

if [[ ! "$ACTIVE_SNAPSHOT" =~ ^[0-9a-f]{16}$ ]]; then
	echo "Invalid active snapshot in $PROVIDER_INDEX: $ACTIVE_SNAPSHOT" >&2
	exit 1
fi

ACTIVE_RELEASE_DIR="${RELEASE_DIR}/${ACTIVE_SNAPSHOT}"
if [ ! -d "$ACTIVE_RELEASE_DIR" ]; then
	echo "Active snapshot directory is missing: $ACTIVE_RELEASE_DIR" >&2
	exit 1
fi

mapfile -t RELEASE_PATHS < <(python - "$PROVIDER_INDEX" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for indicator in payload.get("indicators", []):
	path = str(indicator.get("path", "")).strip()
	if path:
		print(path)
PY
)

if [ "${#RELEASE_PATHS[@]}" -eq 0 ]; then
	echo "Provider index contains no release paths: $PROVIDER_INDEX" >&2
	exit 1
fi

EXPECTED_PREFIX="releases/${ACTIVE_SNAPSHOT}/"
for path in "${RELEASE_PATHS[@]}"; do
	if [[ "$path" != "${EXPECTED_PREFIX}"*.json ]]; then
		echo "Release path does not belong to active snapshot: $path" >&2
		exit 1
	fi
	if [ ! -s "${PROVIDER_DIR}/${path}" ]; then
		echo "Missing or empty release file: ${PROVIDER_DIR}/${path}" >&2
		exit 1
	fi
done

RELEASE_FILE_COUNT="${#RELEASE_PATHS[@]}"

if ! command -v lftp >/dev/null 2>&1; then
	echo "lftp is required for statistics deployment." >&2
	exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
	echo "curl is required for statistics deployment verification." >&2
	exit 1
fi

SSL_VERIFY="${LFTP_SSL_VERIFY:-no}"
LFTP_RETRIES="${LFTP_RETRIES:-10}"
LFTP_RETRY_DELAY="${LFTP_RETRY_DELAY:-15}"
LFTP_NET_TIMEOUT="${LFTP_NET_TIMEOUT:-30}"
LFTP_TEMP_FILE_NAME=".in.${PROVIDER_ID}.${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-0}.*"
CACHE_BUST="run=${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-0}"
CURL_RETRY=(
	--connect-timeout 10
	--max-time 30
	--retry 2
	--retry-delay 2
	--retry-all-errors
)

UPLOAD_CMDS="$(mktemp)"
PUBLISH_CMDS="$(mktemp)"
LIST_CMDS="$(mktemp)"
DELETE_CMDS="$(mktemp)"
PUBLIC_TMP_DIR="$(mktemp -d)"
trap 'rm -f "$UPLOAD_CMDS" "$PUBLISH_CMDS" "$LIST_CMDS" "$DELETE_CMDS"; rm -rf "$PUBLIC_TMP_DIR"' EXIT

write_lftp_preamble() {
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
}

# Stage only the active immutable snapshot first. Existing manifests and older
# snapshots remain untouched until the new release has passed a full public
# byte-for-byte verification.
{
	write_lftp_preamble
	echo "mkdir -p -f \"${REMOTE_BASE}/${PROVIDER_ID}/releases\""
	echo "mkdir -p -f \"${REMOTE_BASE}/${PROVIDER_ID}/releases/${ACTIVE_SNAPSHOT}\""
	echo "mirror -R --delete --verbose \"$ACTIVE_RELEASE_DIR\" \"${REMOTE_BASE}/${PROVIDER_ID}/releases/${ACTIVE_SNAPSHOT}\""
	echo "bye"
} > "$UPLOAD_CMDS"

lftp -f "$UPLOAD_CMDS"

for index in "${!RELEASE_PATHS[@]}"; do
	path="${RELEASE_PATHS[$index]}"
	local_file="${PROVIDER_DIR}/${path}"
	public_file="${PUBLIC_TMP_DIR}/release-${index}.json"
	curl --fail --silent --show-error --location \
		"${CURL_RETRY[@]}" \
		"${PUBLIC_BASE}/${PROVIDER_ID}/${path}?${CACHE_BUST}" \
		--output "$public_file"
	cmp "$local_file" "$public_file"
done

echo "Verified ${RELEASE_FILE_COUNT} staged ${PROVIDER_ID} release files byte-for-byte."

# Switch manifests only after the staged snapshot is known-good. Temporary-file
# uploads plus same-directory rename keep index publication atomic.
{
	write_lftp_preamble
	echo "set xfer:use-temp-file true"
	echo "set xfer:temp-file-name \"$LFTP_TEMP_FILE_NAME\""
	echo "mkdir -p -f \"${REMOTE_BASE}/${PROVIDER_ID}\""
	echo "put \"$PROVIDER_INDEX\" -o \"${REMOTE_BASE}/${PROVIDER_ID}/index.json\""
	echo "put \"$GLOBAL_INDEX\" -o \"${REMOTE_BASE}/index.json\""
	echo "bye"
} > "$PUBLISH_CMDS"

lftp -f "$PUBLISH_CMDS"

curl --fail --silent --show-error --location \
	"${CURL_RETRY[@]}" \
	"${PUBLIC_BASE}/${PROVIDER_ID}/index.json?${CACHE_BUST}" \
	--output "${PUBLIC_TMP_DIR}/provider-index.json"
cmp "$PROVIDER_INDEX" "${PUBLIC_TMP_DIR}/provider-index.json"

curl --fail --silent --show-error --location \
	"${CURL_RETRY[@]}" \
	"${PUBLIC_BASE}/index.json?${CACHE_BUST}" \
	--output "${PUBLIC_TMP_DIR}/global-index.json"
cmp "$GLOBAL_INDEX" "${PUBLIC_TMP_DIR}/global-index.json"

echo "Verified ${PROVIDER_ID} manifests byte-for-byte."

# No historical releases are retained permanently. Only after both the active
# snapshot and the published manifests are verified do we remove older hashed
# snapshot directories. Non-snapshot entries are deliberately left untouched.
{
	write_lftp_preamble
	echo "cls -1 \"${REMOTE_BASE}/${PROVIDER_ID}/releases\""
	echo "bye"
} > "$LIST_CMDS"

mapfile -t REMOTE_RELEASES < <(lftp -f "$LIST_CMDS" | sed 's#/$##')
DELETE_COUNT=0
{
	write_lftp_preamble
	for entry in "${REMOTE_RELEASES[@]}"; do
		snapshot="${entry##*/}"
		if [[ "$snapshot" =~ ^[0-9a-f]{16}$ ]] && [ "$snapshot" != "$ACTIVE_SNAPSHOT" ]; then
			echo "rm -r -f \"${REMOTE_BASE}/${PROVIDER_ID}/releases/${snapshot}\""
			DELETE_COUNT=$((DELETE_COUNT + 1))
		fi
	done
	echo "bye"
} > "$DELETE_CMDS"

if [ "$DELETE_COUNT" -gt 0 ]; then
	lftp -f "$DELETE_CMDS"
fi

echo "Deployed and verified ${RELEASE_FILE_COUNT} ${PROVIDER_ID} statistics files in snapshot ${ACTIVE_SNAPSHOT}."
echo "Removed ${DELETE_COUNT} superseded ${PROVIDER_ID} release snapshot(s); only the active snapshot is retained."
