"""harness.config.yaml: reading it (``HarnessConfig``) and changing it (``ConfigFile``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schemas import SchemaRegistry
from .yaml_io import YamlDocument, YAMLError


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class HarnessConfig:
    """A validated, read-only view of harness.config.yaml.

    ``data`` keeps the full file, so a new setting can be read before a
    typed property is added for it.
    """

    data: Mapping[str, Any]

    @property
    def working_language(self) -> str:
        return self.data["language"]["working"]

    @property
    def preserve_original(self) -> bool:
        return self.data["language"]["preserve_original"]

    @property
    def live_log_threshold_percent(self) -> int:
        return self.data["capture"]["live_log_threshold_percent"]

    @property
    def live_log_fallback_messages(self) -> int:
        return self.data["capture"]["live_log_fallback_messages"]

    @property
    def max_inline_asset_bytes(self) -> int:
        return int(self.data["assets"]["max_inline_size_mb"] * 1024 * 1024)

    @property
    def tools(self) -> list[str]:
        return list(self.data["tools"])

    def storage_settings(self, name: str) -> dict[str, Any]:
        """Settings of a named storage area, e.g. 'transcripts'."""
        try:
            return dict(self.data["storage"][name])
        except KeyError:
            raise ConfigError(f"No storage area named {name!r} in the configuration") from None


class ConfigFile:
    """The configuration file on disk. Every write is validated first."""

    SCHEMA = "config"

    def __init__(self, path: Path, schemas: SchemaRegistry | None = None) -> None:
        self.path = Path(path)
        self.schemas = schemas or SchemaRegistry.bundled()

    def load(self) -> HarnessConfig:
        return HarnessConfig(self._validated(self._open().to_plain()))

    def get(self, key: str) -> Any:
        try:
            return self._open().get(key)
        except KeyError:
            raise ConfigError(f"No setting {key!r}") from None

    def update(self, changes: Mapping[str, Any]) -> None:
        """Apply ``{dotted.key: value}`` changes; nothing is written if the result is invalid."""
        document = self._open()
        for key, value in changes.items():
            try:
                document.set(key, value)
            except KeyError as exc:
                raise ConfigError(f"Cannot set {key!r}: {exc}") from None
        self._validated(document.to_plain())
        document.save()

    def _open(self) -> YamlDocument:
        if not self.path.is_file():
            raise ConfigError(f"{self.path} not found. Is this a harness content repository?")
        try:
            return YamlDocument(self.path)
        except YAMLError as exc:
            raise ConfigError(f"{self.path} is not valid YAML: {exc}") from None

    def _validated(self, data: Any) -> Mapping[str, Any]:
        errors = self.schemas.errors(self.SCHEMA, data)
        if errors:
            raise ConfigError(f"{self.path.name} would be invalid:\n  " + "\n  ".join(errors))
        return data
