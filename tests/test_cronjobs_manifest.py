"""
k8s/cronjobs.yaml: the nightly refresh must not let one failing step stop the
rest (Todoist 6hm4gJcHXMhfqVcf), and ops/deploy.sh must patch every CronJob
in the manifest (a missing one silently stays on a stale :latest image, which
happened twice before).
"""
import os
import re
import stat
import subprocess

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _cronjobs() -> dict:
    with open(os.path.join(ROOT, "k8s", "cronjobs.yaml")) as f:
        docs = [d for d in yaml.safe_load_all(f) if d and d.get("kind") == "CronJob"]
    return {d["metadata"]["name"]: d for d in docs}


def _script(name: str) -> str:
    c = _cronjobs()[name]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    return c["args"][0]


def _run_nightly(tmp_path, fail_on: str | None):
    """Run the manifest's shell block with `python` replaced by a recorder."""
    fake = tmp_path / "python"
    log = tmp_path / "calls.log"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> {log}\n'
        'case "$*" in *"$FAIL_ON"*) [ -n "$FAIL_ON" ] && exit 3;; esac\n'
        "exit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "FAIL_ON": fail_on or ""}
    r = subprocess.run(["/bin/sh", "-c", _script("futbol-nightly-refresh")], env=env,
                       capture_output=True, text=True, cwd=ROOT)
    return r, log.read_text().splitlines() if log.exists() else []


def test_all_steps_run_and_exit_zero_when_nothing_fails(tmp_path):
    r, calls = _run_nightly(tmp_path, None)
    assert r.returncode == 0, r.stderr
    assert len(calls) == 10
    assert calls[-1].endswith("compute_team_ratings.py")


def test_one_failing_league_does_not_stop_later_steps(tmp_path):
    r, calls = _run_nightly(tmp_path, "--league EPL")
    assert r.returncode != 0                      # the Job still reports failure
    assert "STEP FAILED" in r.stderr and "EPL" in r.stderr
    assert len(calls) == 10                       # every step still ran
    assert any("rebuild_features" in c for c in calls)
    assert any("compute_team_ratings" in c for c in calls)
    assert any("--league LA_LIGA" in c for c in calls)


def test_deploy_script_patches_every_cronjob():
    deploy = open(os.path.join(ROOT, "ops", "deploy.sh")).read()
    patched = set(re.findall(r'patch_cronjob "([^"]+)"', deploy))
    assert set(_cronjobs()) <= patched, f"not patched by deploy.sh: {set(_cronjobs()) - patched}"


def test_patched_container_names_match_manifest():
    deploy = open(os.path.join(ROOT, "ops", "deploy.sh")).read()
    pairs = dict(re.findall(r'patch_cronjob "([^"]+)"\s+"([^"]+)"', deploy))
    for name, cj in _cronjobs().items():
        container = cj["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["name"]
        assert pairs[name] == container, f"{name}: deploy.sh uses {pairs[name]!r}, manifest has {container!r}"
