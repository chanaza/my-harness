"""``Adapter``: everything the engine needs to know about one tool."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..harvest import Captured
from ..local import LocalHome


class Adapter(ABC):
    """One AI tool. Subclasses provide capture (harvest + hooks) and installation."""

    #: Tool id used in profiles and connections, e.g. "claude-code".
    tool: str = ""

    def __init__(self, local: LocalHome | None = None) -> None:
        self.local = local or LocalHome()

    @abstractmethod
    def harvest(self) -> list[Captured]:
        """Read everything built inside the tool (no writing)."""

    @abstractmethod
    def handle_hook(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """React to a tool event; return a response for the tool, if any."""

    @abstractmethod
    def install(self, profile_id: str, label: str, repo_root: Path | None = None,
                hooks: bool = True, environment: str | None = None) -> list[str]:
        """Bind this machine's tool account to a profile (and, with ``hooks``, install
        automatic capture); return what was done."""


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, type[Adapter]] = {}

    def register(self, adapter: type[Adapter]) -> type[Adapter]:
        self._adapters[adapter.tool] = adapter
        return adapter

    def names(self) -> list[str]:
        return sorted(self._adapters)

    def create(self, tool: str, local: LocalHome | None = None) -> Adapter:
        if tool not in self._adapters:
            raise KeyError(f"No adapter for {tool!r}. Available: {', '.join(self.names())}")
        return self._adapters[tool](local)


adapters = AdapterRegistry()
