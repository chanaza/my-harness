"""Storage for data that does not belong in Git (transcripts, live logs, later app data)."""

from .base import Storage, StorageError
from .filesystem import FilesystemStorage  # importing a backend registers it
from .git import GitStorage
from .registry import BackendRegistry, backends

__all__ = ["BackendRegistry", "FilesystemStorage", "GitStorage", "Storage", "StorageError", "backends"]
