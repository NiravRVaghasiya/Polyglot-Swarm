"""Off-host encrypted backups (ADR-0037, RR7).

The copy job is a shell script run in the restic image; these tests drive it
with a fake ``restic`` that records its calls, so they need only ``sh``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.observability import metrics
from src.ops import backup

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "ops" / "backup" / "offsite-backup.sh"
_SAMPLE = re.compile(r"^polyglot_offsite_backup_last_success_timestamp_seconds [0-9.e+]+$", re.M)

_FAKE_RESTIC = """#!/bin/sh
echo "$*" >> "$FAKE_RESTIC_LOG"
case "$1" in
  cat) [ -z "${FAKE_RESTIC_NO_REPO:-}" ] ;;
  "$FAKE_RESTIC_FAIL") exit 1 ;;
  *) exit 0 ;;
esac
"""


class TestStatusAndMetric:
    def test_no_marker_means_no_sample(self, temp_storage):
        assert backup.last_offsite_backup_time() is None
        assert not _SAMPLE.search(metrics.render())

    def test_marker_time_is_exported(self, temp_storage):
        (temp_storage / backup.OFFSITE_STATUS).touch()
        assert backup.last_offsite_backup_time() is not None
        assert _SAMPLE.search(metrics.render())

    def test_marker_is_not_mistaken_for_a_backup_set(self, temp_storage):
        (temp_storage / "backups").mkdir()
        (temp_storage / "backups" / backup.OFFSITE_STATUS).touch()
        assert backup.list_backup_sets() == []


def _posix(path: Path) -> str:
    return path.as_posix()


@pytest.fixture
def run_script(tmp_path):
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("needs a POSIX sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "restic"
    fake.write_bytes(_FAKE_RESTIC.encode())
    fake.chmod(0o755)
    data = tmp_path / "data"
    (data / "backups").mkdir(parents=True)
    log = tmp_path / "restic.log"

    def run(*args: str, **env: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        full_env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "DATA_DIR": _posix(data),
            "RESTIC_REPOSITORY": "rest:http://backup.example.org/polyglot",
            "RESTIC_PASSWORD": "x" * 20,
            "FAKE_RESTIC_LOG": _posix(log),
            "FAKE_RESTIC_FAIL": "none",
            **env,
        }
        proc = subprocess.run(  # noqa: S603 - fixed script under test
            [sh, _posix(SCRIPT), *args], env=full_env, capture_output=True, text=True
        )
        calls = log.read_text().splitlines() if log.exists() else []
        return proc, calls

    run.data = data  # type: ignore[attr-defined]
    return run


class TestCopyJob:
    def test_a_copy_backs_up_prunes_checks_then_records_success(self, run_script):
        proc, calls = run_script("once")
        assert proc.returncode == 0, proc.stderr
        assert [c.split()[0] for c in calls] == ["cat", "backup", "forget", "check"]
        assert calls[1].endswith("/backups")
        assert "--prune" in calls[2]
        assert (run_script.data / backup.OFFSITE_STATUS).exists()

    def test_a_new_repository_is_initialised(self, run_script):
        proc, calls = run_script("once", FAKE_RESTIC_NO_REPO="1")
        assert proc.returncode == 0, proc.stderr
        assert [c.split()[0] for c in calls][:3] == ["cat", "init", "backup"]

    @pytest.mark.parametrize("failing", ["backup", "forget", "check"])
    def test_any_failure_records_no_success(self, run_script, failing):
        proc, _ = run_script("once", FAKE_RESTIC_FAIL=failing)
        assert proc.returncode != 0
        assert not (run_script.data / backup.OFFSITE_STATUS).exists()

    def test_missing_configuration_is_refused(self, run_script):
        proc, calls = run_script("once", RESTIC_REPOSITORY="")
        assert proc.returncode != 0 and "RESTIC_REPOSITORY" in proc.stderr
        assert calls == []

    def test_other_arguments_pass_through_to_restic(self, run_script):
        proc, calls = run_script("snapshots", "--latest", "1")
        assert proc.returncode == 0
        assert calls == ["snapshots --latest 1"]
