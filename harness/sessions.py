"""Session records: everything about one conversation, tied together by its id.

In Git:      sessions/<profile>/<session-id>/{meta.yaml, summary.md}
In storage:  <profile>/<session-id>/transcript.*
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import yaml_io
from .documents import MarkdownDocument
from .provenance import now_iso
from .repo import ContentRepo
from .storage import Storage

SESSIONS_AREA = "sessions"
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def safe_id(raw: str) -> str:
    """Make a tool's session id safe to use as a folder name."""
    cleaned = _SAFE_ID.sub("-", raw).strip("-.")
    if not cleaned:
        raise ValueError(f"Unusable session id: {raw!r}")
    return cleaned


class SessionRecord:
    """One conversation in one profile (tool + account)."""

    def __init__(self, repo: ContentRepo, profile: str, session_id: str) -> None:
        self.repo = repo
        self.profile = profile
        self.id = safe_id(session_id)
        self.native_id = session_id
        self.folder = repo.path(SESSIONS_AREA, profile, self.id)

    # --- keys in external storage -------------------------------------------

    def storage_key(self, name: str) -> str:
        return f"{self.profile}/{self.id}/{name}"

    def transcript_key(self, extension: str) -> str:
        return self.storage_key(f"transcript{extension}")

    def save_transcript(self, storage: Storage, source: Path,
                        activity_at: str | None = None) -> tuple[str, bool] | None:
        """Copy the tool's transcript into transcript storage.

        Returns (key, changed); nothing is written when the stored copy is identical.
        """
        source = Path(source)
        if not source.is_file():
            return None
        key = self.transcript_key(source.suffix)
        text = source.read_text("utf-8")
        changed = not storage.exists(key) or storage.read_text(key) != text
        if changed:
            storage.write_text(key, text)
        if self.meta().get("transcript") != key:
            self.touch(activity_at=activity_at, transcript=key)
        return key, changed

    # --- meta.yaml ------------------------------------------------------------

    @property
    def meta_path(self) -> Path:
        return self.folder / "meta.yaml"

    def meta(self) -> dict[str, Any]:
        if not self.meta_path.is_file():
            return {}
        return dict(yaml_io.load(self.meta_path.read_text("utf-8")) or {})

    def touch(self, activity_at: str | None = None, **fields: Any) -> dict[str, Any]:
        """Create meta.yaml on first use; update ``fields`` and the activity time
        (now, unless ``activity_at`` gives it, e.g. when importing an old session)."""
        meta = self.meta()
        if not meta:
            meta = {"id": self.id, "profile": self.profile, "started_at": now_iso()}
            if self.native_id != self.id:
                meta["native_id"] = self.native_id
        meta.update({k: v for k, v in fields.items() if v is not None})
        meta["last_activity_at"] = activity_at or now_iso()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(yaml_io.dump(meta), encoding="utf-8")
        return meta

    # --- summary and compactions ---------------------------------------------

    @property
    def summary_path(self) -> Path:
        return self.folder / "summary.md"

    def summary(self) -> MarkdownDocument | None:
        return MarkdownDocument.read(self.summary_path) if self.summary_path.is_file() else None

    def write_summary(self, text: str, reason: str, context_percent: float | None = None,
                      user_messages: int | None = None) -> int:
        """Replace the rolling summary. Returns the new checkpoint number."""
        previous = self.summary()
        number = (previous.meta.get("checkpoint", 0) if previous else 0) + 1
        meta: dict[str, Any] = {"session": self.id, "updated_at": now_iso(),
                                "checkpoint": number, "reason": reason}
        if context_percent is not None:
            meta["context_percent"] = round(context_percent, 1)
        if user_messages is not None:
            meta["user_messages"] = user_messages
        MarkdownDocument(meta, text.strip() + "\n").write(self.summary_path)
        self.touch()
        return number
