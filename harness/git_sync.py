"""``GitSync``: commit (and push) a content repository after captures.

Failures never raise: capture must not break the tool it runs in. They are
returned as messages for the caller to log.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import GitSettings


@dataclass(frozen=True)
class SyncResult:
    committed: bool
    pushed: bool
    message: str = ""


class GitSync:
    def __init__(self, root: Path, settings: GitSettings, timeout: float = 60) -> None:
        self.root = Path(root)
        self.settings = settings
        self.timeout = timeout

    def is_repository(self) -> bool:
        return (self.root / ".git").exists()

    def sync(self, message: str, push: bool = False) -> SyncResult:
        """Commit everything if enabled; push too when ``push`` and enabled."""
        if not self.settings.auto_commit or not self.is_repository():
            return SyncResult(False, False, "auto-commit off or not a git repository")
        try:
            self._git("add", "-A")
            committed = self._git("diff", "--cached", "--quiet", check=False).returncode != 0
            if committed:
                self._git("commit", "-q", "-m", message)
            pushed = False
            if push and self.settings.auto_push and self._has_remote():
                # -u keeps the branch linked to origin, so `git status` reports it as pushed.
                self._git("push", "-q", "-u", "origin", "HEAD")
                pushed = True
            return SyncResult(committed, pushed)
        except (subprocess.SubprocessError, OSError) as exc:
            return SyncResult(False, False, f"git failed: {exc}")

    def _has_remote(self) -> bool:
        return bool(self._git("remote", check=False).stdout.strip())

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True,
                              timeout=self.timeout, check=check)
