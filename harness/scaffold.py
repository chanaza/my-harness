"""``Scaffolder``: creates a new content repository (`harness init`).

The content repository is only ever created and changed through the engine,
so everything it contains on day one comes from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from .layout import DEFAULT_LAYOUT, RepoLayout
from .repo import ContentRepo

SUPPORTED_TOOLS: tuple[str, ...] = (
    "claude-code", "claude", "chatgpt", "cursor", "genspark", "base44", "monday",
)


class ScaffoldError(Exception):
    """The target cannot be initialised."""


@dataclass
class InitOptions:
    """Choices made at init time. ``storage_paths`` maps storage area -> folder."""

    owner: str
    language: str = "en"
    tools: list[str] = field(default_factory=lambda: list(SUPPORTED_TOOLS))
    storage_paths: dict[str, str] = field(default_factory=dict)

    def config_changes(self) -> dict[str, object]:
        changes: dict[str, object] = {
            "owner": self.owner,
            "language.working": self.language,
            "tools": list(self.tools),
        }
        for area, path in self.storage_paths.items():
            changes[f"storage.{area}.path"] = path
        return changes


class Scaffolder:
    """Builds a content repository from a template folder and a layout."""

    def __init__(self, layout: RepoLayout = DEFAULT_LAYOUT, template: Traversable | None = None) -> None:
        self.layout = layout
        self.template = template or resources.files("harness.templates").joinpath("content_repo")

    def create(self, target: Path, options: InitOptions) -> ContentRepo:
        target = Path(target)
        self._ensure_empty(target)
        target.mkdir(parents=True, exist_ok=True)

        self._copy(self.template, target, overwrite=True)
        repo = ContentRepo(target, self.layout)
        repo.config_file.update(options.config_changes())
        self._create_areas(repo)
        from .guide import RepoGuide

        RepoGuide(repo).write()  # the map of the repository, rebuilt by the engine on every save
        return repo

    def ensure_structure(self, repo: ContentRepo) -> list[Path]:
        """Add template files and areas that a newer engine introduced. Never overwrites."""
        created = self._copy(self.template, repo.root, overwrite=False)
        created += self._create_areas(repo)
        return created

    @staticmethod
    def _ensure_empty(target: Path) -> None:
        if target.exists() and any(p.name != ".git" for p in target.iterdir()):
            raise ScaffoldError(f"{target} is not empty. `harness init` only runs on an empty folder.")

    def _copy(self, source: Traversable, target: Path, overwrite: bool) -> list[Path]:
        """Copy the template tree; returns files written."""
        written: list[Path] = []
        for entry in source.iterdir():
            destination = target / entry.name
            if entry.is_dir():
                destination.mkdir(exist_ok=True)
                written += self._copy(entry, destination, overwrite)
            elif overwrite or not destination.exists():
                destination.write_bytes(entry.read_bytes())
                written.append(destination)
        return written

    def _create_areas(self, repo: ContentRepo) -> list[Path]:
        """Create missing areas; empty ones get a .gitkeep so Git tracks them."""
        created: list[Path] = []
        for area in self.layout.areas:
            folder = repo.path(area.path)
            if not folder.is_dir():
                folder.mkdir(parents=True)
                created.append(folder)
            if not any(folder.iterdir()):
                (folder / ".gitkeep").touch()
        return created
