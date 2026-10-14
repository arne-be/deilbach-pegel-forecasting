#!/usr/bin/env bash
# Rewrites db/schema.sql and src/pegel/adapters/storage/records.py from db/migrations.
#
# Migrates a throwaway Postgres container with the pinned dbmate image, so the
# dump looks the same on every machine and in CI, and no live database is touched.
# Needs Docker and uv.
set -euo pipefail

POSTGRES_IMAGE="postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24"
DBMATE_IMAGE="ghcr.io/amacneil/dbmate:2.36.0@sha256:520c740c6e0ad73fde2cd1ea7e2b779aaf789d22aca8858f87a478e7094535fb"  # same version as mise.toml and .github/workflows/infra.yml
NAME="pegel-schema-$$"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker network rm "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$NAME" >/dev/null
docker run -d --name "$NAME" --network "$NAME" -p 127.0.0.1::5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=pegel "$POSTGRES_IMAGE" >/dev/null

until docker exec "$NAME" pg_isready -U postgres -d pegel -h 127.0.0.1 >/dev/null 2>&1; do
  sleep 1
done

# In Neon these roles are created by hand (docs/setup-neon.md); the grants need them.
docker exec "$NAME" psql -q -U postgres -d pegel \
  -c "CREATE ROLE pegel_jobs NOLOGIN; CREATE ROLE pegel_api NOLOGIN; CREATE ROLE pegel_grafana NOLOGIN;"

docker run --rm --network "$NAME" -v "$repo_root/db:/db" \
  -e DATABASE_URL="postgres://postgres:postgres@$NAME:5432/pegel?sslmode=disable" \
  "$DBMATE_IMAGE" --wait migrate

host_port="$(docker port "$NAME" 5432/tcp | head -n 1 | sed 's/.*://')"
DATABASE_URL="postgres://postgres:postgres@127.0.0.1:$host_port/pegel?sslmode=disable" \
  uv run --directory "$repo_root" python scripts/generate_records.py
