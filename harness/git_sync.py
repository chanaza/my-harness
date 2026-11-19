"""``GitSync``: commit (and push) a content repository after captures.

Failures never raise: capture must not break the tool it runs in. They are
returned as messages for the caller to log.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import GitSettings
from .local import LocalHome


@dataclass(frozen=True)
class SyncResult:
    committed: bool
    pushed: bool
    message: str = ""


class GitSync:
    """Commit, pull and push a harness repository.

    Two machines changing the same YAML file are reconciled by content (see
    harness/merge.py), through a Git merge driver this class registers locally.
    Failures are logged (``harness status`` shows them), never raised.
    """

    MERGE_DRIVER = "harness"
    GENERATED_DRIVER = "harness-generated"
    #: Paths the engine generates from the content (merged by keeping either side).
    GENERATED = ("connector/**",)

    def __init__(self, root: Path, settings: GitSettings, timeout: float = 60,
                 log: Callable[[str], None] | None = None) -> None:
        self.root = Path(root)
        self.settings = settings
        self.timeout = timeout
        self._log = log or LocalHome().log

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
                if not self._catch_up():
                    return self._failed(SyncResult(committed, False, "git failed: could not merge "
                                                   "changes from the remote; retried next time"))
                # -u keeps the branch linked to origin, so `git status` reports it as pushed.
                self._git("push", "-q", "-u", "origin", "HEAD")
                pushed = True
            return SyncResult(committed, pushed)
        except (subprocess.SubprocessError, OSError) as exc:
            return self._failed(SyncResult(False, False, f"git failed: {exc}"))

    def pull(self) -> bool:
        """Bring in what other machines pushed (settings included) before working.

        Safe at any time: local uncommitted work is kept (autostash); on a conflict
        nothing changes. Returns False only when the remote could not be merged.
        """
        if not self.is_repository() or not self._has_remote():
            return True
        try:
            if self._catch_up():
                return True
            self._log(f"git: could not merge changes from the remote in {self.root}")
            return False
        except (subprocess.SubprocessError, OSError) as exc:
            self._log(f"git failed while pulling {self.root}: {exc}")
            return False

    def _catch_up(self) -> bool:
        """Put this machine's commits on top of what other machines pushed (rebase).

        Profiles write to separate files, so this almost never conflicts. If it does,
        the rebase is undone and nothing is lost; the push waits for a later turn.
        """
        self._register_merge_driver()
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if self._git("fetch", "-q", "origin", branch, check=False).returncode != 0:
            return True  # the remote does not have the branch yet: nothing to catch up on
        if self._git("rebase", "-q", "--autostash", "FETCH_HEAD", check=False).returncode == 0:
            return True
        self._git("rebase", "--abort", check=False)
        return False

    def _register_merge_driver(self) -> None:
        """Let Git merge the harness's YAML and Markdown files by content, and never stop on a
        generated file (this clone only, nothing committed)."""
        # Git runs drivers through a POSIX shell, also on Windows: a path with backslashes would
        # lose them, so the interpreter is given with forward slashes, quoted for that shell.
        command = f"{shlex.quote(sys.executable.replace(chr(92), '/'))} -m harness merge-file"
        self._git("config", f"merge.{self.MERGE_DRIVER}.name", "harness YAML merge", check=False)
        self._git("config", f"merge.{self.MERGE_DRIVER}.driver", f"{command} %O %A %B %P", check=False)
        # Files the engine generates (connector/: index, served instructions) are never merged:
        # either side is kept, and the engine writes them again from the content on its next run.
        self._git("config", f"merge.{self.GENERATED_DRIVER}.name", "harness generated file", check=False)
        self._git("config", f"merge.{self.GENERATED_DRIVER}.driver", "true", check=False)
        attributes = self.root / ".git" / "info" / "attributes"
        existing = attributes.read_text("utf-8") if attributes.is_file() else ""
        wanted = [f"{pattern} merge={self.MERGE_DRIVER}" for pattern in ("*.yaml", "*.md")]
        wanted += [f"{pattern} merge={self.GENERATED_DRIVER}" for pattern in self.GENERATED]  # last wins
        missing = [line for line in wanted if line not in existing]
        if missing:
            attributes.parent.mkdir(parents=True, exist_ok=True)
            attributes.write_text(existing + ("" if existing.endswith("\n") or not existing else "\n")
                                  + "\n".join(missing) + "\n", encoding="utf-8")

    def _failed(self, result: SyncResult) -> SyncResult:
        self._log(f"{result.message} ({self.root})")
        return result

    def _has_remote(self) -> bool:
        return bool(self._git("remote", check=False).stdout.strip())

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True,
                              timeout=self.timeout, check=check)
