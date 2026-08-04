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

## Real deploy workflow (frontend or API)

```bash
# On docker-host, in the repo:
git pull
docker build --provenance=false -t gitea.josephbernal.com/joe/futbol-web:latest web/
docker save gitea.josephbernal.com/joe/futbol-web:latest -o futbol-web.tar
scp futbol-web.tar joe@192.168.4.63:~/

# On the control-plane:
sudo k3s ctr images import ~/futbol-web.tar
sudo kubectl delete pod -l app=futbol-web   # forces pull of the fresh image
sudo kubectl get pods -l app=futbol-web
```

Same pattern for `futbol-api` with `Dockerfile.api` and `requirements-api.txt`.
`imagePullPolicy: Never` everywhere — images are locally imported, not
pulled from a registry. **A stale `.tar` file reused without rebuilding
is a real, easy mistake — always confirm the image hash actually changed
before trusting a deploy worked.**

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
- `~/.zshrc` on the Mac (`FUTBOL_DSN`, `FUTBOL_RO_DSN`, `PGPASSWORD`)
- The `futbol-secrets` Kubernetes secret on the control-plane (`FUTBOL_DSN`,
  `API_FOOTBALL_KEY`, `FUTBOL_RO_DSN`, `FUTBOL_OLLAMA_URL`, `PYTHONPATH`)

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
writing, open items include: grammar fixes on the Lessons Learned page,
verifying whether Dixon-Coles (1X2/Total Goals) needs the same
calibration treatment corners/SOT just got, and three scoped
UI-only Phase 2 pages (team pages, league standings, "Recently Graded"
feed).
