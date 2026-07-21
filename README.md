# Futbol Modelo

A calibrated soccer prediction system — real predictions, locked before
kickoff, graded automatically, published honestly (misses included).

**Live site:** [futbol.josephbernal.com](https://futbol.josephbernal.com)
**How it works:** [futbol.josephbernal.com/how-it-works](https://futbol.josephbernal.com/how-it-works)
**Track record:** [futbol.josephbernal.com/track-record](https://futbol.josephbernal.com/track-record)

## What this is

A full-stack ML system covering four leagues (MLS, Premier League, Serie A,
La Liga):

- **Dixon-Coles** statistical model for match outcomes (win/draw/loss,
  total goals, both-teams-to-score)
- **LightGBM** gradient-boosted models for props markets (corners, shots
  on target, anytime goalscorer, goalkeeper saves) — each required to
  beat a naive baseline on held-out data before being allowed to ship
- An **immutable prediction ledger** — once a prediction is written, it
  cannot be edited or deleted, even by the system itself
- Fully automated daily pipeline (refresh data → generate predictions →
  grade finished matches), running unattended on a self-managed
  Kubernetes cluster

## Petey

A conversational layer on top of the real data — not a general chatbot,
a narrow tool that answers specific questions using real, pre-validated
queries. The LLM (a small local Ollama model) never writes SQL and never
sees raw database rows; it only ever phrases a pre-computed, validated
answer as a sentence. Full reasoning in
[`docs/petey-spec.md`](docs/petey-spec.md) and the architectural decision
records in [`docs/adr/petey-decisions.md`](docs/adr/petey-decisions.md).

## Architecture
Ingestion (API-Football, Understat, FBref)
│
▼
PostgreSQL  ──────────────►  FastAPI (read-only role)
│                              │
▼                              ▼
Model training              Next.js frontend
(Dixon-Coles, LightGBM)      (fixtures, slates, Track Record, Petey)
│
▼
Kubernetes CronJobs (daily refresh / predict / grade)
- `src/` — ingestion pipeline, entity resolution, feature engineering,
  models (Dixon-Coles, LightGBM props)
- `scripts/` — slate generation, grading, automation entry points
- `api/` — FastAPI backend (read-only DB role, Ollama integration for Petey)
- `web/` — Next.js frontend
- `sql/` — schema, views (calibration, season scorecard)
- `k8s/` — Kubernetes manifests
- `docs/` — design specs and architectural decision records

## A few real engineering notes

This project has a real, sometimes messy build history — including
production bugs found and fixed live: a database constraint that never
actually enforced uniqueness because of how SQL treats `NULL`, an LLM
that misread a stated confidence percentage as a literal event count,
and a Next.js client component trying to reach a Kubernetes-internal
service name that no browser could ever resolve. The `docs/` folder and
git history reflect that honestly — the interesting parts of building
something real aren't usually the parts that worked on the first try.

## Stack

Python, PostgreSQL, LightGBM, scikit-learn, FastAPI, Next.js, TypeScript,
Tailwind, Kubernetes, Ollama.
