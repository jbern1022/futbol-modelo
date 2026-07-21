# futbol-modelo — Bernal Labs

Calibrated soccer prediction system. Premier League + Serie A at launch,
international module (World Cup) layered on later. Every prediction is
logged immutably before kickoff and graded after — the season-end
scorecard is the product.

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │  k3s (Pi cluster)                        │
  FBref ──scrape──► │  CronJob: ingest-nightly (02:00)         │
  Understat ──────► │  CronJob: ingest-matchday (hourly, Sa/Su)│
  football-data ──► │  CronJob: grade-nightly (04:00)          │
                    │  CronJob: predict-prematch (T-6h)        │
                    │  Deployment: portal-api (FastAPI)        │
                    └──────────────┬──────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Postgres (Proxmox / Omen)   │
                    │  schema: futbol              │
                    │  · dims, facts, shots        │
                    │  · predictions (immutable)   │
                    │  · prediction_grades         │
                    │  · model_registry            │
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
   ┌──────────▼─────────┐  ┌──────▼───────┐  ┌──────────▼─────────┐
   │ Training (WoL 5070)│  │ Grafana      │  │ Portal frontend    │
   │ · Dixon-Coles      │  │ · calibration│  │ · match slates     │
   │ · LightGBM props   │  │ · pipeline   │  │ · track record     │
   │ · (v3: neural tier)│  │   health     │  │ · Ollama previews  │
   └────────────────────┘  └──────────────┘  └────────────────────┘
```

## The two models

**High-level (match) model — `src/models/dixon_coles.py`**
Time-decayed Dixon-Coles Poisson, fit per league. One scoreline
distribution per fixture → 1X2, totals, BTTS, clean sheets, exact
scores. `knockout_extension()` handles ET/pens for cup/World Cup play.

**Secondary market model — `src/models/props.py`**
One LightGBM (Poisson objective) per market: team corners, team shots,
shots on target, player shots, GK saves. Rolling as-of features with
opponent mirrors; league as a categorical so EPL + Serie A train
jointly. Isotonic calibration fit on out-of-fold predictions only —
this is what makes stated probabilities honest.

## The ledger discipline (non-negotiable)

- `predictions` is INSERT-only; UPDATE/DELETE raise via trigger.
- A trigger rejects any prediction locked at/after kickoff.
- Grades live in `prediction_grades`, append-only, separate table.
- `v_season_scorecard` and `v_calibration` views feed Grafana and the
  season report — hit rate, Brier, log loss, calibration by decile,
  segmented by market and league.
- Headline metric: does the 60–75% confidence band realize 60–75%?

## Build order

1. **Now → Italy (Aug 6):** stand up schema, ingest 3–5 seasons EPL +
   Serie A from FBref/Understat, fit Dixon-Coles, backtest.
2. **Late Aug (season start):** predict-prematch CronJob live, ledger
   accumulating, grade-nightly running. v1 shipped.
3. **Autumn:** props models per market, calibration dashboards, portal.
4. **Winter+:** neural tier on the 5070 (player embeddings, sequence
   models), custom xG from `shots`, Ollama match previews.

## Repo layout

```
sql/schema.sql                 # full schema incl. ledger triggers + views
src/models/dixon_coles.py      # match model (working implementation)
src/models/props.py            # props models + calibration layer
src/predictions/generator.py   # slate builder + ledger writer
src/grading/grader.py          # nightly grading + season report
src/ingestion/                 # scrapers (next step)
k8s/                           # CronJob manifests (next step)
```

## Deps

`pip install pandas numpy scipy scikit-learn lightgbm psycopg2-binary`
