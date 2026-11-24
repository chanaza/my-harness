"""``EngineFreshness``: is this computer's engine older than the one that writes the repository?

The harness repository is shared. GitHub Actions always installs the latest engine (to save
what the connector drops into the inbox), while a computer keeps the engine it was installed
with until `harness update` runs there. A newer engine may change the shared repository
(a new setting, a new form) in ways an older one does not understand, and then this
computer's capture can stop with nobody told - which is what happened: a setting added in
the cloud made every hook on a computer fail for days.

So a computer notices the gap itself: the repository's README names the engine that last
wrote it. When it is newer than this computer's engine, `harness status` says so, the gap is
logged once a day, and the computer updates itself in the background (at most once a day,
so a failing update is not retried on every turn).
"""

from __future__ import annotations

import re
import time

from . import __version__
from .local import LocalHome
from .repo import ContentRepo

#: How often a computer that is behind tries to update itself.
RETRY_SECONDS = 24 * 3600

_WRITTEN_BY = re.compile(r"my-harness\]\([^)]*\) engine \(v(\d+(?:\.\d+)*)\)")


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


class EngineFreshness:
    def __init__(self, local: LocalHome | None = None, installed: str = __version__) -> None:
        self.local = local or LocalHome()
        self.installed = installed

    @staticmethod
    def repository_version(repo: ContentRepo) -> str | None:
        """The engine version that last wrote the repository (its README says), if known."""
        readme = repo.path("README.md")
        if not readme.is_file():
            return None
        match = _WRITTEN_BY.search(readme.read_text("utf-8", errors="replace"))
        return match[1] if match else None

    def behind(self, repo: ContentRepo) -> str | None:
        """The newer version the repository was written by, when this engine is older."""
        theirs = self.repository_version(repo)
        if theirs and version_tuple(theirs) > version_tuple(self.installed):
            return theirs
        return None

    def message(self, repo: ContentRepo) -> str | None:
        newer = self.behind(repo)
        settings = repo.config_file.newer_settings() if repo.config_file.path.is_file() else []
        if not newer and not settings:
            return None
        parts = [f"the engine on this computer (v{self.installed}) is older than the one that "
                 f"wrote the harness (v{newer})" if newer else
                 f"the engine on this computer (v{self.installed}) is older than the harness settings"]
        if settings:
            parts.append(f"settings it does not know yet: {', '.join(settings)}")
        return "; ".join(parts) + ". Run: python -m harness update"

    def update_if_behind(self, repo: ContentRepo, start) -> bool:
        """Start a background update when behind, at most once every RETRY_SECONDS.
        ``start`` runs it (e.g. ``spawn_detached``). Returns True when one was started."""
        message = self.message(repo)
        if not message:
            return False
        state = self.local.state("engine", "freshness")
        if time.time() - float(state.get("last_attempt", 0)) < RETRY_SECONDS:
            return False
        state.set("last_attempt", time.time())
        state.save()
        self.local.log(f"engine behind: {message} (updating in the background)")
        start(["update"], "")
        return True
