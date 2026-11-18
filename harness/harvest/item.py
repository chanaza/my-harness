"""``Captured``: one thing found inside a tool, before it is written to the harness."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Kind(StrEnum):
    INSTRUCTION = "instruction"   # always-on instructions (e.g. CLAUDE.md)
    SKILL = "skill"               # a skill folder, or a prompt command
    AGENT = "agent"               # a sub-agent definition
    MEMORY = "memory"             # a memory document
    CONNECTION = "connection"     # an MCP server or plugin (names only, never secrets)
    NATIVE = "native"             # tool-specific settings with no portable equivalent


@dataclass
class Captured:
    """An item read from a tool.

    ``files`` holds the item's source files (relative path -> bytes); ``meta``
    holds fields the adapter already parsed. ``scope`` is ``global`` or
    ``project:<name>``.
    """

    kind: Kind
    name: str
    origin: str
    files: dict[str, bytes] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    scope: str = "global"

    @property
    def key(self) -> str:
        """Stable identity used to remember what was already captured."""
        return f"{self.kind.value}:{self.scope}:{self.name}"

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.files):
            digest.update(path.encode())
            digest.update(self.files[path])
        digest.update(repr(sorted(self.meta.items())).encode())
        return digest.hexdigest()

    def text(self, path: str) -> str:
        return self.files[path].decode("utf-8", errors="replace")
