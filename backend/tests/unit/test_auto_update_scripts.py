"""Server scripts of the instant update: the watcher starts the update on a trigger."""

# ruff: noqa: S603, S607 - runs the repository's own shell scripts with bash from PATH

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="flock missing")


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "infrastructure" / "deploy-hook").mkdir(parents=True)
    shutil.copy(SCRIPTS / "auto_update_watch.sh", repo / "scripts")
    fake = repo / "scripts" / "auto_update.sh"
    fake.write_text(
        '#!/usr/bin/env bash\necho "run wait=${AUTO_UPDATE_WAIT:-}" >>"$(dirname "$0")/../calls"\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return repo


def _watch(repo: Path, tmp_path: Path, seconds: str = "3") -> None:
    env = {
        **os.environ,
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "AUTO_UPDATE_WATCH_SECONDS": seconds,
        "AUTO_UPDATE_WATCH_POLL": "0.2",
    }
    subprocess.run(
        ["bash", str(repo / "scripts" / "auto_update_watch.sh")], env=env, check=True, timeout=30
    )


def test_watcher_runs_update_once_per_trigger(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    hook = repo / "infrastructure" / "deploy-hook"
    (hook / "trigger").write_text('{"commit": "abc"}')
    _watch(repo, tmp_path)
    assert (repo / "calls").read_text() == "run wait=1\n"
    assert not (hook / "trigger").exists()
    assert (hook / "watcher").exists()


def test_watcher_without_trigger_only_reports_alive(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    _watch(repo, tmp_path, seconds="1")
    assert not (repo / "calls").exists()
    assert (repo / "infrastructure" / "deploy-hook" / "watcher").exists()


def test_only_one_watcher_at_a_time(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    state = tmp_path / "state" / "content-engine"
    state.mkdir(parents=True)
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state"),
           "AUTO_UPDATE_WATCH_SECONDS": "3", "AUTO_UPDATE_WATCH_POLL": "0.2"}  # fmt: skip
    first = subprocess.Popen(["bash", str(repo / "scripts" / "auto_update_watch.sh")], env=env)
    try:
        for _ in range(50):
            if (repo / "infrastructure" / "deploy-hook" / "watcher").exists():
                break
            time.sleep(0.1)
        (repo / "infrastructure" / "deploy-hook" / "trigger").write_text("{}")
        second = subprocess.run(
            ["bash", str(repo / "scripts" / "auto_update_watch.sh")], env=env, timeout=10
        )
        assert second.returncode == 0  # left at once, the running one handles it
    finally:
        first.wait(timeout=30)
    assert (repo / "calls").read_text() == "run wait=1\n"


def test_server_scripts_parse() -> None:
    for name in ("auto_update.sh", "auto_update_watch.sh", "install_auto_update.sh", "deploy.sh"):
        subprocess.run(["bash", "-n", str(SCRIPTS / name)], check=True)


def _install_env(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """Copy of the repository's scripts with a fake ``crontab`` that stores into a file."""
    repo = tmp_path / "repo"
    shutil.copytree(SCRIPTS, repo / "scripts")
    (repo / "infrastructure" / "deploy-hook").mkdir(parents=True)
    tab = tmp_path / "crontab.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "crontab"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'F="{tab}"\n'
        'if [[ "$1" == "-l" ]]; then [[ -f "$F" ]] || { echo "no crontab" >&2; exit 1; }; '
        'cat "$F"; else data="$(cat)"; printf "%s\\n" "$data" >"$F"; fi\n'
    )
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return repo, tab, env


def test_install_with_empty_crontab_adds_both_lines(tmp_path: Path) -> None:
    """Regression 27.11.2026: with no crontab yet the script ended silently."""
    repo, tab, env = _install_env(tmp_path)
    script = str(repo / "scripts" / "install_auto_update.sh")
    out = subprocess.run(["bash", script], env=env, check=True, capture_output=True, text=True)
    assert "Automatisches Update ist an" in out.stdout
    lines = tab.read_text().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("# content-engine auto-update")
    assert lines[1].endswith("# content-engine auto-update-watch")
    secret = (repo / "infrastructure" / "deploy-hook" / "secret").read_text()
    assert len(secret) == 64
    # again: same two lines, other entries kept, secret unchanged
    tab.write_text("0 4 * * * /bin/true # other\n" + tab.read_text())
    subprocess.run(["bash", script], env=env, check=True, capture_output=True)
    lines = tab.read_text().splitlines()
    assert lines[0] == "0 4 * * * /bin/true # other" and len(lines) == 3
    assert (repo / "infrastructure" / "deploy-hook" / "secret").read_text() == secret
    # off removes both, keeps the rest
    subprocess.run(["bash", script, "--off"], env=env, check=True, capture_output=True)
    assert tab.read_text().splitlines() == ["0 4 * * * /bin/true # other"]
