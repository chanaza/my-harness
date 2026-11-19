"""``run``: every command the engine starts, without a window.

On Windows the engine often runs with no console of its own (a scheduled task with pythonw, or
a background job after a Claude Code turn). Each console program it then starts - every
``git`` command - would open a window of its own for a moment: the flashing command windows.
Started with CREATE_NO_WINDOW, they (and what they start, e.g. git's merge driver) run hidden.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

CREATE_NO_WINDOW = 0x08000000   # subprocess.CREATE_NO_WINDOW, which exists only on Windows


def hidden(options: dict[str, Any] | None = None) -> dict[str, Any]:
    """``options`` plus what keeps a started program from opening a window."""
    options = dict(options or {})
    if os.name == "nt":
        options["creationflags"] = options.get("creationflags", 0) | CREATE_NO_WINDOW
    return options


def run(command: list[str], **options: Any) -> subprocess.CompletedProcess:
    return subprocess.run(command, **hidden(options))
