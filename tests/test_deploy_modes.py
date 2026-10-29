"""
ops/deploy.sh modes (Todoist 6hrFHQFwfr7HQrg7): `build` (docker only), `rollout` (kubectl only),
`all` (default, today's behaviour). Runs the REAL script with stub docker/kubectl on PATH that
log every call, so no registry or cluster is touched.
"""
import os
import stat
import subprocess
import textwrap

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEPLOY = os.path.join(ROOT, "ops", "deploy.sh")


@pytest.fixture
def stubs(tmp_path):
    log = tmp_path / "calls.log"
    for name in ("docker", "kubectl"):
        p = tmp_path / name
        p.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env bash
            echo "{name} $*" >> "{log}"
            exit 0
        """))
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return tmp_path, log


def run(stubs, *args):
    d, log = stubs
    env = {**os.environ, "PATH": f"{d}:{os.environ['PATH']}"}
    r = subprocess.run(["bash", DEPLOY, *args], capture_output=True, text=True, env=env)
    calls = log.read_text().splitlines() if log.exists() else []
    return r, calls


def kinds(calls):
    return {c.split()[0] for c in calls}


def test_default_mode_builds_pushes_and_rolls_out(stubs):
    r, calls = run(stubs, "futbol-api", "abc1234")
    assert r.returncode == 0, r.stderr
    assert any(c.startswith("docker build") for c in calls) and any(c.startswith("docker push") for c in calls)
    assert any("set image deployment/futbol-api" in c for c in calls)


def test_build_mode_never_calls_kubectl(stubs):
    r, calls = run(stubs, "futbol-api", "abc1234", "build")
    assert r.returncode == 0, r.stderr
    assert kinds(calls) == {"docker"} and any(c.startswith("docker push") for c in calls)


def test_rollout_mode_never_calls_docker(stubs):
    r, calls = run(stubs, "futbol-api", "abc1234", "rollout")
    assert r.returncode == 0, r.stderr
    assert kinds(calls) == {"kubectl"}
    assert any("set image deployment/futbol-api" in c and ":abc1234" in c for c in calls)


def test_modelo_rollout_patches_every_cronjob_without_docker(stubs):
    r, calls = run(stubs, "futbol-modelo", "abc1234", "rollout")
    assert r.returncode == 0, r.stderr
    assert "docker" not in kinds(calls)
    assert sum(1 for c in calls if c.startswith("kubectl patch cronjob")) >= 9


def test_modelo_build_touches_no_cronjob(stubs):
    r, calls = run(stubs, "futbol-modelo", "abc1234", "build")
    assert r.returncode == 0, r.stderr
    assert kinds(calls) == {"docker"}


def test_unknown_mode_is_rejected_before_anything_runs(stubs):
    r, calls = run(stubs, "futbol-api", "abc1234", "push")
    assert r.returncode != 0 and "mode" in (r.stdout + r.stderr).lower() and calls == []


def test_missing_args_still_print_usage(stubs):
    r, calls = run(stubs)
    assert r.returncode != 0 and "Usage" in r.stdout and calls == []
