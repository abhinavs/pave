#!/usr/bin/env bash
# Nightly PostgreSQL backup. Run by backup.service via backup.timer, never by
# hand on the server (use `fab production backup` for an ad-hoc, verified dump).
#
# Dumps $DATABASE_URL to a gzipped file under /srv/pave/backups, writes a
# sha256 sidecar so restores can be integrity-checked, and prunes anything
# older than the retention window.
set -euo pipefail

APP_DIR="/srv/pave"
BACKUP_DIR="${APP_DIR}/backups"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
ENV_FILE="${APP_DIR}/current/.env.production"

# DATABASE_URL lives in the same env file the services load.
# shellcheck disable=SC1090
set -a
source "${ENV_FILE}"
set +a

mkdir -p "${BACKUP_DIR}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${BACKUP_DIR}/db-${stamp}.sql.gz"

pg_dump "${DATABASE_URL}" | gzip > "${out}"
sha256sum "${out}" > "${out}.sha256"

# Retention: drop dumps (and their sidecars) older than the window.
find "${BACKUP_DIR}" -name 'db-*.sql.gz*' -mtime "+${RETENTION_DAYS}" -delete

echo "backup written: ${out}"
