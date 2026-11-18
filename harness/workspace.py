"""``WorkspaceScanner``: which Git repositories a session works in, and their state.

Recorded in the session's meta.yaml so a later session (in any tool) knows
exactly which code it was at: remote, branch and commit.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse


@dataclass(frozen=True)
class RepoState:
    path: str
    remote: str | None
    branch: str | None
    head: str | None
    dirty: bool

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class WorkspaceScanner:
    def __init__(self, root: Path, depth: int = 1, timeout: float = 10) -> None:
        self.root = Path(root)
        self.depth = depth
        self.timeout = timeout

    def scan(self) -> list[RepoState]:
        return [self._state(path) for path in self._repositories()]

    def _repositories(self) -> list[Path]:
        candidates = [self.root]
        level = [self.root]
        for _ in range(self.depth):
            level = [c for p in level if p.is_dir() for c in sorted(p.iterdir())
                     if c.is_dir() and not c.name.startswith(".")]
            candidates += level
        return [p for p in candidates if (p / ".git").exists()]

    def _state(self, path: Path) -> RepoState:
        remote = self._git(path, "remote", "get-url", "origin")
        return RepoState(
            path=path.name if path != self.root else ".",
            remote=_without_credentials(remote) if remote else None,
            branch=self._git(path, "rev-parse", "--abbrev-ref", "HEAD"),
            head=self._git(path, "rev-parse", "--short", "HEAD"),
            dirty=bool(self._git(path, "status", "--porcelain")),
        )

    def _git(self, path: Path, *args: str) -> str | None:
        try:
            result = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True,
                                    timeout=self.timeout)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() or None if result.returncode == 0 else None


def _without_credentials(url: str) -> str:
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        return urlunparse(parsed._replace(netloc=parsed.hostname or ""))
    return url
