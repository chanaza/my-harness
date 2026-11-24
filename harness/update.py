"""``Updater``: `harness update` - bring this machine up to the latest engine in one step.

  1. Install the latest engine code (skipped for a development checkout).
  2. `harness upgrade` the harness repository (new settings, migrations).
  3. Re-install every tool connection on this machine (refreshes hooks and the
     save skill) and capture once.

Steps 2 and 3 run as new processes, so they use the freshly installed code.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import process
from .local import LocalHome

ENGINE_URL = os.environ.get("HARNESS_ENGINE_URL", "git+https://github.com/chanaza/my-harness")


@dataclass
class UpdateReport:
    steps: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


class Updater:
    def __init__(self, local: LocalHome | None = None,
                 run: Callable[..., subprocess.CompletedProcess[str]] = process.run,
                 progress: Callable[[str], None] | None = None) -> None:
        self.local = local or LocalHome()
        self._run = run
        #: Told before each step starts: an update takes minutes (downloads, then a capture of
        #: every tool), and with no output it looks stuck and gets stopped half way.
        self._progress = progress or (lambda message: None)

    def update(self, engine: bool = True) -> UpdateReport:
        report = UpdateReport()
        repo = self.local.content_repo()
        if not repo:
            report.problems.append("No harness repository on this machine: run `harness setup` first.")
            return report
        if engine and not self._is_development_checkout():
            quiet = ("--user", "--quiet", "--disable-pip-version-check", "--no-warn-script-location")
            self._step(report, "engine updated", "-m", "pip", "install", *quiet, "--upgrade", ENGINE_URL)
            self._step(report, None, "-m", "pip", "install", *quiet, "--force-reinstall", "--no-deps",
                       ENGINE_URL)
        self._step(report, "harness repository upgraded", "-m", "harness", "upgrade", "--repo", str(repo))
        for tool, bindings in (self.local.settings().get("profiles") or {}).items():
            for key, profile in bindings.items():
                # Claude Code accounts are told apart by their config folder; others by an account key.
                env = {**os.environ, "CLAUDE_CONFIG_DIR": key} if tool == "claude-code" else None
                account = [] if tool == "claude-code" else ["--account-key", key]
                self._step(report, f"{profile}: connection refreshed", "-m", "harness", "install", tool,
                           "--profile", profile, "--repo", str(repo), *account, env=env)
            self._step(report, f"{tool}: captured", "-m", "harness", "harvest", tool)
        return report

    def _step(self, report: UpdateReport, label: str | None, *args: str,
              env: dict[str, str] | None = None) -> None:
        self._progress(' '.join(a for a in args[:5] if not a.startswith('--')))
        result = self._run([sys.executable, *args], capture_output=True, text=True, env=env)
        if result.returncode != 0:
            report.problems.append(f"{' '.join(args[:4])}: {(result.stderr or result.stdout).strip()}")
        elif label:
            report.steps.append(label)

    @staticmethod
    def _is_development_checkout() -> bool:
        """Running from a source checkout (pip install -e): never overwrite it with a download."""
        package = Path(__file__).resolve().parent
        return (package.parent / "pyproject.toml").is_file() and (package.parent / ".git").exists()
