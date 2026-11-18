"""Git storage backend: documents live in a branch of a Git repository.

Reachable from any machine with Git access (cloud sessions included). By
default it uses a separate ``transcripts`` branch of the content
repository's own remote, so transcripts never enter ``main``'s history and
the branch can be pruned or deleted on its own.

The working copy is kept under ~/.my-harness/storage/. Every write is
committed and pushed right away, so nothing waits on a session ending.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from ..local import LocalHome
from .base import Storage, StorageError
from .filesystem import FilesystemStorage
from .registry import backends


@backends.register
class GitStorage(Storage):
    backend_name = "git"

    def __init__(self, remote: str, branch: str, checkout: Path, timeout: float = 120) -> None:
        self.remote = remote
        self.branch = branch
        self.checkout = Path(checkout)
        self.timeout = timeout
        self._files = FilesystemStorage(self.checkout)
        self._ready = False

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> GitStorage:
        remote = settings.get("remote", "origin")
        if remote == "origin":
            repo = settings.get("content_repo")
            if not repo:
                raise StorageError("git backend with remote 'origin' needs the content repository")
            remote = cls._run(["git", "remote", "get-url", "origin"], Path(repo)).stdout.strip()
        branch = settings.get("branch", "transcripts")
        digest = hashlib.sha256(f"{remote}#{branch}".encode()).hexdigest()[:12]
        return cls(remote, branch, LocalHome().root / "storage" / digest)

    # --- Storage interface ------------------------------------------------------------

    def write_text(self, key: str, text: str) -> None:
        self._prepare()
        self._files.write_text(key, text)
        self._publish(f"write {key}")

    def append_text(self, key: str, text: str) -> None:
        self._prepare()
        self._files.append_text(key, text)
        self._publish(f"append {key}")

    def read_text(self, key: str) -> str:
        self._prepare()
        return self._files.read_text(key)

    def exists(self, key: str) -> bool:
        self._prepare()
        return self._files.exists(key)

    def list_keys(self, prefix: str = "") -> list[str]:
        self._prepare()
        return [k for k in self._files.list_keys(prefix) if not k.startswith(".git/")]

    def delete(self, key: str) -> None:
        self._prepare()
        self._files.delete(key)
        self._publish(f"delete {key}")

    # --- git plumbing -------------------------------------------------------------------

    def _prepare(self) -> None:
        """Clone the branch once (creating it if the remote does not have it yet), then pull."""
        if self._ready:
            return
        if not (self.checkout / ".git").is_dir():
            self.checkout.mkdir(parents=True, exist_ok=True)
            self._git("init", "-q")
            self._git("remote", "add", "origin", self.remote)
        has_branch = bool(self._git("ls-remote", "--heads", "origin", self.branch).stdout.strip())
        if has_branch:
            self._git("fetch", "-q", "--depth", "1", "origin", self.branch)
            self._git("checkout", "-q", "-B", self.branch, "FETCH_HEAD")
        elif self._git("rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0:
            self._git("checkout", "-q", "--orphan", self.branch)
        self._ready = True

    def _publish(self, message: str) -> None:
        self._git("add", "-A")
        if self._git("diff", "--cached", "--quiet", check=False).returncode != 0:
            self._git("commit", "-q", "-m", message)
            # Another machine may have pushed to the branch meanwhile: rebase onto it first.
            if self._git("fetch", "-q", "origin", self.branch, check=False).returncode == 0:
                if self._git("rebase", "-q", "FETCH_HEAD", check=False).returncode != 0:
                    self._git("rebase", "--abort", check=False)
                    raise StorageError("could not merge the remote transcripts branch")
            self._git("push", "-q", "origin", f"HEAD:refs/heads/{self.branch}")

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self._run(["git", *args], self.checkout, check, self.timeout)

    @staticmethod
    def _run(command: list[str], cwd: Path, check: bool = True,
             timeout: float = 120) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                  timeout=timeout, check=check)
        except subprocess.CalledProcessError as exc:
            raise StorageError(f"{' '.join(command)} failed: {exc.stderr.strip()}") from None
        except (OSError, subprocess.SubprocessError) as exc:
            raise StorageError(f"{' '.join(command)} failed: {exc}") from None
