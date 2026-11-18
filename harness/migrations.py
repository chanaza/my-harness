"""Content migrations: bring a content repository's existing data to the current engine.

Run by `harness upgrade`. Every migration is idempotent: running it again on
migrated content changes nothing. Add new ones to ``MIGRATIONS`` in order.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod

from . import yaml_io
from .digest import session_part
from .documents import MarkdownDocument
from .repo import ContentRepo
from .storage import StorageError


class Migration(ABC):
    #: Short, stable identifier.
    id: str = ""
    description: str = ""

    @abstractmethod
    def apply(self, repo: ContentRepo) -> list[str]:
        """Migrate ``repo``; return what changed (empty when already migrated)."""


class SimplifySessionRecords(Migration):
    """v0.3: a session keeps meta.yaml + summary.md (session sections) + the transcript."""

    id = "simplify-session-records"
    description = "Drop compactions, tail and live-log records; summaries keep session sections only"
    OBSOLETE_META = ("tail", "live_log")
    OBSOLETE_STORED = ("tail.md", "live-log.md")

    def apply(self, repo: ContentRepo) -> list[str]:
        changes: list[str] = []
        for meta_path in sorted(repo.root.glob("sessions/*/*/meta.yaml")):
            folder = meta_path.parent
            where = folder.relative_to(repo.root).as_posix()
            meta = yaml_io.load(meta_path.read_text("utf-8")) or {}
            if any(k in meta for k in self.OBSOLETE_META):
                profile = meta.get("profile")
                for key in self.OBSOLETE_META:
                    stored = meta.pop(key, None)
                    if stored and profile:
                        changes += self._delete_stored(repo, profile, stored)
                meta_path.write_text(yaml_io.dump(meta), encoding="utf-8")
                changes.append(f"{where}/meta.yaml")
            if (folder / "compactions").is_dir():
                shutil.rmtree(folder / "compactions")
                changes.append(f"{where}/compactions (derivable from the transcript)")
            summary_path = folder / "summary.md"
            if summary_path.is_file():
                summary = MarkdownDocument.read(summary_path)
                trimmed = session_part(summary.body)
                if trimmed.strip() != summary.body.strip():
                    summary.body = trimmed
                    summary.write(summary_path)
                    changes.append(f"{where}/summary.md")
        return changes

    @staticmethod
    def _delete_stored(repo: ContentRepo, profile: str, key: str) -> list[str]:
        try:
            storage = repo.storage("transcripts", profile)
            if storage.exists(key):
                storage.delete(key)
                return [f"storage: {key}"]
        except StorageError:
            pass  # unreachable from this machine; harmless leftover
        return []


class RemoveEngineArtifacts(Migration):
    """Skills the engine installs (harness-save, harness-export) are not the user's content."""

    id = "remove-engine-artifacts"
    description = "Remove the engine's own skills saved by older versions"

    def apply(self, repo: ContentRepo) -> list[str]:
        from .harvest import ENGINE_OWNED
        changes = []
        for owned in sorted(ENGINE_OWNED):
            kind, name = owned.split(":", 1)
            folder = repo.path("core", f"{kind}s", name)
            if kind == "skill" and folder.is_dir():
                shutil.rmtree(folder)
                changes.append(f"core/skills/{name}")
        return changes


MIGRATIONS: tuple[Migration, ...] = (SimplifySessionRecords(), RemoveEngineArtifacts())


def run_migrations(repo: ContentRepo) -> dict[str, list[str]]:
    return {m.id: changes for m in MIGRATIONS if (changes := m.apply(repo))}
