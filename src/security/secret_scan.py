"""Scan tracked files for committed credentials (ADR-0035, R11).

``python -m src.security.secret_scan`` exits 1 and lists ``file:line`` (never
the secret itself) when a tracked file contains something shaped like a
provider key or private key. CI runs it on every push. It is a tripwire for
the common formats, not a replacement for a full scanner such as gitleaks.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
}
_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".wav", ".mp3", ".db", ".woff2"}


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "ls-files", "-z"],  # noqa: S607 - git from PATH, fixed arguments
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return [root / p for p in out.split("\0") if p]


def scan_text(text: str) -> list[tuple[int, str]]:
    """``(line number, pattern name)`` for every match."""
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS.items():
            if pattern.search(line):
                hits.append((number, name))
    return hits


def scan(files: list[Path]) -> list[str]:
    findings = []
    for path in files:
        if path.suffix.lower() in _SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings += [f"{path}:{line}: {name}" for line, name in scan_text(text)]
    return findings


def main() -> int:
    root = Path.cwd()
    findings = scan(tracked_files(root))
    for finding in findings:
        print(finding)
    print(f"secret scan: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
