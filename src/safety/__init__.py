"""Safety and correctness (Phase 20).

The plan calls for policies against: hallucinated corrections, fabricated
cultural claims, sensitive content, inappropriate personas, medical/legal
role-play, prompt injection through external content, malicious scenario
definitions, unsafe user-generated content, and privacy/deletion. It states two
hard rules: **external text must always be treated as untrusted data**, and
**retrieved content must never become system instructions**.

Before this package, exactly one place in the codebase honored that rule:
:mod:`src.agents.ingestion` wraps fetched external text in explicit
``<CONTENT>`` delimiters with an instruction to treat it as data, never as
commands. Scenario definitions (persona/objectives/constraints — free text
that ships in version-controlled YAML today, but architecturally no different
from a future community-contributed or user-uploaded scenario) had no
equivalent defense, and cultural notes/grammar corrections had no shared
"is this claim trustworthy enough to surface" gate beyond grammar's own
verifier.

Modules:
- :mod:`injection` — heuristic prompt-injection detection and the delimiter
  pattern (:func:`wrap_untrusted`) used to harden prompt construction wherever
  scenario- or agent-derived text lands in a system-role prompt.
- :mod:`roleplay` — sensitive-role-play guardrails (medical/legal personas get
  an appended disclaimer instruction) and scenario content validation at load
  time, so a malicious scenario definition is rejected before it ever reaches
  an agent prompt.
"""

from src.safety.injection import (
    UntrustedContentError,
    scan_for_injection,
    wrap_untrusted,
)
from src.safety.roleplay import (
    SENSITIVE_ROLE_KEYWORDS,
    disclaimer_for_role,
    is_sensitive_role,
    validate_scenario_content,
)

__all__ = [
    "SENSITIVE_ROLE_KEYWORDS",
    "UntrustedContentError",
    "disclaimer_for_role",
    "is_sensitive_role",
    "scan_for_injection",
    "validate_scenario_content",
    "wrap_untrusted",
]
