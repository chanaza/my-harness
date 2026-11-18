"""Maps the ``backend`` name in harness.config.yaml to a Storage class."""

from __future__ import annotations

from typing import Any

from .base import Storage, StorageError


class BackendRegistry:
    """Known storage backends. Register a new one with ``@backends.register``."""

    def __init__(self) -> None:
        self._backends: dict[str, type[Storage]] = {}

    def register(self, backend: type[Storage]) -> type[Storage]:
        if not backend.backend_name:
            raise ValueError(f"{backend.__name__} must define backend_name")
        self._backends[backend.backend_name] = backend
        return backend

    def names(self) -> list[str]:
        return sorted(self._backends)

    def create(self, settings: dict[str, Any]) -> Storage:
        """Build the backend described by a storage block of harness.config.yaml."""
        name = settings.get("backend")
        if name not in self._backends:
            raise StorageError(f"Unknown storage backend {name!r}. Known: {', '.join(self.names())}")
        return self._backends[name].from_settings(settings)


#: The engine-wide registry. Backend modules register themselves on import.
backends = BackendRegistry()
