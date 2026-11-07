"""Regenerate requirements.lock from the current (tested) environment.

Pins exactly the dependency closure of polyglot-swarm[all] (runtime, voice,
dev), so tools installed alongside (pip-audit, ...) stay out. Run after the
full test suite passes:  make lock
"""

import importlib.metadata as md
import re
import tomllib
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

py = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
roots = list(py["project"]["dependencies"])
extras = py["project"]["optional-dependencies"]
for name in ("voice", "dev"):
    roots += extras.get(name, [])

installed = {canonicalize_name(d.metadata["Name"]): d for d in md.distributions()}
seen: dict[str, str] = {}
missing: list[str] = []


def visit(req_str: str, extra: str | None = None) -> None:
    req = Requirement(req_str)
    env = default_environment()
    env["extra"] = extra or ""
    if req.marker and not req.marker.evaluate(env):
        return
    key = canonicalize_name(req.name)
    dist = installed.get(key)
    if dist is None:
        missing.append(req.name)
        return
    wanted_extras = set(req.extras)
    first = key not in seen
    seen[key] = f"{dist.metadata['Name']}=={dist.version}"
    for sub in dist.requires or []:
        r = Requirement(sub)
        # Base requirements once; extra-gated ones for the extras requested.
        if r.marker and "extra" in str(r.marker):
            for e in wanted_extras:
                envx = default_environment()
                envx["extra"] = e
                if r.marker.evaluate(envx):
                    visit(sub, e)
        elif first:
            visit(sub)


for r in roots:
    visit(r)

header = """# Polyglot Swarm — dependency lockfile (fully pinned transitive closure).
#
# The closure of polyglot-swarm[all] (runtime + voice + dev), pinned to the
# versions the full test suite passed with. Regenerate with `make lock`.
# Install reproducibly:  pip install -c requirements.lock -e ".[all]"
# The production image uses it as a constraints file (Dockerfile).
"""
lines = sorted(seen.values(), key=str.lower)
# Local build tags (torch "+cpu") are not on PyPI; pin the public version.
lines = [re.sub(r"\+[A-Za-z0-9.]+$", "", line) for line in lines]
Path("requirements.lock").write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
print(len(lines), "pins; missing (not installed, skipped):", sorted(set(missing)))
