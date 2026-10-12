#!/usr/bin/env bash
# Run a read-only InfluxQL query against the source database and print the JSON result.
#
# Usage:
#   scripts/influx-query.sh                                  # SHOW MEASUREMENTS
#   scripts/influx-query.sh 'SELECT * FROM "m" LIMIT 5'
#
# Reads .env and .env.local from the main checkout, so it also works inside worktrees.
# Uses HTTP GET, which InfluxDB 1.x only allows for SELECT and SHOW: the server
# rejects anything that would write.
set -euo pipefail

query=${1:-SHOW MEASUREMENTS}

repo_root=$(cd "$(git -C "$(dirname "$0")" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)

# Parse KEY=VALUE lines instead of sourcing, so passwords with $, spaces or quotes
# are taken literally and the files can't run code.
load_env_file() {
  local file=$1 key value
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    key=${line%%=*}
    value=${line#*=}
    [[ "$key" =~ ^INFLUX_[A-Z_]+$ ]] || continue
    if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then
      value=${BASH_REMATCH[1]}
    fi
    export "$key=$value"
  done <"$file"
}

load_env_file "$repo_root/.env"
load_env_file "$repo_root/.env.local"

for name in INFLUX_URL INFLUX_DATABASE INFLUX_CLIENT_CERT INFLUX_CLIENT_KEY INFLUX_USERNAME INFLUX_PASSWORD; do
  if [[ -z "${!name:-}" ]]; then
    echo "error: $name is not set (check $repo_root/.env and .env.local)" >&2
    exit 1
  fi
done
for file in "$INFLUX_CLIENT_CERT" "$INFLUX_CLIENT_KEY"; do
  if [[ ! -r "$file" ]]; then
    echo "error: cannot read $file" >&2
    exit 1
  fi
done

# Pass credentials via a curl config on stdin, so they never show up in `ps` or in the URL.
escape_for_curl_config() {
  local text=${1//\\/\\\\}
  printf '%s' "${text//\"/\\\"}"
}
credentials="user = \"$(escape_for_curl_config "$INFLUX_USERNAME"):$(escape_for_curl_config "$INFLUX_PASSWORD")\""

response=$(printf '%s\n' "$credentials" | curl --config - \
  --silent --show-error --fail-with-body \
  --max-time "${INFLUX_TIMEOUT:-30}" --retry 2 --retry-delay 2 \
  --cert "$INFLUX_CLIENT_CERT" --key "$INFLUX_CLIENT_KEY" \
  --get "$INFLUX_URL/query" \
  --data-urlencode "db=$INFLUX_DATABASE" \
  --data-urlencode "q=$query") || {
  echo "error: request failed" >&2
  [[ -n "${response:-}" ]] && echo "$response" >&2
  exit 1
}

echo "$response" | jq .

# InfluxDB answers HTTP 200 even when a statement fails; the error is in the body.
if echo "$response" | jq -e '[.error?, .results[]?.error?] | any' >/dev/null; then
  echo "error: query failed (see above)" >&2
  exit 1
fi
