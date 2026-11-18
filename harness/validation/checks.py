"""Individual checks run against a content repository.

A ``Check`` looks at one aspect of the repository and records problems in
a ``Report``. New kinds of checks are new subclasses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..repo import ContentRepo
from .readers import FileReader, ReadError, YamlReader
from .report import Report


class Check(ABC):
    @abstractmethod
    def run(self, repo: ContentRepo, report: Report) -> None:
        """Inspect ``repo`` and add any problems to ``report``."""


class SchemaCheck(Check):
    """Every file matching ``pattern`` must satisfy schema ``schema``."""

    IGNORED_NAMES = frozenset({"README.md", ".gitkeep"})

    def __init__(self, pattern: str, schema: str, reader: FileReader | None = None) -> None:
        self.pattern = pattern
        self.schema = schema
        self.reader = reader or YamlReader()

    def run(self, repo: ContentRepo, report: Report) -> None:
        for path in sorted(repo.root.glob(self.pattern)):
            if path.is_file() and path.name not in self.IGNORED_NAMES:
                self._check_file(repo, path, report)

    def _check_file(self, repo: ContentRepo, path: Path, report: Report) -> None:
        report.checked += 1
        where = path.relative_to(repo.root).as_posix()
        try:
            data = self.reader.read(path)
        except ReadError as exc:
            report.add(where, str(exc))
            return
        for message in repo.schemas.errors(self.schema, data):
            report.add(where, message)

    def __repr__(self) -> str:
        return f"SchemaCheck({self.pattern!r} -> {self.schema!r})"


class AssetSizeCheck(Check):
    """Files above the configured inline limit must be stored outside Git."""

    def run(self, repo: ContentRepo, report: Report) -> None:
        assets = repo.path(repo.layout.assets_dir)
        if not assets.is_dir():
            return
        limit = repo.config.max_inline_asset_bytes
        for path in assets.rglob("*"):
            if path.is_file() and path.stat().st_size > limit:
                size_mb = path.stat().st_size / (1024 * 1024)
                report.add(
                    path.relative_to(repo.root).as_posix(),
                    f"{size_mb:.1f} MB exceeds the inline limit; store it externally "
                    "and reference it from asset.yaml",
                )
