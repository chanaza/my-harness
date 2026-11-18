"""``Captured``: one thing found inside a tool, before it is written to the harness."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..text import slugify


class Kind(StrEnum):
    INSTRUCTION = "instruction"   # always-on instructions (e.g. CLAUDE.md)
    SKILL = "skill"               # a skill folder, or a prompt command
    AGENT = "agent"               # a sub-agent definition
    MEMORY = "memory"             # a memory document
    CONNECTION = "connection"     # an MCP server or plugin (names only, never secrets)
    PLUGIN = "plugin"             # a whole plugin the user built (its skills, agents, commands)
    PROJECT = "project"           # a project: its instructions and knowledge files
    WORKFLOW = "workflow"         # a scheduled / repeatable task
    APP = "app"                   # an app or page built inside a tool (e.g. a claude.ai artifact)
    NATIVE = "native"             # tool-specific settings with no portable equivalent


#: Things the engine itself installs in tools (its own skills). They are the engine's,
#: never the user's content, so no adapter saves them. "<kind>:<name>".
ENGINE_OWNED: frozenset[str] = frozenset({
    "skill:harness-save",     # Claude Code: save on request
    "skill:harness-export",   # claude.ai: export automation (before v0.15)
    "skill:harness-account",  # the Claude account skill
    "workflow:harness-describe-account",              # its daily scheduled task
    "workflow:harness-request-claude-ai-export",      # export automation (before v0.15)
    "workflow:harness-download-claude-ai-export",
})


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
    def engine_owned(self) -> bool:
        return f"{self.kind.value}:{slugify(self.name)}" in ENGINE_OWNED

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
