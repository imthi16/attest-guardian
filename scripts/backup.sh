#!/usr/bin/env bash
# Back up everything that cannot be rebuilt: the database and the stored objects.
#
# Connects to the deployment's *configured* stores, read from the same
# environment the application uses. An earlier version of this script ran
# `docker compose exec postgres pg_dump`, which in the documented production
# topology reaches a service that is not running — and if somebody started it,
# would faithfully back up an empty local database while reporting success. A
# backup script that cannot fail loudly is worse than none.
#
# The two stores are not independent. A `documents` row points at a storage key,
# and a citation is only resolvable while both exist, so both are captured under
# one timestamp and both are digested into the manifest. `restore.sh` refuses a
# pair whose digests do not match: a database from Tuesday beside objects from
# Thursday makes citations resolve to the wrong text, which nothing downstream
# can detect.
#
# Requires `pg_dump` (matching the server's major version), `mc`, and
# `sha256sum` on PATH.
set -euo pipefail

: "${DATABASE_URL:?set DATABASE_URL to the DSN this deployment uses}"
: "${S3_ENDPOINT:?set S3_ENDPOINT}"
: "${S3_ACCESS_KEY:?set S3_ACCESS_KEY}"
: "${S3_SECRET_KEY:?set S3_SECRET_KEY}"
: "${S3_BUCKET:?set S3_BUCKET}"

BACKUP_ROOT="${BACKUP_ROOT:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_ROOT}/${STAMP}"

# SQLAlchemy's driver suffix is not understood by libpq.
PG_DSN="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"

for tool in pg_dump mc sha256sum; do
  command -v "${tool}" >/dev/null || { echo "${tool} is required but not on PATH" >&2; exit 1; }
done

mkdir -p "${DEST}/objects"
echo "backing up to ${DEST}"

cat >&2 <<'WARNING'
NOTE: this is not an atomic snapshot across two systems. A permanent delete
between the two steps can purge an object whose row is already in the dump,
leaving a restored citation pointing at bytes that are gone. Stop the worker —
or pause purging — for the duration if that matters to you.
WARNING

# Database first. A document uploaded between the steps then lands in storage
# and not in the dump: an orphaned object wastes space, an orphaned row breaks
# an answer, and only one of those is survivable.
pg_dump --dbname="${PG_DSN}" --format=custom --no-owner --no-privileges \
  > "${DEST}/database.dump"
echo "  database.dump  $(du -h "${DEST}/database.dump" | cut -f1)"

mc alias set attest-backup "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}" >/dev/null
mc mirror --quiet --overwrite "attest-backup/${S3_BUCKET}" "${DEST}/objects"
OBJECT_COUNT="$(find "${DEST}/objects" -type f | wc -l | tr -d ' ')"
echo "  objects        ${OBJECT_COUNT} file(s)"

# A digest over the object *tree*, not only the database dump. Without it the
# runbook's promise that a mismatched pair is refused would simply be false:
# swapping the objects directory for another date's would pass every check.
object_digest() {
  if [[ "${OBJECT_COUNT}" == "0" ]]; then
    echo "empty"
    return
  fi
  # Path and content, sorted, so the digest is stable across filesystems.
  find "${DEST}/objects" -type f -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum \
    | sed "s|${DEST}/objects/||" \
    | sha256sum | cut -d' ' -f1
}

cat > "${DEST}/manifest.json" <<JSON
{
  "created_at": "${STAMP}",
  "bucket": "${S3_BUCKET}",
  "database_sha256": "$(sha256sum "${DEST}/database.dump" | cut -d' ' -f1)",
  "objects_sha256": "$(object_digest)",
  "object_count": ${OBJECT_COUNT}
}
JSON

echo "done. Restore with: scripts/restore.sh ${DEST}"
echo
echo "A backup nobody has restored is a hypothesis. Test it on staging."
