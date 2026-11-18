"""harness.config.yaml: reading it (``HarnessConfig``) and changing it (``ConfigFile``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from . import yaml_io
from .schemas import SchemaRegistry
from .yaml_io import YamlDocument, YAMLError

CONFIG_TEMPLATE = "harness.config.yaml"


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class CaptureSettings:
    live_log_threshold_percent: int
    live_log_fallback_messages: int
    live_log_max_chars: int
    context_window_tokens: int
    tail_exchanges: int = 10
    transcript_on_checkpoint: bool = True


@dataclass(frozen=True)
class CheckpointSettings:
    """When the rolling session summary is refreshed (see ``CheckpointPolicy``)."""

    enabled: bool
    every_user_messages: int
    every_context_percent: int
    force_at_context_percent: int
    on_compaction: bool
    summary_max_words: int


@dataclass(frozen=True)
class GitSettings:
    auto_commit: bool
    auto_push: bool


def _section(cls: type, values: Mapping[str, Any]) -> Any:
    """Build a settings dataclass from a config section, ignoring unknown keys."""
    names = cls.__dataclass_fields__
    return cls(**{k: v for k, v in values.items() if k in names})


@dataclass(frozen=True)
class HarnessConfig:
    """A validated, read-only view of harness.config.yaml.

    Settings missing from an older file fall back to the engine template's
    defaults, so a repository keeps working before `harness upgrade` runs.
    ``data`` keeps the merged file, so a new setting can be read before a
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
    def capture(self) -> CaptureSettings:
        return _section(CaptureSettings, self.data["capture"])

    @property
    def checkpoints(self) -> CheckpointSettings:
        return _section(CheckpointSettings, self.data["checkpoints"])

    @property
    def git(self) -> GitSettings:
        return _section(GitSettings, self.data["git"])

    @property
    def harvest_enabled(self) -> bool:
        return bool(self.data["harvest"]["enabled"])

    @property
    def harvest_exclude(self) -> list[str]:
        return list(self.data["harvest"].get("exclude") or [])

    @property
    def live_log_threshold_percent(self) -> int:
        return self.capture.live_log_threshold_percent

    @property
    def max_inline_asset_bytes(self) -> int:
        return int(self.data["assets"]["max_inline_size_mb"] * 1024 * 1024)

    @property
    def tools(self) -> list[str]:
        return list(self.data["tools"])

    def storage_settings(self, name: str, profile: str | None = None) -> dict[str, Any]:
        """Settings of a named storage area, e.g. 'transcripts'.

        A ``storage_by_profile.<profile>.<name>`` block, when present, wins.
        """
        override = ((self.data.get("storage_by_profile") or {}).get(profile) or {}).get(name)
        if override:
            return dict(override)
        try:
            return dict(self.data["storage"][name])
        except KeyError:
            raise ConfigError(f"No storage area named {name!r} in the configuration") from None


def template_config_text() -> str:
    """The configuration template shipped with the engine (defaults + comments)."""
    return resources.files("harness.templates").joinpath("content_repo", CONFIG_TEMPLATE).read_text("utf-8")


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _leaves(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested settings to ``{dotted.key: value}``."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, Mapping) and value:
            flat.update(_leaves(value, f"{dotted}."))
        else:
            flat[dotted] = value
    return flat


class ConfigFile:
    """The configuration file on disk. Every write is validated first."""

    SCHEMA = "config"

    def __init__(self, path: Path, schemas: SchemaRegistry | None = None) -> None:
        self.path = Path(path)
        self.schemas = schemas or SchemaRegistry.bundled()

    def load(self) -> HarnessConfig:
        own = self._validated(self._open().to_plain())
        return HarnessConfig(_deep_merge(yaml_io.load(template_config_text()), own))

    def missing_settings(self) -> list[str]:
        """Settings the engine template has and this file does not (fixed by ``upgrade``)."""
        own = _leaves(self._open().to_plain())
        return [key for key in _leaves(yaml_io.load(template_config_text())) if key not in own
                and not any(key.startswith(f"{k}.") for k in own)]

    def upgrade(self) -> list[str]:
        """Rewrite the file from the current engine template, keeping every value already set.

        New settings appear with their defaults and explanatory comments.
        Returns the settings that were added.
        """
        added = self.missing_settings()
        document = YamlDocument.from_text(self.path, template_config_text())
        for key, value in _leaves(self._open().to_plain()).items():
            document.set(key, value, create=True)
        self._validated(document.to_plain())
        document.save()
        return added

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
                document.set(key, value, create=True)
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
