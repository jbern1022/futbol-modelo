# Reviewer package: statistical and reproducibility review

Todoist `6hWgXxQj4Q9x65c7`. Written 2026-10-29. This is the **package**, not the review: no external
reviewer has been selected, contacted or has signed off. Reviewer selection and sign-off are separate
gates (owner disposition 2026-10-25). Reviewers advise; they have no editorial veto, and they cannot waive
legal obligations or release blockers.

## What a reviewer is asked to check

| Concern | Where the evidence is | How to regenerate |
|---|---|---|
| Leakage and feature availability at prediction time | `docs/RESEARCH_PROTOCOL.md` (time-ordered windows, leakage tests); ADR-012 (slate locks 3 days out); `src/predictions/snapshot.py` and table `prediction_snapshots` (cutoff, input freshness, missing features, referee known) | Snapshots exist only for predictions made after migration 0044 (2026-10-29). Earlier predictions have feature values in `predictions.context` without cutoff provenance. Nothing is back-filled. |
| Calibration | `v_calibration` (deciles); `scripts/calibration_check.py` (cluster-bootstrap shift/slope with a fail rule); `src/evaluation/evidence.py` (ADR-020 gates and intervals) | `python scripts/build_review_manifest.py` lists every league + market cohort with its gate status and per-band gap and Wilson interval |
| Holdouts and baselines | `docs/EXPERIMENT_REGISTRY.md` (append-only; each entry states hypothesis, data cutoff, evaluation method, result, limitations); baselines per league via `scripts/experiment_new_league_baseline.py` | Each registry entry names its script and arguments |
| Sample-size claims | ADR-017 (350 / 750 / 1,250 gates) and ADR-020 (calibration goal, +/-5 then +/-3) | The manifest applies the gates; `tests/test_evidence_gates.py` pins the rules |
| Model identity | `model_versions` and `model_versions_history`; the manifest records a hash of each version's params and train metrics, plus code SHA and library versions | Manifest fields `code`, `libraries`, `model_versions` |
| Data provenance and rights | `docs/DATA_LICENSING.md`; `docs/DATA_AUDIT_2026-10.md`; `docs/DATA_ALTERNATIVES_XG_2026-10.md`; ADR-015, ADR-019 | Manifest field `data_coverage` (finals, xG, referee and provider-id coverage by league and season) |
| Decisions and why | `docs/DECISIONS.md` (ADR-001 to ADR-021) | n/a |
| Governance of model replacement | ADR-021 and `src/evaluation/promotion.py` (head-to-head on matched predictions) | `tests/test_model_governance.py` |

## How to produce the manifest

```bash
export FUTBOL_DSN=...                # a read-only role is enough; the session is opened read-only
python scripts/build_review_manifest.py --out review_manifest.json
```

It writes nothing to the database. Run it from the **production image** for exact library versions: the
manifest records the interpreter it ran on, and production runs Python 3.12 while a developer machine may
differ (the 2026-10-29 run was on 3.14.3).

## Reproducing the code state

```bash
git clone https://gitea.josephbernal.com/joe/futbol-modelo      # or the public mirror, see below
git checkout <git_sha from the manifest>
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-api.txt -r requirements-dev.txt
PYTHONPATH=src pytest                 # 600+ tests; DB-backed ones skip without FUTBOL_TEST_DSN
```

A database can be rebuilt from `sql/schema.sql` then `sql/features.sql`. Since 2026-10-29 that build matches
production exactly (columns, constraints, indexes, triggers, functions: verified by diff), and
`tests/test_schema_matches_migrations.py` keeps it from drifting again. Before that fix the repository did
**not** reproduce the production schema (97 columns and 5 tables/views were missing), so any earlier claim
that "the schema is in the repo" was wrong.

The public GitHub mirror has deliberately clean history (a fresh initial commit); use the Gitea repository
for commit-level history.

## What cannot be reproduced from the repository alone

1. **The data.** Results depend on a live Postgres database filled from API-Football, Understat and
   FBref-derived loads. A reviewer cannot regenerate the training or evaluation tables without a data
   export, and whether the data may be passed to a third party is itself restricted: Understat (robots.txt
   disallows all, no terms), FBref/Sports Reference (automated access prohibited without written
   permission) and API-Football (whether derived predictions may be published is unread) are unresolved in
   `docs/DATA_LICENSING.md`. **A data-sharing plan for reviewers needs the owner's decision first.**
2. **The live prediction ledger as it was.** It is append-only and exportable, but the ledger cohorts pool
   model versions, so they describe status rather than the performance of one version.
3. **Pre-2026-10-29 provenance.** See the leakage row above.

## Known limitations (also printed in the manifest)

- Ledger cohorts pool model versions.
- 2026-27 xG for EPL, SERIE_A and LA_LIGA is API-Football rescaled (x1.108), BUNDESLIGA x1.095; history is Understat.
- Understat historical rights and FBref terms are unresolved (`6hmV7JJxQpG2Wqhf`, `6hmVCJQVqgwHfP67`).
- CARDS uses a league-average referee fallback; the real referee is rarely known at the 3-day lock.
- MLS props scored with a model that never trained on MLS (no xG): MLS SOT is paused and MLS CORNERS is
  under review (`docs/MLS_CORNERS_DECISION.md`).
- The projected-failure rule is not operational and no estimator is selected
  (`docs/PROJECTED_FAILURE_ESTIMATOR_OPTIONS.md`).
- The 350 / 750 / 1,250 gates are not yet shown on the Track Record page.
- On the 2026-10-29 ledger only MLS CORNERS (1,334 graded) and MLS SOT (1,184) pass the 750-prediction gate;
  both are in the interim (+/-5 point) regime. Every other cohort is Insufficient Evidence.

## Still to do before a review can start (owner decisions)

1. Choose a reviewer or review route and the expertise required (statistics; sports modelling; data licensing).
2. Decide what data, if any, may be shared, and in what form (aggregates only, or row-level).
3. Fix the release checkpoint the review is attached to.
4. Record the actual reviewer, materials/version reviewed, findings and dispositions in the shared review
   register (Notion, accepted 2026-10-13); this document does not do that.
