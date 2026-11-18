"""Where the Claude desktop app keeps Cowork data, and which accounts it holds."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

SESSIONS_FOLDER = "local-agent-mode-sessions"
CODE_SESSIONS_FOLDER = "claude-code-sessions"  # Claude Code inside the desktop app
SCHEDULED_TASKS_FILE = "scheduled-tasks.json"
SKILLS_FOLDER = "skills-plugin"
INTERNAL = frozenset({SKILLS_FOLDER})


def app_data_dir() -> Path:
    """The Claude desktop app's data folder on this operating system."""
    custom = os.environ.get("CLAUDE_APP_DATA_DIR")
    if custom:
        return Path(custom).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude"
    return Path.home() / ".config" / "Claude"


@dataclass(frozen=True)
class CoworkAccount:
    """One signed-in account. Its data sits in <sessions>/<a>/<b>/, its skills in
    <sessions>/skills-plugin/<b>/<a>/. ``key`` does not depend on that order."""

    first: str
    second: str
    folder: Path
    skills_folder: Path
    code_folder: Path | None = None

    @property
    def key(self) -> str:
        return "+".join(sorted((self.first, self.second)))

    @property
    def short(self) -> str:
        """A short label to tell accounts apart (the folder name's first characters)."""
        return self.first[:8]

    def session_folders(self) -> list[Path]:
        """Folders of individual Cowork conversations."""
        return sorted(p for p in self.folder.iterdir() if p.is_dir() and not p.name.startswith(".")
                      and p.name not in ("agent", "rpm")
                      and ((p / "audit.jsonl").is_file() or (p / ".claude").is_dir()))

    def agent_folders(self) -> list[Path]:
        """Folders of the account's persistent agents (each keeps its own conversation)."""
        agent = self.folder / "agent"
        return sorted(p for p in agent.iterdir() if p.is_dir() and p.name != "memory") \
            if agent.is_dir() else []

    @property
    def memory_folder(self) -> Path:
        return self.folder / "agent" / "memory"

    def scheduled_task_files(self) -> list[Path]:
        """Scheduled tasks of this account, in Cowork and in the app's Claude Code."""
        candidates = [self.folder / SCHEDULED_TASKS_FILE]
        if self.code_folder:
            candidates.append(self.code_folder / SCHEDULED_TASKS_FILE)
        return [p for p in candidates if p.is_file()]

    def plugin_folders(self) -> list[Path]:
        rpm = self.folder / "rpm"
        return sorted(p for p in rpm.iterdir() if p.is_dir()) if rpm.is_dir() else []


@dataclass(frozen=True)
class CoworkLocations:
    root: Path

    @classmethod
    def detect(cls) -> CoworkLocations:
        return cls(app_data_dir())

    @property
    def sessions_root(self) -> Path:
        return self.root / SESSIONS_FOLDER

    def accounts(self) -> list[CoworkAccount]:
        found = []
        if not self.sessions_root.is_dir():
            return found
        for first in sorted(self.sessions_root.iterdir()):
            if not first.is_dir() or first.name in INTERNAL or first.name.startswith("."):
                continue
            for second in sorted(p for p in first.iterdir() if p.is_dir()):
                skills = self.sessions_root / SKILLS_FOLDER / second.name / first.name
                code = self.root / CODE_SESSIONS_FOLDER / first.name / second.name
                found.append(CoworkAccount(first.name, second.name, second, skills, code))
        return found

    def account(self, key: str) -> CoworkAccount | None:
        return next((a for a in self.accounts() if a.key == key), None)
