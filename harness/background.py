"""Running work after a hook has returned, so the user never waits for it.

``spawn_detached`` starts ``python -m harness ...`` as an independent process
(Windows and POSIX). ``ProcessLock`` keeps two background jobs of the same
kind from running at once; the next turn catches up on anything skipped.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .process import CREATE_NO_WINDOW


def spawn_detached(args: list[str], stdin_text: str) -> None:
    """Run ``python -m harness <args>`` in the background, fed ``stdin_text``."""
    options: dict = {"stdin": subprocess.PIPE, "stdout": subprocess.DEVNULL,
                     "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        # No window, and a hidden console that what it starts (git) inherits: nothing flashes.
        options["creationflags"] = CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    process = subprocess.Popen([sys.executable, "-m", "harness", *args], **options)
    process.stdin.write(stdin_text.encode("utf-8"))
    process.stdin.close()


class ProcessLock:
    """A lock file. A lock older than ``stale_after`` seconds is considered abandoned."""

    def __init__(self, path: Path, wait: float = 30, stale_after: float = 600) -> None:
        self.path = Path(path)
        self.wait = wait
        self.stale_after = stale_after
        self.acquired = False

    def __enter__(self) -> ProcessLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                self.acquired = True
                return self
            except FileExistsError:
                if time.time() - self._age_base() > self.stale_after:
                    self.path.unlink(missing_ok=True)
                    continue
                if time.monotonic() >= deadline:
                    return self  # not acquired: the caller skips its work
                time.sleep(0.2)

    def __exit__(self, *exc: object) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)

    def _age_base(self) -> float:
        try:
            return self.path.stat().st_mtime
        except FileNotFoundError:
            return time.time()
