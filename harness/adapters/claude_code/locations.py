"""Where Claude Code keeps things on this machine."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ClaudeCodeLocations:
    """``config_dir`` is ~/.claude (or $CLAUDE_CONFIG_DIR, used to run several accounts).

    ``project_dir`` is the folder a session runs in, when there is one.
    """

    config_dir: Path
    user_config_file: Path
    project_dir: Path | None = None

    @classmethod
    def detect(cls, project_dir: Path | None = None) -> ClaudeCodeLocations:
        custom = os.environ.get("CLAUDE_CONFIG_DIR")
        if custom:
            config_dir = Path(custom).expanduser()
            user_config = config_dir / ".claude.json"
        else:
            config_dir = Path.home() / ".claude"
            user_config = Path.home() / ".claude.json"
        return cls(config_dir, user_config, Path(project_dir) if project_dir else None)

    def for_project(self, project_dir: Path | None) -> ClaudeCodeLocations:
        return ClaudeCodeLocations(self.config_dir, self.user_config_file,
                                   Path(project_dir) if project_dir else None)

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def key(self) -> str:
        """Identifies this Claude Code installation (one per account) on the machine."""
        return str(self.config_dir.resolve())
