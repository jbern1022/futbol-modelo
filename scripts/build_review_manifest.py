"""
Reviewer manifest (Todoist 6hWgXxQj4Q9x65c7): a machine-readable statement of exactly what was
evaluated, for an external statistical / reproducibility review. READ-ONLY: the session is opened
read-only and nothing is written. Output is JSON on stdout (or --out).

Covers the items in the owner's 2026-10-25 disposition: model/version, source provenance, point-in-time
features, calibration with the ADR-020 gates and intervals, known limitations. Regeneration steps for the
published results are in docs/REVIEW_PACKAGE.md.

    python scripts/build_review_manifest.py > review_manifest.json

Ledger cohorts are league + market and POOL model versions (v_graded_predictions carries no version), so
they are a status snapshot, not an evaluation of any one version; each cohort says so.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from importlib import metadata

import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
from evaluation.evidence import evaluate_cohort  # noqa: E402

KNOWN_LIMITATIONS = [
    "Ledger cohorts pool model versions; they describe status, not any single version.",
    "Predictions made before the point-in-time snapshot table (migration 0044, 2026-10-29) have no snapshot: "
    "their feature values are only in predictions.context, without cutoff provenance. Nothing is back-filled.",
    "2026-27 xG for EPL, SERIE_A, LA_LIGA is API-Football rescaled (x1.108), BUNDESLIGA x1.095; "
    "history is Understat.",
    "Understat historical use rights are unresolved (DATA_LICENSING.md; Todoist 6hmV7JJxQpG2Wqhf); "
    "FBref-sourced rows (original World Cup rows) have unresolved terms (6hmVCJQVqgwHfP67).",
    "CARDS uses a league-average referee fallback: the real referee is rarely known at the 3-day slate lock.",
    "MLS props scored a model that never trained on MLS (no xG); MLS SOT is paused, MLS CORNERS is under review.",
    "The projected-failure rule is not operational; no estimator is selected "
    "(docs/PROJECTED_FAILURE_ESTIMATOR_OPTIONS.md).",
    "The 350 / 750 / 1,250 gates are applied here descriptively; the Track Record page does not show them yet.",
]


def canonical_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def library_versions() -> dict:
    out = {"python": platform.python_version()}
    for label, dist in (("numpy", "numpy"), ("pandas", "pandas"), ("scipy", "scipy"),
                        ("scikit-learn", "scikit-learn"), ("lightgbm", "lightgbm"), ("psycopg2", "psycopg2-binary")):
        try:
            out[label] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            out[label] = "not installed"
    return out


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _plain(v):
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def cohort_summary(league: str, market: str, probs, hits) -> dict:
    r = evaluate_cohort(np.asarray(probs, dtype=float), np.asarray(hits, dtype=int))
    return {
        "league": league, "market": market, "n_graded": r["n_total"], "pools_model_versions": True,
        "status": r["status"], "tolerance": r["tolerance"], "tolerance_regime": r["tolerance_regime"],
        "bands": [{k: _plain(v) for k, v in b.items()} for b in r["bands"]],
    }


def build_manifest(conn) -> dict:
    conn.set_session(readonly=True)
    cur = conn.cursor()
    cur.execute("SET search_path TO futbol")

    cur.execute("SELECT to_regclass('futbol.schema_migrations')")
    if cur.fetchone()[0] is None:  # a database built straight from schema.sql has not run migrate.py
        latest, n_mig = None, 0
    else:
        cur.execute("SELECT max(version), count(*) FROM schema_migrations")
        latest, n_mig = cur.fetchone()

    cur.execute("""SELECT model_version_id, model_name, version_tag, trained_at, training_window, params, train_metrics
                   FROM model_versions ORDER BY model_version_id""")
    model_versions = [{"model_version_id": i, "model_name": n, "version_tag": t, "trained_at": at,
                       "training_window": w, "params_sha256": canonical_hash(p),
                       "train_metrics_sha256": canonical_hash(m)}
                      for i, n, t, at, w, p, m in cur.fetchall()]

    cur.execute("SELECT league, market, probability, (outcome = 'hit')::int FROM v_graded_predictions "
                "WHERE outcome IN ('hit', 'miss')")
    groups: dict = defaultdict(lambda: ([], []))
    for league, market, p, y in cur.fetchall():
        groups[(league, market)][0].append(float(p))
        groups[(league, market)][1].append(y)
    cohorts = [cohort_summary(lg, mk, p, y) for (lg, mk), (p, y) in sorted(groups.items())]

    cur.execute("""
        SELECT l.code, s.label, count(*) FILTER (WHERE m.status = 'final'),
               count(*) FILTER (WHERE m.status = 'final' AND EXISTS (
                   SELECT 1 FROM team_match_stats t WHERE t.match_id = m.match_id AND t.xg IS NOT NULL)),
               count(*) FILTER (WHERE m.status = 'final' AND m.referee IS NOT NULL),
               count(*) FILTER (WHERE m.status = 'final' AND m.api_football_fixture_id IS NOT NULL)
        FROM matches m JOIN seasons s USING (season_id) JOIN leagues l USING (league_id)
        WHERE l.sport = 'soccer' GROUP BY 1, 2 ORDER BY 1, 2""")
    coverage = [{"league": a, "season": b, "finals": c, "with_xg": d, "with_referee": e, "with_api_fixture_id": f}
                for a, b, c, d, e, f in cur.fetchall()]

    cur.execute("SELECT to_regclass('futbol.prediction_snapshots')")
    if cur.fetchone()[0] is None:
        snapshots: dict = {"table_present": False}
    else:
        cur.execute("SELECT count(*), min(cutoff_at), max(cutoff_at) FROM prediction_snapshots")
        n, lo, hi = cur.fetchone()
        snapshots = {"table_present": True, "rows": n, "first_cutoff": lo, "last_cutoff": hi}

    dirty = bool(_git("status", "--porcelain"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code": {"git_sha": _git("rev-parse", "HEAD"), "branch": _git("branch", "--show-current"), "dirty": dirty},
        "libraries": library_versions(),
        "database": {"latest_migration": latest, "migrations_applied": n_mig, "read_only_session": True},
        "model_versions": model_versions,
        "ledger_cohorts": cohorts,
        "data_coverage": coverage,
        "snapshots": snapshots,
        "known_limitations": KNOWN_LIMITATIONS,
    }


def main() -> None:
    import psycopg2
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="write JSON here instead of stdout")
    a = ap.parse_args()
    dsn = os.environ.get("FUTBOL_DSN")
    if not dsn:
        sys.exit("FUTBOL_DSN not set")
    conn = psycopg2.connect(dsn)
    try:
        text = json.dumps(build_manifest(conn), indent=2, default=str)
    finally:
        conn.rollback()
        conn.close()
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text + "\n")
    else:
        print(text)


if __name__ == "__main__":
    main()
