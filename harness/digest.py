"""``SummaryDigest``: a checkpoint has fixed sections, in two groups.

Session sections stay in sessions/<profile>/<id>/summary.md:
  Goal, Decisions, Current state, Open thread

Harness sections are written only where they belong (not repeated in the summary):
  Standing instructions  -> core/instructions/<profile>/standing-instructions.md
                            (one block per session; your own words, so no approval loop)
  Preferences learned    -> memory/<profile>-preferences-<session>.md
  Connections in use     -> core/connections.yaml (names and purpose only)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .documents import MarkdownDocument
from .harvest import Captured, Kind
from .harvest.writers import ConnectionWriter
from .memory import MemoryStore
from .profiles import ProfileError, ProfileRegistry
from .provenance import Origin, Provenance
from .repo import ContentRepo
from .sessions import SessionRecord
from .text import slugify

SESSION_SECTIONS = ("Goal", "Decisions", "Current state", "Open thread")
HARNESS_SECTIONS = ("Standing instructions", "Preferences learned", "Connections in use")
#: The sections a checkpoint is asked to contain, in order.
SECTIONS = SESSION_SECTIONS + HARNESS_SECTIONS
#: What each section means. The one definition every tool is given (Claude Code checkpoints,
#: the account skill for claude.ai and Cowork, ...), so summaries read the same everywhere.
SECTION_MEANINGS = {
    "Goal": "what the user is trying to achieve",
    "Decisions": "what was decided, and why when it matters",
    "Current state": "what exists and works now",
    "Open thread": "what is in progress right now and what you are waiting for from the user",
    "Standing instructions": "rules the user gave that should apply to future work, in their words",
    "Preferences learned": "how the user likes to work",
    "Connections in use": "one line per connector/MCP server available to you here "
                          "('- name: purpose'), names only",
}


def summary_request(max_words: int, language: str) -> str:
    """The instruction for writing a summary in the harness's language, for any tool."""
    sections = "\n".join(f"## {s}" for s in SECTIONS)
    meanings = " ".join(f"'{s}' = {SECTION_MEANINGS[s]}." for s in SECTIONS)
    return (f"Write a summary of this WHOLE conversation (not only the latest part) so that a new "
            f"session in any tool could continue from exactly this point, using exactly these "
            f"Markdown sections:\n\n{sections}\n\n{meanings} Write 'None' in an empty section. "
            f"At most {max_words} words, in '{language}'.")


EMPTY = re.compile(r"^\s*(-\s*)?(none|n/a|—|-)?\s*\.?\s*$", re.IGNORECASE)


def split_sections(text: str) -> dict[str, str]:
    """``## Heading`` blocks of a Markdown text, keyed by heading."""
    sections: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1)
            sections[current] = ""
        elif current:
            sections[current] += line + "\n"
    return {k: v.strip() for k, v in sections.items()}


def session_part(text: str) -> str:
    """The summary without the harness sections (those live in their own places)."""
    sections = split_sections(text)
    if not sections:
        return text
    kept = [f"## {name}\n\n{body}" for name, body in sections.items() if name not in HARNESS_SECTIONS]
    return "\n\n".join(kept) + "\n"


@dataclass
class DigestResult:
    written: list[str] = field(default_factory=list)


class SummaryDigest:
    def __init__(self, repo: ContentRepo, session: SessionRecord) -> None:
        self.repo = repo
        self.session = session
        self.origin = Origin.now(session.profile, session.native_id)

    def apply(self, summary: str) -> DigestResult:
        result = DigestResult()
        sections = split_sections(summary)
        if self._has_content(sections.get("Standing instructions")):
            result.written.append(self._standing_instructions(sections["Standing instructions"]))
        if self._has_content(sections.get("Preferences learned")):
            result.written.append(self._preferences(sections["Preferences learned"]))
        if self._has_content(sections.get("Connections in use")):
            result.written += self._connections(sections["Connections in use"])
        return result

    @staticmethod
    def _has_content(text: str | None) -> bool:
        return bool(text) and not EMPTY.match(text)

    def _standing_instructions(self, text: str) -> str:
        path = self.repo.path("core", "instructions", self.session.profile, "standing-instructions.md")
        document = MarkdownDocument.read(path) if path.is_file() else MarkdownDocument(
            {"scope": "global"},
            "Instructions the user gave in conversations, kept for every future session.\n")
        blocks = split_sections(document.body)
        blocks[f"Session {self.session.native_id}"] = text
        intro = document.body.split("\n## ", 1)[0].strip()
        document.body = intro + "\n\n" + "\n\n".join(f"## {k}\n\n{v}" for k, v in blocks.items()) + "\n"
        document.meta["provenance"] = Provenance.updated(document.meta.get("provenance"), self.origin)
        document.write(path)
        return path.relative_to(self.repo.root).as_posix()

    def _preferences(self, text: str) -> str:
        entry = slugify(f"{self.session.profile}-preferences-{self.session.id}")
        result = MemoryStore(self.repo).put(entry, text, self.origin, kind="preference",
                                            subject="Preferences learned in conversation")
        return result.path.relative_to(self.repo.root).as_posix()

    def _connections(self, text: str) -> list[str]:
        try:
            tool = ProfileRegistry(self.repo).get(self.session.profile).tool
        except ProfileError:
            return []
        writer = ConnectionWriter(self.repo)
        written = []
        for line in text.splitlines():
            match = re.match(r"^\s*-\s*\**([^:*]+?)\**\s*(?::\s*(.+))?$", line)
            if not match:
                continue
            name, purpose = match.group(1).strip(), (match.group(2) or "").strip()
            item = Captured(Kind.CONNECTION, name, "reported by the model at a checkpoint",
                            meta={"tool": tool, "kind": "mcp",
                                  "description": purpose or f"Connection '{name}'",
                                  "notes": "connector available in the session"})
            written.append(writer.write(item, self.origin).path.relative_to(self.repo.root).as_posix())
        return sorted(set(written))
