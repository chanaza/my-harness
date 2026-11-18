"""Storage for data that does not belong in Git (transcripts, live logs, later app data)."""

from .base import Storage, StorageError
from .filesystem import FilesystemStorage  # importing it registers the backend
from .registry import BackendRegistry, backends

__all__ = ["BackendRegistry", "FilesystemStorage", "Storage", "StorageError", "backends"]
