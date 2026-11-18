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
        meta = yaml_io.load(head) or {}
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
