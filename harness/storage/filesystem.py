"""Filesystem storage backend.

Stores documents as files under a root folder. Point the root at a folder
synced by Google Drive for desktop (or Dropbox, OneDrive, ...) and the
documents are in the cloud with no API keys involved.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any

from .base import Storage, StorageError
from .registry import backends


@backends.register
class FilesystemStorage(Storage):
    backend_name = "filesystem"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> FilesystemStorage:
        if not settings.get("path"):
            raise StorageError("The filesystem backend needs a 'path' setting.")
        return cls(Path(os.path.expandvars(os.path.expanduser(settings["path"]))))

    def _path(self, key: str) -> Path:
        parts = PurePosixPath(key).parts
        if not parts or key.startswith("/") or ".." in parts:
            raise StorageError(f"Invalid storage key: {key!r}")
        return self.root.joinpath(*parts)

    def write_text(self, key: str, text: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def append_text(self, key: str, text: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(text)

    def read_text(self, key: str) -> str:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"No document at {key!r}")
        return path.read_text(encoding="utf-8")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list_keys(self, prefix: str = "") -> list[str]:
        if not self.root.is_dir():
            return []
        keys = (p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())
        return sorted(k for k in keys if k.startswith(prefix))

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
