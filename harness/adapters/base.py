"""``Adapter``: everything the engine needs to know about one tool."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..harvest import Captured, HarvestReport
from ..local import LocalHome


class HarnessNotConfigured(Exception):
    """The machine is not connected to a harness (or not for this tool/account) yet."""


@dataclass(frozen=True)
class Account:
    """A tool account found on this machine. ``key`` identifies it to the adapter."""

    key: str | None
    summary: str


class Adapter(ABC):
    """One AI tool. Subclasses provide capture (harvest + hooks) and installation."""

    #: Tool id used in profiles and connections, e.g. "claude-code".
    tool: str = ""

    def __init__(self, local: LocalHome | None = None) -> None:
        self.local = local or LocalHome()

    @abstractmethod
    def harvest(self, exclude: list[str] | None = None) -> list[Captured]:
        """Read everything built inside the tool (no writing)."""

    @abstractmethod
    def run_harvest(self, session: str | None = None) -> HarvestReport:
        """Capture into the harness repository (the only way content gets in)."""

    @abstractmethod
    def prune_harvest(self) -> list[str]:
        """Remove previously captured items that are now excluded."""

    def is_present(self) -> bool:
        """Whether this tool is installed / has data on this machine."""
        return bool(self.accounts())

    def is_connected(self) -> bool:
        """Whether this machine's tool account(s) are already bound to profiles."""
        bindings = (self.local.settings().get("profiles") or {}).get(self.tool) or {}
        return any(account.key in bindings for account in self.accounts())

    def accounts(self) -> list[Account]:
        """Accounts of this tool on this machine (one by default)."""
        return [Account(None, self.tool)]

    def preview(self, exclude: list[str]) -> list[str]:
        """What a capture would save, one line per item (for setup)."""
        return [f"{i.kind.value:11} {i.name}" for i in self.harvest(exclude)]

    def capture(self) -> str:
        """Capture everything now (used by setup); returns a short summary."""
        return self.run_harvest().summary()

    @abstractmethod
    def handle_hook(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """React to a tool event; return a response for the tool, if any."""

    @abstractmethod
    def install(self, profile_id: str, label: str, repo_root: Path | None = None,
                hooks: bool = True, environment: str | None = None,
                account_key: str | None = None) -> list[str]:
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
