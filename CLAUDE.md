# futbol-modelo — Claude Code context

Calibrated soccer prediction system: Dixon-Coles + LightGBM props models,
Next.js/FastAPI frontend, Petey (Ollama-backed Q&A), all deployed on a
self-managed Kubernetes cluster. Live at https://futbol.josephbernal.com.

## Infrastructure map — three real, separate machines

| Host | IP | Role |
|---|---|---|
| `docker-host` | 192.168.4.20 | Docker builds, Gitea, Grafana, Woodpecker |
| k3s control-plane | 192.168.4.63 | Runs the actual deployed pods, `kubectl` here |
| Postgres LXC | 192.168.4.210 | The `futbol` database (Proxmox container) |
| GPU workstation | 192.168.4.48 | Ollama (`llama3.2`), backs Petey |

**This matters:** builds happen on `docker-host`, deploys happen via
`kubectl` on the control-plane, and local dev/testing (`uvicorn`,
`npm run dev`, `psql`) happens on the Mac. Don't assume one machine has
what another one does — `docker-host` has no `npm`/`psql` installed;
the Mac has the full toolchain.

## Real deploy workflow (frontend, API, or CronJob image)

```bash
# On docker-host, in the repo (ops/deploy.sh handles build + push + rollout):
git pull
./ops/deploy.sh futbol-web    <sha>   # Next.js frontend
./ops/deploy.sh futbol-api    <sha>   # FastAPI backend
./ops/deploy.sh futbol-modelo <sha>   # all three CronJobs
```

Images are pushed to the Gitea registry (`gitea.josephbernal.com/joe/`)
and pulled by k3s via `imagePullPolicy: IfNotPresent`. `<sha>` is the
short digest you use for the image tag (e.g. `abc1234`); the script also
tags `:latest`. Rollouts use `kubectl set image` + `kubectl rollout
status` for Deployments and `kubectl patch cronjob` for CronJobs.

**One-time setup** (already done once per cluster — only needed again if
the secret is deleted):
```bash
kubectl create secret docker-registry gitea-registry \
  --docker-server=gitea.josephbernal.com \
  --docker-username=joe \
  --docker-password=<GITEA_TOKEN>
docker login gitea.josephbernal.com   # on docker-host
```

**Old workflow (now retired):** Previously images were `docker save`d to
`.tar`, `scp`d to the control-plane, and `k3s ctr images import`ed with
`imagePullPolicy: Never`. This required kubectl debug node workarounds
since the Mac has no SSH key on the control-plane. Don't use this path.

**If a CronJob change also edits `command`/`args`, `schedule`, or
anything else in the manifest itself, run `kubectl apply -f
k8s/cronjobs.yaml` separately.** `ops/deploy.sh futbol-modelo` only
patches the image reference — it does not touch the live CronJob
object's spec. Real mistake made 2026-08-28: added a new step to
`futbol-nightly-refresh`'s command chain, rebuilt and deployed the
image, triggered a real run to verify — and it silently ran the
*old* three-step command, because the live CronJob object still had
the old `args`. No error, no warning, just quietly wrong. Verify by
checking the actual CronJob object's spec matches the repo, not just
that the image updated cleanly.

## Schema changes

Since 2026-08-27, schema changes go through `sql/migrations/` (numbered
`.sql` files, applied via `python scripts/migrate.py` against
`FUTBOL_DSN`, tracked in a `schema_migrations` table) — not ad hoc
scripts run by hand. See `sql/migrations/README.md` and ADR-007 in
`docs/DECISIONS.md`. `sql/schema.sql` stays the from-scratch reference
and must be updated by hand alongside each new migration.

## Database backups

Nightly at 03:15 UTC via docker-host's crontab: `~/scripts/backup-futbol-db.sh`
(deployed from `ops/backup-futbol-db.sh` in this repo -- that's the
source of truth, docker-host's copy should match it) dumps the live
database and keeps the last 14 days in `~/futbol-modelo-backups/` on
docker-host, off the Postgres LXC's own disk. See `ops/README.md` for
the restore procedure and the 2026-08-27 restore drill that verified
it actually works.

## Where things actually are

- Repo (private): `https://gitea.josephbernal.com/joe/futbol-modelo`
- Repo (public mirror, clean history, no secrets): `https://github.com/jbern1022/futbol-modelo`
- Live site: `https://futbol.josephbernal.com`
- K8s manifests: `k8s/webapp.yaml`
- Full design docs: `docs/petey-spec.md` and `docs/adr/petey-decisions.md`
  (11 real ADRs — read these before changing anything about Petey's
  architecture, especially the safety design)

## Credentials

Never hardcoded, never committed. Real values live in:
- `~/.zshrc` on the Mac (`FUTBOL_DSN`, `PGPASSWORD` -- note `FUTBOL_RO_DSN`
  is NOT here, only in the k8s secret below)
- The `futbol-secrets` Kubernetes secret on the control-plane (`FUTBOL_DSN`,
  `API_FOOTBALL_KEY`, `FUTBOL_RO_DSN`, `FUTBOL_OLLAMA_URL`, `PYTHONPATH`)
- `~/.futbol_backup_dsn` on docker-host (chmod 600, not in any repo) --
  the `futbol_backup` role (read-only via PostgreSQL's builtin
  `pg_read_all_data`, see `sql/migrations/0004_create_backup_role.sql`),
  used only by `ops/backup-futbol-db.sh`. Deliberately not `futbol_ro`:
  that role is scoped to exactly the ~15 tables/views the API serves,
  not the whole schema, which a backup needs.

Two credentials were found exposed in early commit history and have
since been rotated (dead values now, harmless, but don't reintroduce
the pattern). The public GitHub repo has clean history by design — a
fresh initial commit, not the scrubbed original. Keep it that way.

## The one real lesson worth internalizing from this project's history

More than once, a fix was built, tested in isolation, and genuinely
believed to be live — but never actually got wired into the script the
real nightly pipeline runs. Found only by directly grepping the actual
file the CronJob executes. **Always verify against the real, currently
running code — not a commit message, not a past summary, not memory.**
See /lessons-learned on the live site for the full, honest version of
this.

## Current real open work

Tracked in Todoist (project: futbol-modelo) — not duplicated here on
purpose, since Todoist is the live source of truth. As of this file's
writing (2026-09-05), the real bookmaker odds comparison ticket
(ingestion, MLS/EPL/Serie A coverage, and the Track Record UI
comparison) is fully closed — see CLAIMS.md. Remaining open items are
mostly real infra decisions awaiting the user's go-ahead (registry/SHA
tags, GitOps, NetworkPolicy, Sealed Secrets) and larger scoped-but-not-
started builds (Petey v2, NBA/NFL). Grammar fixes on the Lessons
Learned page are also still untouched — nobody has pointed at a
specific sentence yet.
