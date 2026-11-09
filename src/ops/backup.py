"""Verified backup sets, restore and retention (ADR-0035, R4).

A **backup set** is one directory under ``<data_dir>/backups/``:

```
polyglot-20261107T120000Z[-label]/
    polyglot.db          SQLite online backup (consistent while the app writes)
    media/               retained audio (consented, short-lived)
    user_profiles/       profile files
    manifest.json        files, sizes, SHA-256, schema version, row counts
```

ChromaDB (``chroma/``) is **not** included: it holds derived, re-buildable
embeddings of static content, not learner data.

- :func:`create_backup_set` writes the set and verifies it before returning
  (``PRAGMA integrity_check`` plus checksums); a set that fails verification
  is deleted and the error raised, so a listed set is always restorable.
- :func:`verify_backup_set` re-checks a set at any time.
- :func:`restore_backup_set` restores a set over the live data. Run it with
  the API stopped. It first takes a safety backup of the current data, and
  restores the database through SQLite's backup API (never a file copy over
  an open WAL database).
- :func:`prune_backups` keeps the newest ``settings.backup_retention_count``.

Backups are **not encrypted** by this module. The ``offsite`` service of
``docker-compose.prod.yml`` (``ops/backup/offsite-backup.sh``, ADR-0037)
copies the sets to an off-host restic repository, encrypted client-side,
and touches :data:`OFFSITE_STATUS` after each verified copy.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config import settings

PREFIX = "polyglot-"
MANIFEST = "manifest.json"
DB_NAME = "polyglot.db"
_TREES = ("media", "user_profiles")
_COUNTED_TABLES = ("users", "evidence", "vocabulary", "sessions", "media_submissions")
#: Touched by the off-host copy job after each successful, checked copy.
OFFSITE_STATUS = ".offsite-last-success"


class BackupError(RuntimeError):
    """A backup could not be created, verified or restored."""


def backup_root() -> Path:
    path = Path(settings.data_dir) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_source(name: str) -> Path:
    if name == "user_profiles":
        return Path(settings.profiles_dir)
    return Path(settings.data_dir) / name


def _db_facts(db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {
            t: int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])  # noqa: S608 - fixed names
            for t in _COUNTED_TABLES
            if t in tables
        }
    finally:
        conn.close()
    return {"integrity": check, "schema_version": version, "row_counts": counts}


def create_backup_set(*, label: str | None = None) -> Path:
    """Write and verify a backup set; returns its directory."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = f"-{label}" if label else ""
    dest = backup_root() / f"{PREFIX}{stamp}{suffix}"
    dest.mkdir(parents=True)
    try:
        source_path = Path(settings.db_path)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(str(source_path))
        try:
            target = sqlite3.connect(str(dest / DB_NAME))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        for name in _TREES:
            src = _tree_source(name)
            if src.exists() and any(src.iterdir()):
                shutil.copytree(src, dest / name)
        files = {
            str(p.relative_to(dest).as_posix()): {"bytes": p.stat().st_size, "sha256": _sha256(p)}
            for p in sorted(dest.rglob("*"))
            if p.is_file()
        }
        facts = _db_facts(dest / DB_NAME)
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "label": label,
            "app_env": settings.app_env,
            "files": files,
            **facts,
        }
        (dest / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        verify_backup_set(dest)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def verify_backup_set(path: Path) -> dict[str, Any]:
    """Check checksums and database integrity; raises :class:`BackupError`."""
    manifest_path = path / MANIFEST
    if not manifest_path.exists():
        raise BackupError(f"{path.name}: no manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for rel, meta in manifest["files"].items():
        file = path / rel
        if not file.exists():
            raise BackupError(f"{path.name}: missing {rel}")
        if _sha256(file) != meta["sha256"]:
            raise BackupError(f"{path.name}: checksum mismatch for {rel}")
    facts = _db_facts(path / DB_NAME)
    if facts["integrity"] != "ok":
        raise BackupError(f"{path.name}: integrity_check failed: {facts['integrity']}")
    return dict(manifest)


def list_backup_sets() -> list[Path]:
    """Backup sets, newest first."""
    return sorted(
        (p for p in backup_root().glob(f"{PREFIX}*") if p.is_dir() and (p / MANIFEST).exists()),
        reverse=True,
    )


def last_verified_backup_time() -> float | None:
    """Unix time of the newest set's manifest (its verification time)."""
    sets = list_backup_sets()
    return (sets[0] / MANIFEST).stat().st_mtime if sets else None


def last_offsite_backup_time() -> float | None:
    """Unix time of the last successful off-host copy, if one was recorded."""
    marker = Path(settings.data_dir) / OFFSITE_STATUS
    return marker.stat().st_mtime if marker.exists() else None


def prune_backups(keep: int | None = None) -> list[Path]:
    """Delete all but the newest ``keep`` sets; pre-migration sets count too."""
    keep = settings.backup_retention_count if keep is None else keep
    doomed = list_backup_sets()[max(keep, 1) :]
    for path in doomed:
        shutil.rmtree(path, ignore_errors=True)
    return doomed


def restore_backup_set(path: Path) -> dict[str, Any]:
    """Restore ``path`` over the live data (the API must be stopped).

    Verifies the set, takes a safety backup of the current data, then
    restores the database via the SQLite backup API and replaces the media
    and profile trees. Returns the restored manifest.
    """
    manifest = verify_backup_set(path)
    live = Path(settings.db_path)
    if live.exists():
        create_backup_set(label="pre-restore")
    live.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{(path / DB_NAME).as_posix()}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(str(live))
        try:
            source.backup(target)
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            target.close()
    finally:
        source.close()
    for name in _TREES:
        dst = _tree_source(name)
        if dst.exists():
            shutil.rmtree(dst)
        if (path / name).exists():
            shutil.copytree(path / name, dst)
    from src.memory.db import reset_schema_cache

    reset_schema_cache()  # the restored schema may be older: let startup migrate it
    restored = _db_facts(live)
    if restored["integrity"] != "ok" or restored["row_counts"] != manifest["row_counts"]:
        raise BackupError("restored database does not match the backup manifest")
    return manifest
