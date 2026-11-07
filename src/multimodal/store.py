"""Submission store, retention and deletion for multimodal data (ADR-0034).

**Privacy policy** (also in ``docs/multimodal-assessment.md``):

- **Raw audio is not kept by default.** It is decoded in memory, written to a
  temporary file only for the recogniser, and the file is deleted
  immediately.
- **Opt-in retention.** With the learner's explicit consent
  (``retain_audio=True``), the raw upload is kept under
  ``<data_dir>/media/<user>/`` for at most :data:`RETENTION_DAYS` days.
  :func:`purge_expired` deletes it after that. The app starts a purge on
  every submission.
- **Derived artifacts** (transcript, measures, feedback) live in the
  ``media_submissions`` row. They are deleted with the submission
  (:func:`delete_submission`) or the account (privacy deletion).
- **Access.** Every read is scoped to the authenticated user id. There is no
  cross-user lookup.
- **Logging.** Nothing here logs audio bytes or transcript text; only ids,
  sizes, formats and statuses.
- **Evidence.** Evidence rows hold scores and measures, never transcript
  text. They remain part of the learning history after a single submission is
  deleted, and are removed with the account.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import settings
from src.memory.db import get_connection
from src.memory.schema import init_all
from src.multimodal.contracts import AssessmentReport

logger = logging.getLogger("polyglot.multimodal.store")

RETENTION_DAYS = 30


def _media_dir(user_id: str) -> Path:
    safe = "".join(c for c in user_id if c.isalnum() or c in "-_") or "anon"
    return Path(settings.data_dir) / "media" / safe


def save_submission(
    report: AssessmentReport, *, raw: bytes | None = None, retain_audio: bool = False
) -> None:
    """Persist a report; keep the raw upload only with consent."""
    init_all()
    storage_path: str | None = None
    retain_until: str | None = None
    asset = report.asset
    if retain_audio and raw is not None and asset is not None:
        directory = _media_dir(report.user_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{asset.asset_id}.{asset.media_format}"
        path.write_bytes(raw)
        storage_path = str(path)
        retain_until = (datetime.now(UTC) + timedelta(days=RETENTION_DAYS)).isoformat()
        asset.retained, asset.retain_until = True, retain_until
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO media_submissions (submission_id, user_id, language, "
            "modality, task_type, status, media_format, sha256, size_bytes, duration_s, "
            "retained, retain_until, storage_path, report, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report.submission_id,
                report.user_id,
                report.language,
                report.modality.value,
                report.task_type,
                report.status.value,
                None if asset is None else asset.media_format,
                None if asset is None else asset.sha256,
                None if asset is None else asset.size_bytes,
                None if asset is None else asset.duration_s,
                int(storage_path is not None),
                retain_until,
                storage_path,
                json.dumps(report.as_dict(), default=str),
                report.created_at,
            ),
        )
    logger.info(
        "submission saved: id=%s status=%s retained=%s",
        report.submission_id, report.status.value, storage_path is not None,
    )  # fmt: skip


def _row(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["report"] = json.loads(data["report"])
    data.pop("storage_path", None)  # never expose server paths
    data["retained"] = bool(data["retained"])
    return data


def get_submission(user_id: str, submission_id: str) -> dict[str, Any] | None:
    init_all()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM media_submissions WHERE submission_id=? AND user_id=?",
            (submission_id, user_id),
        ).fetchone()
    return _row(row) if row else None


def list_submissions(
    user_id: str, language: str | None = None, *, limit: int = 50
) -> list[dict[str, Any]]:
    init_all()
    query = "SELECT * FROM media_submissions WHERE user_id=?"
    params: list[Any] = [user_id]
    if language is not None:
        query += " AND language=?"
        params.append(language)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(int(limit))
    with get_connection() as conn:
        return [_row(r) for r in conn.execute(query, params).fetchall()]


def _unlink(path: str | None) -> bool:
    if not path:
        return False
    p = Path(path)
    if p.exists():
        p.unlink()
        return True
    return False


def delete_submission(user_id: str, submission_id: str) -> bool:
    """Delete one submission's derived artifacts and any retained audio."""
    init_all()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT storage_path FROM media_submissions WHERE submission_id=? AND user_id=?",
            (submission_id, user_id),
        ).fetchone()
        if row is None:
            return False
        _unlink(row["storage_path"])
        conn.execute(
            "DELETE FROM media_submissions WHERE submission_id=? AND user_id=?",
            (submission_id, user_id),
        )
    return True


def purge_expired(now: datetime | None = None) -> int:
    """Delete retained audio past its retention date (rows keep derived data)."""
    init_all()
    now_iso = (now or datetime.now(UTC)).isoformat()
    purged = 0
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT submission_id, storage_path FROM media_submissions "
            "WHERE retained=1 AND retain_until IS NOT NULL AND retain_until <= ?",
            (now_iso,),
        ).fetchall()
        for r in rows:
            purged += int(_unlink(r["storage_path"]))
            conn.execute(
                "UPDATE media_submissions SET retained=0, storage_path=NULL, retain_until=NULL "
                "WHERE submission_id=?",
                (r["submission_id"],),
            )
    return purged


def export_for_user(user_id: str) -> list[dict[str, Any]]:
    """Submissions (derived data and retention status) for a privacy export."""
    return list_submissions(user_id, limit=1_000_000)


def delete_for_user(user_id: str) -> int:
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT storage_path FROM media_submissions WHERE user_id=?", (user_id,)
        ).fetchall()
        for r in rows:
            _unlink(r["storage_path"])
        cur = conn.execute("DELETE FROM media_submissions WHERE user_id=?", (user_id,))
        count = int(cur.rowcount or 0)
    directory = _media_dir(user_id)
    if directory.exists():
        for f in directory.iterdir():
            f.unlink()
        directory.rmdir()
    return count
