"""
Bundesliga wiring (phase 2 expansion): cron chains, health expectations,
deploy script, ratings list and the deliberately NOT-yet-enabled switches.

Text-level checks only (no database, no cluster, no PyYAML): they pin that
the pieces that must change together did, and that the pieces that need a
validated result first have not been switched on by accident. Remove the
"still off" test's entries one at a time as each validation passes
(props, cards, then the live poller at launch), each with its registry entry.
xG blend, API xG fill, in-play share and red-card factors are validated.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

ROOT = Path(__file__).resolve().parent.parent
CRON = (ROOT / "k8s" / "cronjobs.yaml").read_text()
DEPLOY = (ROOT / "ops" / "deploy.sh").read_text()


def _doc(name: str) -> str:
    start = CRON.index(f"  name: {name}\n")
    end = CRON.find("\n---\n", start)
    return CRON[start:end if end != -1 else len(CRON)]


def test_bundesliga_refresh_is_its_own_cronjob_not_a_step_in_the_main_chain():
    assert "backfill --league BUNDESLIGA" not in _doc("futbol-nightly-refresh")
    own = _doc("futbol-nightly-refresh-bundesliga")
    assert "python -m ingestion.api_football backfill --league BUNDESLIGA --season 2026 --primary" in own
    assert 'schedule: "30 11 * * *"' in own  # before the 12:00 chain's rebuild_features
    assert "name: refresh-bundesliga" in own


def test_deploy_script_patches_the_new_cronjob_image():
    assert ('patch_cronjob "futbol-nightly-refresh-bundesliga" "refresh-bundesliga"' in DEPLOY)


def test_bundesliga_is_last_in_the_slate_and_odds_chains_so_it_cannot_block_others():
    slate = _doc("futbol-auto-slate")
    assert slate.rstrip().endswith("python scripts/auto_slate.py --league BUNDESLIGA --days 3") or \
        re.search(r"auto_slate\.py --league BUNDESLIGA --days 3\s*\n(?:\s*#.*\n|\s*env:|\s*-\s)", slate)
    assert slate.index("generate_nfl_slate.py") < slate.index("--league BUNDESLIGA")
    for name, days in (("futbol-odds-daily", 7), ("futbol-odds-intraday", 1)):
        doc = _doc(name)
        assert doc.index(f"--league LA_LIGA --days-ahead {days}") < doc.index(
            f"--league BUNDESLIGA --days-ahead {days}")


def test_health_check_expects_the_new_jobs_and_slated_league():
    from check_pipeline_health import EXPECTED_JOBS, SLATED_LEAGUES
    for job in ("nightly_refresh:BUNDESLIGA", "auto_slate:BUNDESLIGA", "odds:BUNDESLIGA"):
        assert job in EXPECTED_JOBS
    assert "BUNDESLIGA" in SLATED_LEAGUES


def test_every_bundesliga_cron_job_is_in_the_health_expectations():
    from check_pipeline_health import EXPECTED_JOBS
    if "backfill --league BUNDESLIGA" in CRON:
        assert "nightly_refresh:BUNDESLIGA" in EXPECTED_JOBS
    if "auto_slate.py --league BUNDESLIGA" in CRON:
        assert "auto_slate:BUNDESLIGA" in EXPECTED_JOBS
    if "odds --league BUNDESLIGA" in CRON:
        assert "odds:BUNDESLIGA" in EXPECTED_JOBS


def test_ratings_list_includes_the_league():
    from compute_team_ratings import LEAGUES
    assert "BUNDESLIGA" in LEAGUES


def test_petey_allows_the_league():
    from petey_filter import ALLOWED_LEAGUE_VALUES
    assert "BUNDESLIGA" in ALLOWED_LEAGUE_VALUES


def test_validated_switches_are_on_and_agree_with_each_other():
    """Switched on once each had its registry entry: xG blend (ADR-018),
    API xG fill with its own scale (ADR-018), empirical remaining-goal share
    and red-card factors (2026-10-15 entry)."""
    from models.xg_blend import XG_BLEND_LEAGUES
    from ingestion.api_football import API_FOOTBALL_XG_SCALES, XG_FILL_LEAGUES
    from predictions.live_winprob import EMPIRICAL_REMAINING_LEAGUES, RED_CARD_FACTORS
    for name, s in (("XG_BLEND_LEAGUES", XG_BLEND_LEAGUES), ("XG_FILL_LEAGUES", XG_FILL_LEAGUES),
                    ("EMPIRICAL_REMAINING_LEAGUES", EMPIRICAL_REMAINING_LEAGUES),
                    ("RED_CARD_FACTORS", RED_CARD_FACTORS)):
        assert "BUNDESLIGA" in s, f"{name} lost its validated Bundesliga entry"
    assert "BUNDESLIGA" in API_FOOTBALL_XG_SCALES
    down, up = RED_CARD_FACTORS["BUNDESLIGA"]
    assert down < 1 < up


def test_switches_that_need_a_validated_result_are_still_off():
    """Staged launch. Props and cards read xg_for_r5 and each needs its own
    registry entry; the live poller and the props final pass are not run for
    the Bundesliga until launch. Remove an entry here when its validation passes."""
    from generate_slate import CARDS_LEAGUES, PLAYER_PROPS_LEAGUES, PROPS_LEAGUES
    for name, s in (("PROPS_LEAGUES", PROPS_LEAGUES), ("PLAYER_PROPS_LEAGUES", PLAYER_PROPS_LEAGUES),
                    ("CARDS_LEAGUES", CARDS_LEAGUES)):
        assert "BUNDESLIGA" not in s, f"{name} was switched on before its validation"
    assert "--league BUNDESLIGA" not in _doc("futbol-props-final-pass")
    assert "--league BUNDESLIGA" not in _doc("futbol-live-winprob")
