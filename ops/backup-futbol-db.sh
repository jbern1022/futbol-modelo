#!/usr/bin/env bash
# futbol-modelo — off-box database backup.
#
# Dumps the futbol database from the Postgres LXC (192.168.4.210) over
# the network, using the dedicated futbol_backup role (read-only via
# PostgreSQL's builtin pg_read_all_data -- never the write-capable
# FUTBOL_DSN, so this host never holds a credential that can touch the
# live ledger). pg_dump runs via the official postgres:15 image (no
# local postgresql-client install needed on this host). Verifies the
# dump is actually restorable, then keeps it here -- a separate
# physical host from the Postgres LXC, so an LXC/disk failure there
# doesn't take the backups with it.
#
# Deployed to and run from docker-host's crontab (see CLAUDE.md), not
# from a dev machine and not in Kubernetes -- this is host-level ops
# tooling, unlike scripts/ which all run inside the futbol-modelo
# image via k8s CronJobs. Mirrors the conventions of docker-host's
# existing ~/scripts/backup-db.sh (a sibling project's own DB backup).
#
# Requires on docker-host: ~/.futbol_backup_dsn (chmod 600), containing
# a single line: host=192.168.4.210 dbname=futbol user=futbol_backup
# password=... -- see sql/migrations/0004_create_backup_role.sql for
# how that role was created.
#
# Retention: keeps the last 14 daily dumps; older ones are pruned
# automatically.

set -euo pipefail

PG_IMAGE="postgres:15"
DSN_FILE="$HOME/.futbol_backup_dsn"
BACKUP_DIR="/home/joe/futbol-modelo-backups"
RETENTION_DAYS=14

# A real dump of this database is ~4.6MB. Anything under this is a
# truncated or empty write, not a small database -- see
# ~/scripts/backup-db.sh's own comment for why this check exists (a
# full disk once produced a 0-byte file that looked like success).
MIN_DUMP_BYTES=$((1024 * 1024))

# pg_dump needs room for the dump itself plus working space. Checked up
# front so a doomed run fails immediately and loudly, rather than after
# writing a partial file.
MIN_FREE_KB=$((1024 * 1024)) # 1 GiB

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
DUMP_FILE="futbol-modelo-${TIMESTAMP}.dump"
HOST_PATH="${BACKUP_DIR}/${DUMP_FILE}"

mkdir -p "$BACKUP_DIR"

fail() {
    echo "[$(date)] BACKUP FAILED: $*" >&2
    exit 1
}

# Never leave a partial dump behind: a 0-byte file in the backup
# directory is worse than no file, because it looks like a backup
# exists.
cleanup_partial() {
    local code=$?
    if [ $code -ne 0 ]; then
        rm -f "$HOST_PATH"
        echo "[$(date)] Cleaned up partial dump after failure (exit ${code})." >&2
    fi
}
trap cleanup_partial EXIT

echo "[$(date)] Starting backup: ${DUMP_FILE}"

# Prune BEFORE dumping, not after -- so a full disk doesn't get stuck
# failing the same way every run with no path to recovery.
find "$BACKUP_DIR" -name "futbol-modelo-*.dump" -mtime "+${RETENTION_DAYS}" -delete

FREE_KB=$(df --output=avail -k "$BACKUP_DIR" | tail -1 | tr -d ' ')
if [ "$FREE_KB" -lt "$MIN_FREE_KB" ]; then
    fail "only $((FREE_KB / 1024))MB free in ${BACKUP_DIR}, need $((MIN_FREE_KB / 1024))MB"
fi

# Custom format (-F c): compressed, supports selective/parallel restore.
docker run --rm \
    -v "${BACKUP_DIR}:/backup" \
    -v "${DSN_FILE}:/dsn:ro" \
    "$PG_IMAGE" bash -c 'pg_dump "$(cat /dsn)" -F c -f "/backup/'"${DUMP_FILE}"'"' \
    || fail "pg_dump returned non-zero"

# Verify the archive is readable before trusting it. pg_restore --list
# exits non-zero on a truncated or corrupt archive, which catches the
# failure mode a size check alone would miss.
docker run --rm -v "${BACKUP_DIR}:/backup" "$PG_IMAGE" \
    pg_restore --list "/backup/${DUMP_FILE}" >/dev/null \
    || fail "dump is not a readable pg_dump archive"

DUMP_BYTES=$(stat -c %s "$HOST_PATH")
if [ "$DUMP_BYTES" -lt "$MIN_DUMP_BYTES" ]; then
    fail "dump is ${DUMP_BYTES} bytes, expected at least ${MIN_DUMP_BYTES} -- treating as truncated"
fi

echo "[$(date)] Dump created and verified: $(du -h "$HOST_PATH" | cut -f1)"
echo "[$(date)] Backup complete."
