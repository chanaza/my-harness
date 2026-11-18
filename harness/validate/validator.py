"""Check that a content repository follows the engine's rules.

Each rule maps a glob inside the content repository to a schema and says
how to read the file (plain YAML, or YAML frontmatter at the top of a
Markdown file). Adding a new content type = adding one Rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from ..config import ConfigError, load_config
from ..layout import CONFIG_FILENAME, CONNECTIONS_FILE
from ..schema_loader import schema_errors


def read_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text("utf-8"))


def read_frontmatter(path: Path) -> object:
    """Parse the ``---``-delimited YAML block at the top of a Markdown file."""
    text = path.read_text("utf-8")
    if not text.startswith("---"):
        raise ValueError("missing YAML frontmatter (the file must start with '---')")
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        raise ValueError("frontmatter is not closed with '---'")
    return yaml.safe_load(parts[0][3:])


@dataclass(frozen=True)
class Rule:
    pattern: str
    schema: str
    reader: Callable[[Path], object] = read_yaml
    exclude_names: tuple[str, ...] = ("README.md",)


RULES: tuple[Rule, ...] = (
    Rule(CONFIG_FILENAME, "config"),
    Rule(CONNECTIONS_FILE, "connections"),
    Rule("core/skills/*/SKILL.md", "skill", read_frontmatter),
    Rule("core/agents/*.yaml", "agent"),
    Rule("core/workflows/*.yaml", "workflow"),
    Rule("memory/**/*.md", "memory", read_frontmatter),
    Rule("apps/*/app.yaml", "app"),
    Rule("apps/*/schema/*.yaml", "table"),
    Rule("apps/*/workflows/*.yaml", "workflow"),
    Rule("apps/*/data.yaml", "data_pointer"),
    Rule("assets/*/asset.yaml", "asset"),
    Rule("sessions/*/*/meta.yaml", "session_meta"),
)


@dataclass
class Report:
    checked: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def validate_repo(root: Path) -> Report:
    """Validate every known file in the content repository at ``root``."""
    root = Path(root)
    report = Report()

    try:
        config = load_config(root)
    except ConfigError as exc:
        report.problems.append(str(exc))
        return report

    for rule in RULES:
        for path in sorted(root.glob(rule.pattern)):
            if not path.is_file() or path.name in rule.exclude_names:
                continue
            report.checked += 1
            rel = path.relative_to(root).as_posix()
            try:
                data = rule.reader(path)
            except (ValueError, yaml.YAMLError) as exc:
                report.problems.append(f"{rel}: {exc}")
                continue
            report.problems.extend(f"{rel}: {msg}" for msg in schema_errors(rule.schema, data))

    _check_asset_sizes(root, config.max_inline_asset_bytes, report)
    return report


def _check_asset_sizes(root: Path, limit: int, report: Report) -> None:
    """Files above the inline limit must live outside Git (see asset.yaml 'url')."""
    assets = root / "assets"
    if not assets.is_dir():
        return
    for path in assets.rglob("*"):
        if path.is_file() and path.stat().st_size > limit:
            mb = path.stat().st_size / (1024 * 1024)
            report.problems.append(
                f"{path.relative_to(root).as_posix()}: {mb:.1f} MB exceeds the inline limit; "
                "store it externally and reference it from asset.yaml"
            )
