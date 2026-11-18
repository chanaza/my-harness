"""``Adapter``: everything the engine needs to know about one tool."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from ..harvest import Captured, HarvestReport
from ..local import LocalHome
from ..repo import ContentRepo


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
    #: For services that are not tied to a machine (e.g. claude.ai): the profile's environment.
    environment: str | None = None
    #: When accounts can be named before anything was found (e.g. by e-mail), the question to ask.
    #: An empty answer skips the tool.
    account_question: str | None = None
    #: Offer this tool in every setup, even when nothing of it is on the machine (account services).
    offered_everywhere: bool = False

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

    def after_setup(self, profiles: list[str]) -> list[str]:
        """Prepare anything the user still has to do by hand; return those steps in plain words."""
        return []

    def deliver_skill(self, target: Path | None = None) -> Path | None:
        """Write the adapter's skill (if any) where the user can upload it; return its path."""
        return None

    def skill_package(self) -> tuple[str, dict[str, bytes]] | None:
        """A skill to install in the tool's account (name, files), when the adapter offers one."""
        return None

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


class AccountBoundAdapter(Adapter):
    """An adapter whose accounts are bound to profiles on this machine and that is captured
    on a schedule (no hooks): Cowork, claude.ai, ..."""

    def bindings(self) -> dict[str, str]:
        """account key -> profile id."""
        return dict((self.local.settings().get("profiles") or {}).get(self.tool) or {})

    def repo(self) -> ContentRepo:
        root = self.local.content_repo()
        if not root:
            raise HarnessNotConfigured(f"No harness repository on this machine. "
                                       f"Run `harness setup {self.tool}`.")
        return ContentRepo(root)

    def bind(self, account_key: str, profile_id: str) -> None:
        settings = self.local.settings()
        settings.setdefault("profiles", {}).setdefault(self.tool, {})[account_key] = profile_id
        self.local.save_settings(profiles=settings["profiles"])

    def prune_harvest(self) -> list[str]:
        from ..harvest import HarvestSync
        repo = self.repo()
        patterns = repo.config.harvest_exclude
        removed: list[str] = []
        for profile in sorted(set(self.bindings().values())):
            removed += HarvestSync(repo, self.local.state("harvest", profile)).prune(
                lambda kind, name: any(fnmatch(f"{kind}:{name}", p) for p in patterns), profile)
        return removed

    def handle_hook(self, event: dict[str, Any], deferred: bool = False) -> dict[str, Any] | None:
        return None  # no hooks: captured on a schedule

    def schedule(self) -> str:
        """One scheduled capture for this tool (every capture.poll_minutes); set up once."""
        from ..scheduler import SchedulerError, system_scheduler
        minutes = self.repo().config.capture.poll_minutes
        scheduled = self.local.settings().get("scheduled") or {}
        if scheduled.get(self.tool) == minutes:
            return f"automatic capture already scheduled (every {minutes} minutes)"
        try:
            task = system_scheduler().install(f"capture-{self.tool}", ["harvest", self.tool], minutes)
        except (SchedulerError, OSError) as exc:
            return f"automatic capture NOT scheduled ({exc}); run `harness harvest {self.tool}`"
        self.local.save_settings(scheduled={**scheduled, self.tool: minutes})
        return task


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
