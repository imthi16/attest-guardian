#!/usr/bin/env bash
# Restore a database and object pair produced by scripts/backup.sh.
#
# Refuses a mismatched pair on purpose. Restoring a database from Tuesday
# alongside objects from Thursday produces a system where citations resolve to
# the wrong text: every check passes, every answer looks grounded, and the
# evidence quoted is not the evidence stored. Nothing downstream can detect it,
# so it is caught here or not at all.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <backup-directory>" >&2
  exit 2
fi

SOURCE="$1"
POSTGRES_USER="${POSTGRES_USER:-attest}"
POSTGRES_DB="${POSTGRES_DB:-attest}"
COMPOSE="${COMPOSE:-docker compose}"

for required in manifest.json database.dump; do
  [[ -f "${SOURCE}/${required}" ]] || { echo "missing ${required} in ${SOURCE}" >&2; exit 1; }
done

EXPECTED="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['database_sha256'])" "${SOURCE}/manifest.json")"
ACTUAL="$(sha256sum "${SOURCE}/database.dump" | cut -d' ' -f1)"
if [[ "${EXPECTED}" != "${ACTUAL}" ]]; then
  echo "database.dump does not match its manifest; refusing to restore a corrupt dump" >&2
  exit 1
fi

echo "Restoring ${SOURCE} into ${POSTGRES_DB}."
echo "This REPLACES current data. The application must not be running."
read -r -p "Type the database name to continue: " CONFIRM
[[ "${CONFIRM}" == "${POSTGRES_DB}" ]] || { echo "aborted" >&2; exit 1; }

# `--clean --if-exists` so a partial previous restore does not wedge this one.
${COMPOSE} exec -T postgres pg_restore \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" \
  --clean --if-exists --no-owner --no-privileges \
  < "${SOURCE}/database.dump"

if [[ -d "${SOURCE}/objects" ]]; then
  ${COMPOSE} run --rm --no-deps --entrypoint sh minio-create-bucket -c "
    mc alias set restore \"\${MINIO_ENDPOINT}\" \"\${MINIO_ROOT_USER}\" \"\${MINIO_ROOT_PASSWORD}\" >/dev/null &&
    mc mirror --quiet --overwrite /backup/objects \"restore/\${S3_BUCKET:-attest-documents}\"
  "
else
  echo "WARNING: no objects/ directory. The database will reference documents whose" >&2
  echo "bytes are absent: every citation into them will fail to resolve." >&2
fi

# The schema may predate the running code. Migrations are forward-only, so this
# is the step that makes a restored database usable by the current release.
echo
echo "Now run migrations before starting the application:"
echo "  ${COMPOSE} --profile application run --rm migrate"
echo "Then verify with: scripts/smoke.sh <base-url>"
