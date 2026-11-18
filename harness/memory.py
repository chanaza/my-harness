"""``MemoryStore``: memory entries with provenance and conflict tracking."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .documents import MarkdownDocument
from .provenance import Origin, Provenance
from .repo import ContentRepo
from .text import slugify

MEMORY_AREA = "memory"
KINDS = ("fact", "decision", "preference", "project-state")


@dataclass(frozen=True)
class MemoryResult:
    path: Path
    action: str  # "created", "updated", "unchanged" or "conflict"


class MemoryStore:
    """Adds and updates entries under memory/.

    If an entry was last changed by a *different* profile and the new text
    differs, nothing is overwritten: the new text is stored as a separate
    entry, both are marked ``disputed`` and linked with ``conflicts_with``.
    """

    def __init__(self, repo: ContentRepo) -> None:
        self.repo = repo
        self.root = repo.path(MEMORY_AREA)

    def path_for(self, entry_id: str) -> Path:
        return self.root / f"{entry_id}.md"

    def put(self, entry_id: str, body: str, origin: Origin, kind: str = "fact",
            subject: str | None = None) -> MemoryResult:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        entry_id = slugify(entry_id)
        path = self.path_for(entry_id)
        if not path.is_file():
            self._write(path, entry_id, kind, subject, body, Provenance.new(origin))
            return MemoryResult(path, "created")

        existing = MarkdownDocument.read(path)
        if existing.body.strip() == body.strip():
            return MemoryResult(path, "unchanged")
        if Provenance.last_profile(existing.meta.get("provenance")) not in (None, origin.profile):
            return self._conflict(existing, path, entry_id, kind, subject, body, origin)

        existing.meta["provenance"] = Provenance.updated(existing.meta.get("provenance"), origin)
        existing.meta["kind"] = kind
        if subject:
            existing.meta["subject"] = subject
        existing.body = body.strip() + "\n"
        existing.write(path)
        return MemoryResult(path, "updated")

    def _conflict(self, existing: MarkdownDocument, path: Path, entry_id: str, kind: str,
                  subject: str | None, body: str, origin: Origin) -> MemoryResult:
        other_id = f"{entry_id}--{slugify(origin.profile)}"
        other_path = self.path_for(other_id)
        self._write(other_path, other_id, kind, subject, body, Provenance.new(origin),
                    status="disputed", conflicts_with=[entry_id])
        existing.meta["status"] = "disputed"
        links = list(existing.meta.get("conflicts_with", []))
        if other_id not in links:
            existing.meta["conflicts_with"] = links + [other_id]
        existing.write(path)
        return MemoryResult(other_path, "conflict")

    @staticmethod
    def _write(path: Path, entry_id: str, kind: str, subject: str | None, body: str,
               provenance: dict, status: str = "active", conflicts_with: list[str] | None = None) -> None:
        meta = {"id": entry_id, "kind": kind, "status": status}
        if subject:
            meta["subject"] = subject
        if conflicts_with:
            meta["conflicts_with"] = conflicts_with
        meta["provenance"] = provenance
        MarkdownDocument(meta, body.strip() + "\n").write(path)
