"""
Gated (new-league) jobs are only expected once the league has matches in
the DB, so wiring a league's health checks ahead of its CronJobs can't
page (the 2026-10-28 Bundesliga false-alarm risk, Todoist 6hrFJFW7r8Pxvpp7).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from check_pipeline_health import EXPECTED_JOBS, GATED_LEAGUES, jobs_to_expect

BL_JOBS = {"nightly_refresh:BUNDESLIGA", "auto_slate:BUNDESLIGA", "odds:BUNDESLIGA"}


def test_gated_league_jobs_dropped_until_league_has_matches():
    jobs = jobs_to_expect(EXPECTED_JOBS, active_leagues=set())
    assert not BL_JOBS & set(jobs)
    assert "nightly_refresh:EPL" in jobs and "auto_slate:MLS" in jobs


def test_gated_league_jobs_expected_once_league_is_active():
    assert BL_JOBS <= set(jobs_to_expect(EXPECTED_JOBS, active_leagues={"BUNDESLIGA"}))


def test_ungated_leagues_and_shared_jobs_always_expected():
    jobs = set(jobs_to_expect(EXPECTED_JOBS, active_leagues=set()))
    assert jobs == set(EXPECTED_JOBS) - BL_JOBS


def test_order_is_preserved():
    jobs = jobs_to_expect(EXPECTED_JOBS, active_leagues={"BUNDESLIGA"})
    assert jobs == EXPECTED_JOBS


def test_every_gated_league_has_expected_jobs():
    for league in GATED_LEAGUES:
        assert any(j.endswith(f":{league}") for j in EXPECTED_JOBS)
