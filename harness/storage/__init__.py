"""Storage backends and the factory that picks one from configuration."""

from __future__ import annotations

from typing import Any

from .base import Storage, StorageError
from .filesystem import FilesystemStorage

# backend name in harness.config.yaml -> implementation
BACKENDS: dict[str, type[Storage]] = {
    FilesystemStorage.backend_name: FilesystemStorage,
}


def open_storage(settings: dict[str, Any]) -> Storage:
    """Build the backend described by a storage block of harness.config.yaml."""
    name = settings.get("backend")
    try:
        backend = BACKENDS[name]
    except KeyError:
        known = ", ".join(sorted(BACKENDS))
        raise StorageError(f"Unknown storage backend {name!r}. Known backends: {known}") from None
    return backend.from_settings(settings)


__all__ = ["BACKENDS", "FilesystemStorage", "Storage", "StorageError", "open_storage"]
