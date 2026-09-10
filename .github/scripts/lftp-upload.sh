#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
	echo "Usage: $0 <local-path> <remote-path>" >&2
	exit 1
fi

: "${EASYNAME_FTP_HOST:?EASYNAME_FTP_HOST is required}"
: "${EASYNAME_FTP_USER:?EASYNAME_FTP_USER is required}"
: "${EASYNAME_FTP_PASSWORD:?EASYNAME_FTP_PASSWORD is required}"

LOCAL_PATH="$1"
REMOTE_PATH="$2"
REMOTE_PATH="${REMOTE_PATH#/}"

if [ ! -e "$LOCAL_PATH" ]; then
	echo "Local path does not exist: $LOCAL_PATH" >&2
	exit 1
fi

SSL_VERIFY="${LFTP_SSL_VERIFY:-no}"
PARALLEL="${LFTP_PARALLEL:-6}"
FTP_CONNECT_TIMEOUT="${FTP_CONNECT_TIMEOUT:-30}"
FTP_RETRIES="${FTP_RETRIES:-10}"
FTP_RETRY_DELAY="${FTP_RETRY_DELAY:-30}"
FTP_RETRY_MAX_TIME="${FTP_RETRY_MAX_TIME:-900}"

if [ -f "$LOCAL_PATH" ] && command -v curl >/dev/null 2>&1; then
	CURL_URL="ftp://${EASYNAME_FTP_HOST}/${REMOTE_PATH}"
	CURL_ARGS=(
		--fail
		--silent
		--show-error
		--ftp-ssl-reqd
		--ftp-pasv
		--ftp-create-dirs
		--connect-timeout "$FTP_CONNECT_TIMEOUT"
		--retry "$FTP_RETRIES"
		--retry-delay "$FTP_RETRY_DELAY"
		--retry-max-time "$FTP_RETRY_MAX_TIME"
		--retry-all-errors
		--user "${EASYNAME_FTP_USER}:${EASYNAME_FTP_PASSWORD}"
		--upload-file "$LOCAL_PATH"
		"$CURL_URL"
	)

	if [ "$SSL_VERIFY" = "no" ]; then
		CURL_ARGS+=(--insecure)
	fi

	curl "${CURL_ARGS[@]}"
	exit 0
fi

if ! command -v lftp >/dev/null 2>&1; then
	echo "lftp ist nicht installiert (für Verzeichnis-Uploads erforderlich)." >&2
	exit 1
fi

LFTP_RETRIES="${LFTP_RETRIES:-10}"
LFTP_RETRY_DELAY="${LFTP_RETRY_DELAY:-30}"
LFTP_NET_TIMEOUT="${LFTP_NET_TIMEOUT:-30}"

LFTP_CMDS=$(mktemp)
trap 'rm -f "$LFTP_CMDS"' EXIT

{
	echo "set ftp:ssl-force true"
	echo "set ftp:passive-mode true"
	echo "set ssl:verify-certificate $SSL_VERIFY"
	echo "set net:max-retries $LFTP_RETRIES"
	echo "set net:timeout $LFTP_NET_TIMEOUT"
	echo "set net:reconnect-interval-base $LFTP_RETRY_DELAY"
	echo "set net:reconnect-interval-multiplier 1"
	echo "open "$EASYNAME_FTP_HOST""
	echo "user "$EASYNAME_FTP_USER" "$EASYNAME_FTP_PASSWORD""

	if [ -d "$LOCAL_PATH" ]; then
		echo "mirror -R --delete --verbose --parallel=$PARALLEL "$LOCAL_PATH" "$REMOTE_PATH""
	else
		REMOTE_DIR="$(dirname -- "$REMOTE_PATH")"
		REMOTE_FILE="$(basename -- "$REMOTE_PATH")"
		echo "mkdir -p "$REMOTE_DIR""
		echo "put "$LOCAL_PATH" -o "$REMOTE_DIR/$REMOTE_FILE""
	fi

	echo 'bye'
} > "$LFTP_CMDS"

lftp -f "$LFTP_CMDS"
