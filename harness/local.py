"""Per-machine data that does not belong in the content repository.

Lives in ``~/.my-harness`` (override with the HARNESS_HOME environment variable):

  settings.yaml   which content repository this machine writes to
  state/          per-session counters and harvest fingerprints
  logs/           hook errors (hooks never interrupt the tool)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from . import yaml_io

HOME_ENV = "HARNESS_HOME"
REPO_ENV = "HARNESS_REPO"


class LocalHome:
    def __init__(self, root: Path | None = None) -> None:
        default = Path(os.environ.get(HOME_ENV) or Path.home() / ".my-harness")
        self.root = Path(root) if root else default

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.yaml"

    def settings(self) -> dict[str, Any]:
        if not self.settings_path.is_file():
            return {}
        return dict(yaml_io.load(self.settings_path.read_text("utf-8")) or {})

    def save_settings(self, **values: Any) -> None:
        settings = self.settings() | values
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(yaml_io.dump(settings), encoding="utf-8")

    def content_repo(self) -> Path | None:
        """The content repository: $HARNESS_REPO, else settings.yaml."""
        value = os.environ.get(REPO_ENV) or self.settings().get("content_repo")
        return Path(value).expanduser() if value else None

    def rename_profile(self, old: str, new: str) -> None:
        """Re-point this machine's tool bindings and state from ``old`` to ``new``."""
        settings = self.settings()
        for bindings in (settings.get("profiles") or {}).values():
            for key, value in list(bindings.items()):
                if value == old:
                    bindings[key] = new
        if settings:
            self.save_settings(**settings)
        for area in ("sessions", "profiles", "harvest"):
            for suffix in ("", ".json"):
                source = self.root / "state" / area / f"{old}{suffix}"
                if source.exists():
                    source.rename(self.root / "state" / area / f"{new}{suffix}")

    def state(self, *parts: str) -> StateFile:
        return StateFile(self.root.joinpath("state", *parts).with_suffix(".json"))

    @property
    def log_path(self) -> Path:
        return self.root / "logs" / "harness.log"

    def recent_problems(self, limit: int = 10) -> list[str]:
        """The last logged problems (first line of each entry)."""
        if not self.log_path.is_file():
            return []
        lines = self.log_path.read_text("utf-8", errors="replace").splitlines()
        entries = [line for line in lines if line[:4].isdigit()]  # entries start with a timestamp
        return entries[-limit:]

    def log(self, message: str) -> None:
        path = self.log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


class StateFile:
    """A small JSON document of counters and fingerprints."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = (
            json.loads(path.read_text("utf-8")) if path.is_file() else {}
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
