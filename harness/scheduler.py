"""``Scheduler``: run a harness command periodically, for tools that have no hooks.

Windows uses Task Scheduler (schtasks); macOS and Linux use the user's crontab.
Tasks are named, so installing again replaces the previous one.
"""

from __future__ import annotations

import os
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from . import process


def background_python() -> str:
    """The interpreter to schedule: pythonw on Windows (no console window flashes)."""
    executable = Path(sys.executable)
    windowless = executable.with_name("pythonw.exe")
    return str(windowless if os.name == "nt" and windowless.is_file() else executable)


class SchedulerError(Exception):
    pass


class Scheduler(ABC):
    @abstractmethod
    def install(self, name: str, args: list[str], minutes: int) -> str:
        """Run ``python -m harness <args>`` every ``minutes``; return a description."""

    @abstractmethod
    def remove(self, name: str) -> None: ...


class WindowsTaskScheduler(Scheduler):
    FOLDER = "my-harness"

    def install(self, name: str, args: list[str], minutes: int) -> str:
        command = subprocess.list2cmdline([background_python(), "-m", "harness", *args])
        task = f"{self.FOLDER}\\{name}"
        result = process.run(["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", str(minutes),
                                 "/TN", task, "/TR", command], capture_output=True, text=True)
        if result.returncode != 0:
            raise SchedulerError(result.stderr.strip() or result.stdout.strip())
        return f"Task Scheduler: '{task}' every {minutes} minutes"

    def remove(self, name: str) -> None:
        process.run(["schtasks", "/Delete", "/F", "/TN", f"{self.FOLDER}\\{name}"],
                       capture_output=True, text=True)


class CronScheduler(Scheduler):
    MARKER = "# my-harness:"

    def install(self, name: str, args: list[str], minutes: int) -> str:
        command = " ".join([background_python(), "-m", "harness", *args])
        lines = [line for line in self._read() if not line.endswith(f"{self.MARKER}{name}")]
        lines.append(f"*/{minutes} * * * * {command} >/dev/null 2>&1 {self.MARKER}{name}")
        self._write(lines)
        return f"crontab: '{name}' every {minutes} minutes"

    def remove(self, name: str) -> None:
        self._write([line for line in self._read() if not line.endswith(f"{self.MARKER}{name}")])

    @staticmethod
    def _read() -> list[str]:
        result = process.run(["crontab", "-l"], capture_output=True, text=True)
        return result.stdout.splitlines() if result.returncode == 0 else []

    @staticmethod
    def _write(lines: list[str]) -> None:
        result = process.run(["crontab", "-"], input="\n".join(lines) + "\n",
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise SchedulerError(result.stderr.strip())


def system_scheduler() -> Scheduler:
    return WindowsTaskScheduler() if os.name == "nt" else CronScheduler()
