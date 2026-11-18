"""YAML reading and comment-preserving editing.

All YAML access goes through here, so the YAML library is swappable in one place.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

__all__ = ["YAMLError", "YamlDocument", "dump", "load"]


def load(text: str) -> Any:
    """Parse YAML text into plain Python data."""
    return YAML(typ="safe", pure=True).load(text)


def dump(data: Any) -> str:
    """Serialise plain Python data to YAML text."""
    stream = StringIO()
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    yaml.dump(data, stream)
    return stream.getvalue()


class YamlDocument:
    """A YAML file edited in place, keeping its comments and key order.

    Keys are dotted paths, e.g. ``storage.transcripts.path``.
    """

    def __init__(self, path: Path, text: str | None = None) -> None:
        self.path = Path(path)
        self._yaml = YAML()  # round-trip mode
        self._yaml.preserve_quotes = True
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self.data = self._yaml.load(self.path.read_text("utf-8") if text is None else text)

    @classmethod
    def from_text(cls, path: Path, text: str) -> YamlDocument:
        """A document that will be saved to ``path`` but starts from ``text``."""
        return cls(path, text)

    def get(self, key: str) -> Any:
        node = self.data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(key)
            node = node[part]
        return node

    def set(self, key: str, value: Any, create: bool = False) -> None:
        """Set a dotted key. With ``create``, missing sections are added."""
        *parents, leaf = key.split(".")
        node = self.data
        for part in parents:
            if part not in node and create:
                node[part] = {}
            if not isinstance(node.get(part), dict):
                raise KeyError(f"{key}: '{part}' is not a section")
            node = node[part]
        node[leaf] = value

    def to_plain(self) -> Any:
        """The document as plain dicts/lists (for schema validation)."""
        return load(self.render())

    def render(self) -> str:
        stream = StringIO()
        self._yaml.dump(self.data, stream)
        return stream.getvalue()

    def save(self) -> None:
        self.path.write_text(self.render(), encoding="utf-8")
