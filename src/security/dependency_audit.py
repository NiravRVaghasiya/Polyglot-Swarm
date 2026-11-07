"""Dependency vulnerability gate for CI (ADR-0035, R11).

Runs ``pip-audit`` on ``requirements.lock`` and fails on any vulnerable
package that is not accepted in ``ops/security/accepted-vulnerabilities.yml``.
An acceptance matches one exact version and has a review-by date; an expired
acceptance fails the gate too, so exceptions cannot quietly become
permanent.

Usage (CI)::

    python -m pip install pip-audit
    python -m src.security.dependency_audit
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ALLOWLIST = Path("ops/security/accepted-vulnerabilities.yml")


def run_pip_audit(lockfile: str = "requirements.lock") -> dict[str, Any]:
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "pip_audit", "-r", lockfile, "--no-deps", "--disable-pip",
         "--progress-spinner", "off", "-f", "json"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if not proc.stdout.strip():
        raise RuntimeError(f"pip-audit produced no report: {proc.stderr.strip()[:500]}")
    report: dict[str, Any] = json.loads(proc.stdout)
    return report


def evaluate(
    report: dict[str, Any], accepted: list[dict[str, Any]], today: date | None = None
) -> list[str]:
    """Problems: unaccepted vulnerable packages and expired acceptances."""
    today = today or date.today()
    by_key = {(a["package"].lower(), str(a["version"])): a for a in accepted}
    problems: list[str] = []
    for dep in report.get("dependencies", []):
        vulns = dep.get("vulns") or []
        if not vulns:
            continue
        entry = by_key.get((dep["name"].lower(), dep["version"]))
        ids = ", ".join(sorted({v["id"] for v in vulns}))
        if entry is None:
            problems.append(f"{dep['name']} {dep['version']}: {len(vulns)} unaccepted ({ids})")
        elif date.fromisoformat(str(entry["review_by"])) < today:
            problems.append(
                f"{dep['name']} {dep['version']}: acceptance expired {entry['review_by']}"
            )
    return problems


def main() -> int:
    accepted = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8"))["accepted"]
    report = run_pip_audit()
    problems = evaluate(report, accepted)
    vulnerable = [d for d in report.get("dependencies", []) if d.get("vulns")]
    print(f"dependency audit: {len(vulnerable)} vulnerable package(s), {len(problems)} problem(s)")
    for problem in problems:
        print(f"  - {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
