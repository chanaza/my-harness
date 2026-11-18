"""Read and validate a content repository's harness.config.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .layout import CONFIG_FILENAME
from .schema_loader import schema_errors


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class HarnessConfig:
    """Typed view over harness.config.yaml.

    ``raw`` keeps the full parsed file so that new settings can be read
    before a typed attribute is added for them.
    """

    root: Path
    raw: dict[str, Any]

    @property
    def working_language(self) -> str:
        return self.raw["language"]["working"]

    @property
    def preserve_original(self) -> bool:
        return self.raw["language"]["preserve_original"]

    @property
    def live_log_threshold_percent(self) -> int:
        return self.raw["capture"]["live_log_threshold_percent"]

    @property
    def live_log_fallback_messages(self) -> int:
        return self.raw["capture"]["live_log_fallback_messages"]

    @property
    def max_inline_asset_bytes(self) -> int:
        return int(self.raw["assets"]["max_inline_size_mb"] * 1024 * 1024)

    @property
    def tools(self) -> list[str]:
        return list(self.raw["tools"])

    def storage_settings(self, name: str) -> dict[str, Any]:
        """Settings of a named storage area (e.g. 'transcripts')."""
        try:
            return dict(self.raw["storage"][name])
        except KeyError as exc:
            raise ConfigError(f"No storage area named '{name}' in {CONFIG_FILENAME}") from exc


def load_config(root: Path) -> HarnessConfig:
    """Load the configuration of the content repository at ``root``."""
    path = Path(root) / CONFIG_FILENAME
    if not path.is_file():
        raise ConfigError(f"{path} not found. Is this a harness content repository?")
    try:
        data = yaml.safe_load(path.read_text("utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    errors = schema_errors("config", data)
    if errors:
        raise ConfigError(f"{path} is invalid:\n  " + "\n  ".join(errors))
    return HarnessConfig(root=Path(root), raw=data)
