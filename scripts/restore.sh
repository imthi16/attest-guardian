#!/usr/bin/env bash
# Restore a database and object pair produced by scripts/backup.sh.
#
# Everything is validated *before* anything is destroyed. An earlier version
# checked the manifest, ran `pg_restore --clean`, and only then warned that the
# objects directory was missing — by which point the database had already been
# replaced and every restored document row pointed at bytes that were not there.
# The order below is the whole point of this script.
#
# Both digests are checked, because a mismatched pair is the failure nothing
# downstream can catch: a database from Tuesday with objects from Thursday
# produces citations that resolve to the wrong text, with every check green.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <backup-directory>" >&2
  exit 2
fi

SOURCE="$1"
: "${DATABASE_URL:?set DATABASE_URL to the DSN to restore into}"
: "${S3_ENDPOINT:?set S3_ENDPOINT}"
: "${S3_ACCESS_KEY:?set S3_ACCESS_KEY}"
: "${S3_SECRET_KEY:?set S3_SECRET_KEY}"
: "${S3_BUCKET:?set S3_BUCKET}"

PG_DSN="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"

for tool in pg_restore mc sha256sum python3; do
  command -v "${tool}" >/dev/null || { echo "${tool} is required but not on PATH" >&2; exit 1; }
done

# --- validate everything before touching anything ---------------------------

for required in manifest.json database.dump; do
  [[ -f "${SOURCE}/${required}" ]] || { echo "missing ${required} in ${SOURCE}" >&2; exit 1; }
done

read_manifest() {
  python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get(sys.argv[2],''))" \
    "${SOURCE}/manifest.json" "$1"
}

EXPECTED_DB="$(read_manifest database_sha256)"
ACTUAL_DB="$(sha256sum "${SOURCE}/database.dump" | cut -d' ' -f1)"
if [[ "${EXPECTED_DB}" != "${ACTUAL_DB}" ]]; then
  echo "database.dump does not match its manifest; refusing a corrupt dump" >&2
  exit 1
fi

EXPECTED_OBJECTS="$(read_manifest objects_sha256)"
if [[ -z "${EXPECTED_OBJECTS}" ]]; then
  echo "manifest records no objects digest; this backup predates pair verification." >&2
  echo "Restoring it cannot be verified as consistent. Take a fresh backup." >&2
  exit 1
fi

# The object snapshot is required, not optional. Without it the restore
# completes and every citation into a restored document fails to resolve — a
# database that looks intact and answers that cannot be grounded.
if [[ "${EXPECTED_OBJECTS}" != "empty" && ! -d "${SOURCE}/objects" ]]; then
  echo "backup records ${EXPECTED_OBJECTS} objects but ${SOURCE}/objects is missing;" >&2
  echo "refusing to restore a database whose documents would have no bytes" >&2
  exit 1
fi

if [[ -d "${SOURCE}/objects" ]]; then
  ACTUAL_OBJECTS="$(
    find "${SOURCE}/objects" -type f -print0 \
      | LC_ALL=C sort -z \
      | xargs -0 sha256sum \
      | sed "s|${SOURCE}/objects/||" \
      | sha256sum | cut -d' ' -f1
  )"
  [[ "$(find "${SOURCE}/objects" -type f | wc -l | tr -d ' ')" == "0" ]] && ACTUAL_OBJECTS="empty"
  if [[ "${EXPECTED_OBJECTS}" != "${ACTUAL_OBJECTS}" ]]; then
    echo "objects/ does not match its manifest." >&2
    echo "This is the failure that cannot be detected later: restoring a database" >&2
    echo "beside objects from another moment makes citations resolve to the wrong" >&2
    echo "text, with every check passing. Refusing." >&2
    exit 1
  fi
fi

# --- confirmed and validated; now destructive -------------------------------

echo "Restoring ${SOURCE}."
echo "This REPLACES the database at ${PG_DSN%%\?*}. The application must not be running."
read -r -p "Type RESTORE to continue: " CONFIRM
[[ "${CONFIRM}" == "RESTORE" ]] || { echo "aborted" >&2; exit 1; }

pg_restore --dbname="${PG_DSN}" --clean --if-exists --no-owner --no-privileges \
  < "${SOURCE}/database.dump"

if [[ -d "${SOURCE}/objects" ]]; then
  mc alias set attest-restore "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}" >/dev/null
  mc mirror --quiet --overwrite "${SOURCE}/objects" "attest-restore/${S3_BUCKET}"
fi

# The dump may predate the running release, and migrations are forward-only.
echo
echo "Now run migrations before starting the application:"
echo "  docker compose -f docker-compose.yml -f deploy/docker-compose.production.yml \\"
echo "    --profile application run --rm migrate"
echo "Then verify with: scripts/smoke.sh <base-url>"
