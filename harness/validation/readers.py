"""How to extract the structured part of a file for schema validation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .. import yaml_io


class ReadError(Exception):
    """The file's structured part could not be read."""


class FileReader(ABC):
    @abstractmethod
    def read(self, path: Path) -> object:
        """Return the file's structured data. Raise ReadError on failure."""


class YamlReader(FileReader):
    """The whole file is YAML."""

    def read(self, path: Path) -> object:
        try:
            return yaml_io.load(path.read_text("utf-8"))
        except yaml_io.YAMLError as exc:
            raise ReadError(f"invalid YAML: {exc}") from None


class FrontmatterReader(FileReader):
    """A Markdown file whose metadata is a ``---``-delimited YAML block at the top."""

    DELIMITER = "---"

    def read(self, path: Path) -> object:
        text = path.read_text("utf-8")
        if not text.startswith(self.DELIMITER):
            raise ReadError(f"missing YAML frontmatter (the file must start with '{self.DELIMITER}')")
        head, separator, _ = text[len(self.DELIMITER):].partition(f"\n{self.DELIMITER}")
        if not separator:
            raise ReadError(f"frontmatter is not closed with '{self.DELIMITER}'")
        try:
            return yaml_io.load(head)
        except yaml_io.YAMLError as exc:
            raise ReadError(f"invalid YAML in frontmatter: {exc}") from None
