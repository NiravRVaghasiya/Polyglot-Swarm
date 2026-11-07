"""Secret scanning and the dependency-vulnerability gate (R11)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from src.security import dependency_audit, secret_scan

ROOT = Path(__file__).parents[2]


class TestSecretScan:
    def test_detects_common_key_formats_without_printing_them(self, tmp_path):
        fake = "sk-ant-" + "a" * 30
        leak = tmp_path / "config.py"
        leak.write_text(f"KEY = '{fake}'\nOK = 1\n", encoding="utf-8")
        findings = secret_scan.scan([leak])
        assert findings == [f"{leak}:1: anthropic_key"]
        assert fake not in findings[0]

    def test_ignores_placeholders(self):
        assert secret_scan.scan_text("ANTHROPIC_API_KEY=<secret>\nMETRICS_TOKEN=\n") == []

    def test_the_repository_is_clean(self):
        assert secret_scan.scan(secret_scan.tracked_files(ROOT)) == []


def _report(name: str, version: str, ids: list[str]) -> dict:
    return {"dependencies": [{"name": name, "version": version,
                              "vulns": [{"id": i} for i in ids]}]}  # fmt: skip


class TestDependencyGate:
    accepted = [{"package": "pillow", "version": "12.3.0", "review_by": "2027-01-31"}]

    def test_accepted_version_passes(self):
        report = _report("pillow", "12.3.0", ["PYSEC-1"])
        assert dependency_audit.evaluate(report, self.accepted, date(2026, 11, 7)) == []

    def test_unaccepted_or_changed_version_fails(self):
        assert dependency_audit.evaluate(_report("pillow", "12.4.0", ["X"]), self.accepted)
        assert dependency_audit.evaluate(_report("urllib3", "2.7.0", ["Y"]), self.accepted)

    def test_expired_acceptance_fails(self):
        problems = dependency_audit.evaluate(
            _report("pillow", "12.3.0", ["X"]), self.accepted, date(2027, 2, 1)
        )
        assert problems and "expired" in problems[0]

    def test_allowlist_entries_are_documented_and_match_the_lockfile(self):
        allow = yaml.safe_load((ROOT / dependency_audit.ALLOWLIST).read_text("utf-8"))
        lock = (ROOT / "requirements.lock").read_text("utf-8").lower()
        for entry in allow["accepted"]:
            assert entry["reason"] and entry["mitigation"] and entry["review_by"]
            assert f"{entry['package'].lower()}=={entry['version']}" in lock
