"""``ContentRepo``: the entry point for working with a content repository."""

from __future__ import annotations

from pathlib import Path

from .config import ConfigFile, HarnessConfig
from .layout import DEFAULT_LAYOUT, RepoLayout
from .schemas import SchemaRegistry
from .storage import BackendRegistry, Storage, backends


class ContentRepo:
    """A content repository on disk, with its layout, configuration and storage.

    Everything that reads or changes a content repository goes through this
    object, so commands and adapters never assemble paths themselves.
    """

    def __init__(
        self,
        root: Path,
        layout: RepoLayout = DEFAULT_LAYOUT,
        schemas: SchemaRegistry | None = None,
        storage_backends: BackendRegistry = backends,
    ) -> None:
        self.root = Path(root)
        self.layout = layout
        self.schemas = schemas or SchemaRegistry.bundled()
        self._backends = storage_backends
        self.config_file = ConfigFile(self.root / layout.config_file, self.schemas)

    @property
    def config(self) -> HarnessConfig:
        """The current configuration (re-read, so it reflects recent changes)."""
        return self.config_file.load()

    def path(self, *parts: str) -> Path:
        """Absolute path of a location inside the repository."""
        return self.root.joinpath(*parts)

    def storage(self, name: str) -> Storage:
        """The storage backend configured for ``name`` (e.g. 'transcripts')."""
        return self._backends.create(self.config.storage_settings(name))

    def __repr__(self) -> str:
        return f"ContentRepo({str(self.root)!r})"
