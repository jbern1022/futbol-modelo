# futbol-modelo

![coverage](coverage.svg)

Calibrated soccer prediction system, live at
[futbol.josephbernal.com](https://futbol.josephbernal.com). Covers MLS
(primary league, full player props), the Premier League, Serie A, and La
Liga, plus a World Cup knockout-stage module. Every prediction is locked
into an append-only ledger before kickoff and graded automatically after
the match — hits and misses alike, published either way. The season-end
calibration curve is the product: does a stated 60–75% confidence band
actually realize 60–75%?

The site also runs **Petey**, an Ollama-backed Q&A feature that answers
questions about the data without ever writing its own SQL or seeing raw
rows — see [docs/petey-spec.md](docs/petey-spec.md) and
[docs/adr/petey-decisions.md](docs/adr/petey-decisions.md) (11 ADRs) for
the full safety design.

## Infrastructure

Runs on a self-managed Kubernetes (k3s) homelab cluster — no cloud
hosting.

| Host | Role |
|---|---|
| docker-host | Docker image builds, Gitea, Grafana, Woodpecker |
| k3s control-plane | Runs every deployed pod and CronJob |
| Postgres LXC | The `futbol` database (Proxmox container) |
| GPU workstation | Ollama, backs Petey |

Deploys are manual (no CI/CD, no image registry pull) — build on
docker-host, `docker save` to a tar, transfer to the control-plane,
`k3s ctr images import`, then delete the pod to force a fresh pull.
`imagePullPolicy: Never` everywhere. See `k8s/webapp.yaml` and
`k8s/cronjobs.yaml` for the exact deployment shape.

```
                    ┌───────────────────────────────────────────────┐
                    │  k3s (self-managed homelab cluster)            │
  FBref ───scrape──►│  CronJob: futbol-nightly-refresh (ingest)      │
  Understat ───────►│  CronJob: futbol-auto-slate (generate slates)  │
  API-Football ────►│  CronJob: futbol-auto-grade (grade + void)     │
                    │  Deployment: futbol-api (FastAPI, read-only)   │
                    │  Deployment: futbol-web (Next.js)              │
                    └──────────────────┬──────────────────────────┬─┘
                                       │                            │
                    ┌──────────────────▼─────────┐        ┌────────▼────────┐
                    │  Postgres (futbol schema)   │        │  Ollama (Petey) │
                    │  · matches, teams, seasons  │        └─────────────────┘
                    │  · predictions (immutable)  │
                    │  · prediction_grades        │
                    │  · pipeline_runs            │
                    └──────────────────────────────┘
```

## The two model families

**Match model — `src/models/dixon_coles.py`**
Time-decayed Dixon-Coles Poisson, fit per league. One scoreline
distribution per fixture drives 1X2, total goals, and BTTS.
`knockout_extension()` handles extra time/penalties for World Cup
knockout play.

**Props models — `src/models/props.py`, `scripts/generate_slate.py`**
LightGBM (Poisson objective) per market: team corners, shots on
target, player goals, goalkeeper saves. Rolling as-of features
(`team_match_features`) with opponent mirrors. Isotonic calibration
fit on out-of-fold predictions only — this is what makes stated
probabilities honest rather than raw model output.

Markets live today: `1X2`, `BTTS`, `TOTAL_GOALS`, `CORNERS`, `SOT`,
`PLAYER_GOALS`, `PLAYER_SAVES` (player markets are MLS-only for now —
the only league with `player_match_stats` populated).

## The ledger discipline (non-negotiable)

- `predictions` is INSERT-only; a trigger rejects UPDATE/DELETE.
- A trigger rejects any prediction locked at or after kickoff.
- Grades live in `prediction_grades`, append-only, separate table —
  correcting a bad prediction means inserting a `void` grade, never
  editing the original row.
- `v_season_scorecard` and `v_calibration` (see `sql/schema.sql`) feed
  the Track Record page — hit rate, calibration by decile, segmented
  by market and league.

See [CLAIMS.md](CLAIMS.md) for where every claim on this page and the
live site actually gets checked — tested, live-verified, or (honestly)
neither yet.

## Pipeline health

`src/ops/pipeline_run.py` tracks every real cron run (start, status,
rows written, failure traceback) in `futbol.pipeline_runs`, exposed via
`GET /v1/pipeline-status` and shown on the site's footer as "Predictions
last generated Xh ago" — the freshness signal that's supposed to make
a silently-stalled pipeline visible instead of quietly stale.

## Repo layout

```
sql/schema.sql                 # full schema incl. ledger triggers + views
sql/migrations/                # numbered migrations, applied via scripts/migrate.py
sql/*.sql                      # pre-2026-08-27 one-off scripts, applied by hand (history)
src/models/dixon_coles.py      # match model
src/models/props.py            # props model helpers
src/predictions/generator.py   # slate builder + ledger writer
src/grading/grader.py          # grading logic
src/ingestion/                 # FBref / Understat / API-Football loaders
src/ops/pipeline_run.py        # cron run tracking
src/ops/ntfy.py                # shared ntfy alerting helper
scripts/                       # generate_slate, auto_slate, auto_grade,
                                # training scripts, data quality checks
api/main.py                    # FastAPI backend (read-only DB role)
web/                           # Next.js frontend
k8s/                           # real, live-matching Deployment/CronJob manifests
tests/                         # pytest, several run against the live DB
                                # in a rolled-back transaction (see FUTBOL_DSN)
docs/petey-spec.md             # Petey design spec
docs/adr/petey-decisions.md    # Petey's 11 ADRs
```

## Repos

- Private (real history): `gitea.josephbernal.com/joe/futbol-modelo`
- Public mirror (clean history, no secrets): `github.com/jbern1022/futbol-modelo`

## Local dev

```bash
pip install -r requirements.txt          # or requirements-api.txt for just the API
export FUTBOL_DSN=...                    # see CLAUDE.md for where real values live
uvicorn api.main:app --reload --port 8000
cd web && npm run dev
```
