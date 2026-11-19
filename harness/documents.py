"""Markdown documents with YAML frontmatter: the format of most content files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import yaml_io

DELIMITER = "---"


@dataclass
class MarkdownDocument:
    """``---\\n<yaml>\\n---\\n<body>``."""

    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""

    @classmethod
    def parse(cls, text: str) -> MarkdownDocument:
        """Split frontmatter from body. Text without frontmatter is all body."""
        if not text.startswith(DELIMITER):
            return cls({}, text)
        head, separator, body = text[len(DELIMITER):].partition(f"\n{DELIMITER}")
        if not separator:
            return cls({}, text)
        try:
            meta = yaml_io.load(head) or {}
        except Exception:  # noqa: BLE001 - tools accept loose front matter; so does the harness
            meta = _loose_front_matter(head)
        return cls(dict(meta) if isinstance(meta, dict) else {}, body.lstrip("\n"))

    @classmethod
    def read(cls, path: Path) -> MarkdownDocument:
        return cls.parse(Path(path).read_text("utf-8"))

    def render(self) -> str:
        if not self.meta:
            return self.body
        return f"{DELIMITER}\n{yaml_io.dump(self.meta)}{DELIMITER}\n\n{self.body.rstrip()}\n"

    def write(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8")


def _loose_front_matter(head: str) -> dict[str, str]:
    """Front matter as tools write it when it is not strict YAML (e.g. a description with an
    unquoted ': '): each top-level `key: value` line, the value taken as plain text."""
    meta: dict[str, str] = {}
    key = None
    for line in head.splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            meta[key] = value.strip()
        elif key and line.strip():
            meta[key] = f"{meta[key]} {line.strip()}".strip()
    return meta
