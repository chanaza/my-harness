"""harness.config.yaml: reading it (``HarnessConfig``) and changing it (``ConfigFile``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatch
from importlib import resources
from pathlib import Path
from typing import Any

from . import yaml_io
from .schemas import SchemaRegistry
from .yaml_io import YamlDocument, YAMLError

CONFIG_TEMPLATE = "harness.config.yaml"

#: Settings removed from the engine, as dotted-key patterns. `harness upgrade` drops them.
OBSOLETE_SETTINGS: tuple[str, ...] = (
    # v0.3: per-session records simplified to meta + summary + transcript.
    "capture.live_log_*",
    "capture.tail_exchanges",
    "capture.transcript_on_checkpoint",
    "storage.live_logs.*",
    "storage_by_profile.*.live_logs.*",
    # v0.14: the schedule is set per adapter type in capture_modes.
    "capture.poll_minutes",
    # v0.15: claude.ai is captured through the harness-account skill, not a scheduled export.
    "claude_ai.export_every_days",
    "claude_ai.download_after_hours",
    "claude_ai.inbox_folder",
    "claude_ai.drive_folder",
)


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class CaptureSettings:
    context_window_tokens: int
    background: bool = True


@dataclass(frozen=True)
class CaptureMode:
    """How one adapter type is captured: push, scheduled (every N minutes) or on_demand."""

    mode: str
    every_minutes: int = 30

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
class ClaudeAiSettings:
    watch_folder: str = "~/Downloads"
    file_pattern: str = "data-*.zip"
    archive_exports: bool = True
    skills_page: str = "https://claude.ai/new#customize/skills/new/upload"
    skill_folder: str = "~/Downloads"


@dataclass(frozen=True)
class ConnectorSettings:
    """The harness connector: tools without direct access save through it into inbox/."""
    save_every: str = "reply"          # reply | meaningful | request
    run_every_minutes: int = 30        # how often the inbox is processed at most


@dataclass(frozen=True)
class MondaySettings:
    endpoint: str = "https://api.monday.com/v2"
    api_version: str = "dev"
    runs_per_agent: int = 50


@dataclass(frozen=True)
class GitSettings:
    auto_commit: bool
    auto_push: bool
    push_every_turn: bool = True


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

    def capture_mode(self, tool: str, default: str = "on_demand") -> CaptureMode:
        values = (self.data.get("capture_modes") or {}).get(tool) or {"mode": default}
        return _section(CaptureMode, values)

    @property
    def checkpoints(self) -> CheckpointSettings:
        return _section(CheckpointSettings, self.data["checkpoints"])

    @property
    def connector(self) -> ConnectorSettings:
        return _section(ConnectorSettings, self.data.get("connector") or {})

    @property
    def claude_ai(self) -> ClaudeAiSettings:
        return _section(ClaudeAiSettings, self.data.get("claude_ai") or {})

    @property
    def monday(self) -> MondaySettings:
        return _section(MondaySettings, self.data.get("monday") or {})

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

    def obsolete_settings(self) -> list[str]:
        """Settings in this file that the engine no longer has."""
        return [key for key in _leaves(self._open().to_plain())
                if any(fnmatch(key, pattern) for pattern in OBSOLETE_SETTINGS)]

    def missing_settings(self) -> list[str]:
        """Settings the engine template has and this file does not (fixed by ``upgrade``)."""
        own = _leaves(self._open().to_plain())
        return [key for key in _leaves(yaml_io.load(template_config_text())) if key not in own
                and not any(key.startswith(f"{k}.") for k in own)]

    def upgrade(self) -> tuple[list[str], list[str]]:
        """Rewrite the file from the current engine template, keeping every value already set.

        New settings appear with their defaults and explanatory comments; obsolete
        settings are dropped. Returns (added, removed).
        """
        added, removed = self.missing_settings(), self.obsolete_settings()
        document = YamlDocument.from_text(self.path, template_config_text())
        for key, value in _leaves(self._open().to_plain()).items():
            if key not in removed:
                document.set(key, value, create=True)
        self._validated(document.to_plain())
        document.save()
        return added, removed

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
