# Host-level ops scripts

Unlike `scripts/`, nothing here runs inside the `futbol-modelo` Docker
image or as a Kubernetes CronJob. These run directly on a specific
host's own crontab -- see each script's header for which host and why.

## backup-futbol-db.sh

Deployed to `docker-host` (`~/scripts/backup-futbol-db.sh`), runs
nightly at 03:15 via crontab. Dumps the live `futbol` database over the
network using the read-only `futbol_backup` role (see
`sql/migrations/0004_create_backup_role.sql`), lands the dump on
docker-host -- a separate physical host from the Postgres LXC
(192.168.4.210), so a disk failure there doesn't take the backups with
it. Keeps the last 14 daily dumps in `~/futbol-modelo-backups/`.

Requires `~/.futbol_backup_dsn` on docker-host (chmod 600, not
committed anywhere): a single line,
`host=192.168.4.210 dbname=futbol user=futbol_backup password=...`.

### Restoring from a dump

```bash
# Against a fresh/throwaway target database (created with no roles
# other than its own postgres superuser):
docker run --rm -v /path/to/dump/dir:/backup postgres:15 \
    pg_restore -h <target-host> -U postgres -d futbol \
    --no-owner --role=postgres /backup/futbol-modelo-<timestamp>.dump
```

Expect ~17 harmless `role "futbol_ro" does not exist` errors at the
end (the dump includes `GRANT ... TO futbol_ro` statements from the
live database; a fresh target has no such role) -- `pg_restore` prints
`warning: errors ignored on restore: 17` and the schema/data restore
itself is unaffected. Recreate `futbol_ro`/`futbol_backup` separately
if the target needs to serve the API for real, rather than expecting
the dump to bring roles with it.

For restoring onto a database that already has objects in it, add
`--clean --if-exists` to drop existing objects first -- not appropriate
for replaying onto the live database while it's serving traffic.

### Restore drill

Run for real on 2026-08-27: restored a live dump into a throwaway
`postgres:15` container on docker-host and compared row counts against
the live database for `matches`, `predictions`, `prediction_grades`,
`teams`, and `team_match_stats` -- all five matched exactly (8112 /
4578 / 1095 / 154 / 13926). Confirms the backups are actually
restorable, not just assumed to be. Worth re-running this drill
periodically rather than trusting it forever from one point-in-time
check.
