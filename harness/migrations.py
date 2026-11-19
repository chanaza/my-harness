"""Content migrations: bring a content repository's existing data to the current engine.

Run by `harness upgrade`. Every migration is idempotent: running it again on
migrated content changes nothing. Add new ones to ``MIGRATIONS`` in order.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

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
            workflow = repo.path("core", "workflows", f"{name}.yaml")
            if kind == "workflow" and workflow.is_file():
                workflow.unlink()
                changes.append(f"core/workflows/{name}.yaml")
        return changes


class DescribeBeforeFullContent(Migration):
    """Descriptions before 0.17 named memory by number and sent skills without their files.
    Their numbered memory copies (replaced by memory named by topic) and the conflict copies
    a bare description caused are removed; their records are dropped so the next description
    is saved in full."""

    id = "describe-before-full-content"
    description = "Remove numbered memory copies and bare-description conflicts of 0.16"

    def apply(self, repo: ContentRepo) -> list[str]:
        import json
        import re
        changes = []
        for state in sorted(repo.path("inbox", ".state").glob("*-describe.json")):
            data = json.loads(state.read_text("utf-8"))
            written = data.get("written") or {}
            if not any(re.match(r"^memory:global:memory-\d+$", key) for key in written):
                continue
            from .text import slugify
            for key, path in sorted(written.items()):
                kind, _, name = key.split(":", 2)
                target = repo.path(path)
                numbered = kind == "memory" and re.fullmatch(r"memory-\d+", name)
                # a folder named before names kept their letters (e.g. a Hebrew name)
                misnamed = kind in ("project", "plugin", "skill") and Path(path).name != slugify(name)
                if numbered or misnamed:
                    if target.is_dir():
                        shutil.rmtree(target)
                    elif target.is_file():
                        target.unlink()
                    changes.append(path)
            profile = state.name.removesuffix("-describe.json")
            for skill in sorted(repo.path("inbox", "conflicts", profile).glob("**/core/skills/*/SKILL.md")):
                if not skill.read_text("utf-8").split("---", 2)[-1].strip():   # a bare description
                    shutil.rmtree(skill.parent)
                    changes.append(skill.parent.relative_to(repo.root).as_posix())
            state.unlink()
            changes.append(state.relative_to(repo.root).as_posix())
        return changes


class UniformLineEndings(Migration):
    """Files once saved from Windows with CRLF line endings are stored with LF, like the rest
    (with .gitattributes from the template, every later save is stored that way by Git)."""

    id = "uniform-line-endings"
    description = "Store every text file with the same line endings on every computer"

    def apply(self, repo: ContentRepo) -> list[str]:
        import subprocess
        if not (repo.root / ".git").exists() or not (repo.root / ".gitattributes").is_file():
            return []
        subprocess.run(["git", "add", "--renormalize", "."], cwd=repo.root, capture_output=True, check=False)
        changed = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=repo.root,
                                 capture_output=True, text=True, check=False).stdout.split()
        return changed


MIGRATIONS: tuple[Migration, ...] = (SimplifySessionRecords(), RemoveEngineArtifacts(),
                                     DescribeBeforeFullContent(), UniformLineEndings())


def run_migrations(repo: ContentRepo) -> dict[str, list[str]]:
    return {m.id: changes for m in MIGRATIONS if (changes := m.apply(repo))}
