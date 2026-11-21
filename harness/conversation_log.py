"""``ConversationLog``: one readable, word-for-word ``log.md`` per conversation (engine).

To continue a conversation anywhere: its latest ``summary.md`` plus its ``log.md`` after it.
The log is the same for every tool. An adapter only turns its tool's raw record into
``Reply`` objects (e.g. Claude Code: its transcript file); the connector inbox does the same
for the exchanges a tool's skill sends. Everything else - the form, the order, marking
missing replies, where the file lives - is here, once.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from . import yaml_io
from .secrets import SecretGuard
from .sessions import SessionRecord

LOG_FILE = "log.md"
REPLIES_FOLDER = "replies"   # replies that arrive one by one (connector) are kept here first
INTRO = "Word for word, reply by reply. To continue: the latest summary.md plus this log after it.\n"


@dataclass
class Reply:
    """One reply: what the user said, and everything the assistant said and did."""

    number: int
    at: str = ""
    user: list[str] = field(default_factory=list)
    assistant: list[str] = field(default_factory=list)

    def render(self) -> str:
        when = f" · {self.at}" if self.at else ""
        user = "\n\n".join(self.user).strip() or "(no message)"
        assistant = "\n\n".join(self.assistant).strip() or "(no reply)"
        return f"### Reply {self.number}{when}\n\n## User\n\n{user}\n\n## Assistant\n\n{assistant}\n"

    @classmethod
    def from_exchange(cls, number: int, at: str, text: str) -> Reply:
        """An exchange as a tool's skill sends it: '## User' ... '## Assistant' ..."""
        parts = re.split(r"^##\s+(User|Assistant)\s*$", text, flags=re.MULTILINE)
        found = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
        return cls(number, at, [found.get("User", "")], [found.get("Assistant", "")])

    @staticmethod
    def action(tool: str, what: str = "") -> str:
        """How an action the assistant took reads in the log (one line)."""
        what = " ".join(str(what).split())[:160]
        return f"- *{tool}: {what}*" if what else f"- *{tool}*"


class ConversationLog:
    def __init__(self, record: SessionRecord) -> None:
        self.record = record
        self.path = record.folder / LOG_FILE
        self.replies_folder = record.folder / REPLIES_FOLDER

    def write(self, title: str, replies: Iterable[Reply]) -> None:
        """The whole log from a complete source (e.g. a transcript file)."""
        self.record.folder.mkdir(parents=True, exist_ok=True)
        # the readable log is on the main branch: no secret value in it, whatever was typed
        self.path.write_text(SecretGuard().clean_text(self.render(title, replies)).text, encoding="utf-8")

    def add(self, title: str, reply: Reply) -> int:
        """One reply that arrived on its own (in any order; sent twice: the newest is kept).
        Returns the highest reply number so far."""
        self.replies_folder.mkdir(parents=True, exist_ok=True)
        (self.replies_folder / f"{reply.number:05d}.yaml").write_text(
            SecretGuard().clean_text(yaml_io.dump(asdict(reply))).text, encoding="utf-8")
        replies = [Reply(**self._load(p)) for p in sorted(self.replies_folder.glob("*.yaml"))]
        self.write(title, replies)
        return max(r.number for r in replies)

    def missing(self) -> list[int]:
        """Reply numbers that never arrived (only for replies that arrive one by one)."""
        numbers = sorted(int(p.stem) for p in self.replies_folder.glob("*.yaml")) \
            if self.replies_folder.is_dir() else []
        return sorted(set(range(1, numbers[-1] + 1)) - set(numbers)) if numbers else []

    @staticmethod
    def render(title: str, replies: Iterable[Reply]) -> str:
        """The log: a title, then each reply in order; missing numbers are marked, so a gap
        is never silent."""
        parts = [f"# {title}\n\n{INTRO}"]
        expected = 1
        for reply in sorted(replies, key=lambda r: r.number):
            if reply.number > expected:
                gap = (f"Replies {expected}-{reply.number - 1} were" if reply.number - 1 > expected
                       else f"Reply {expected} was")
                parts.append(f"\n> {gap} not received.\n")
            parts.append("\n---\n\n" + reply.render())
            expected = reply.number + 1
        return "".join(parts)

    @staticmethod
    def _load(path: Any) -> dict[str, Any]:
        return dict(yaml_io.load(path.read_text("utf-8")) or {})
