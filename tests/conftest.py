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

# Never touch a developer's real ./data (ADR-0035): every test process gets a
# throw-away data directory unless the test sets its own paths. Environment
# variables take precedence over .env, and settings are created on first
# import of src.config, which happens after this module runs.
import atexit  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

_TEST_DATA = Path(tempfile.mkdtemp(prefix="polyglot-tests-"))
for _key, _value in {
    "DATA_DIR": _TEST_DATA,
    "DB_PATH": _TEST_DATA / "polyglot.db",
    "CHROMA_PATH": _TEST_DATA / "chroma",
    "PROFILES_DIR": _TEST_DATA / "user_profiles",
}.items():
    os.environ[_key] = str(_value)
atexit.register(shutil.rmtree, _TEST_DATA, ignore_errors=True)
