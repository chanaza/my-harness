"""The storage interface.

Transcripts and live logs (and, later, app data snapshots) do not belong in
Git. They go to a *storage backend* chosen in harness.config.yaml. Every
backend implements this small interface, so the rest of the engine never
knows or cares where the bytes actually live.

To add a backend (e.g. Google Drive API, Postgres, S3):
  1. Subclass ``Storage`` in a new module under harness/storage/.
  2. Decorate it with ``@backends.register`` and import it in
     ``harness/storage/__init__.py``.
  3. Add its name to the ``backend`` enum in schemas/config.schema.json.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageError(Exception):
    """A storage operation failed."""


class Storage(ABC):
    """Key/value storage for text documents.

    Keys are forward-slash paths such as ``claude-code/<session-id>/transcript.jsonl``.
    """

    #: The name used in harness.config.yaml's ``backend`` field.
    backend_name: str = ""

    @classmethod
    @abstractmethod
    def from_settings(cls, settings: dict[str, Any]) -> Storage:
        """Build an instance from a storage block of harness.config.yaml."""

    @abstractmethod
    def write_text(self, key: str, text: str) -> None:
        """Create or replace the document at ``key``."""

    @abstractmethod
    def append_text(self, key: str, text: str) -> None:
        """Append to the document at ``key``, creating it if needed."""

    @abstractmethod
    def read_text(self, key: str) -> str:
        """Return the document at ``key``. Raise StorageError if missing."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Whether a document exists at ``key``."""

    @abstractmethod
    def list_keys(self, prefix: str = "") -> list[str]:
        """All keys that start with ``prefix``, sorted."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the document at ``key``. Missing keys are ignored."""
