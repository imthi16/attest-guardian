#!/usr/bin/env bash
# Back up everything that cannot be rebuilt: the database and the stored objects.
#
# Two stores, and they are not independent. A `documents` row points at a
# storage key; a chunk's citation is only resolvable while both exist. Backing
# up one without the other produces a restore where answers cite evidence that
# is gone — worse than no backup, because it looks like it worked.
#
# So both are captured in one run, under one timestamp, and the restore script
# refuses a pair that does not match. There is still a window: this is not a
# consistent snapshot across two systems, and a document uploaded between the
# two steps will be in storage and not in the dump. That direction is the safe
# one — an orphaned object wastes space, an orphaned row breaks an answer — and
# it is why the database is dumped *first*.
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_ROOT}/${STAMP}"

POSTGRES_USER="${POSTGRES_USER:-attest}"
POSTGRES_DB="${POSTGRES_DB:-attest}"
S3_BUCKET="${S3_BUCKET:-attest-documents}"
COMPOSE="${COMPOSE:-docker compose}"

mkdir -p "${DEST}"
echo "backing up to ${DEST}"

# Database first: see the note above about which orphan is survivable.
# `--format=custom` so `pg_restore` can run in parallel and be selective.
${COMPOSE} exec -T postgres pg_dump \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" \
  --format=custom \
  --no-owner \
  --no-privileges \
  > "${DEST}/database.dump"
echo "  database.dump  $(du -h "${DEST}/database.dump" | cut -f1)"

# Objects. `mc mirror` rather than a tarball so a restore can be incremental and
# a large corpus does not need twice its size in scratch space.
${COMPOSE} run --rm --no-deps \
  --entrypoint sh minio-create-bucket -c "
    mc alias set backup \"\${MINIO_ENDPOINT}\" \"\${MINIO_ROOT_USER}\" \"\${MINIO_ROOT_PASSWORD}\" >/dev/null &&
    mc mirror --quiet --overwrite \"backup/${S3_BUCKET}\" /backup/objects
  " || { echo "object backup failed; the database dump alone is NOT a usable backup" >&2; exit 1; }

# The manifest is what makes the pair verifiable. A restore that silently mixed
# a database from Tuesday with objects from Thursday would produce citations
# resolving to the wrong text, which no error would ever report.
cat > "${DEST}/manifest.json" <<JSON
{
  "created_at": "${STAMP}",
  "database": "${POSTGRES_DB}",
  "bucket": "${S3_BUCKET}",
  "database_sha256": "$(sha256sum "${DEST}/database.dump" | cut -d' ' -f1)",
  "schema_revision": "$(${COMPOSE} exec -T postgres psql -tAX -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c 'SELECT version_num FROM alembic_version' 2>/dev/null || echo unknown)"
}
JSON

echo "done. Restore with: scripts/restore.sh ${DEST}"
echo
echo "A backup nobody has restored is a hypothesis. Test it on staging."
