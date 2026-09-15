"""Root pytest configuration — enables deterministic test mode globally.

Setting ``POLYGLOT_DETERMINISTIC=1`` before tests import application code makes
``src.llm.factory.get_provider`` resolve to the deterministic
:class:`~src.llm.fake.FakeProvider` for every tier. That means the whole suite
runs offline, without API keys, and produces reproducible output — no test
depends on a live model.

Per-package ``conftest.py`` files may still install more specific fakes (e.g.
schema-shaped structured responses); this only guarantees a safe default.
"""

from __future__ import annotations

import os

# Set as early as possible: this module is imported before test collection, so
# the flag is in place before any application module reads it.
os.environ.setdefault("POLYGLOT_DETERMINISTIC", "1")
