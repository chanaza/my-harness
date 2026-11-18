"""Reading a claude.ai data export (the zip from Settings > Privacy > Export data)."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Conversation:
    uuid: str
    name: str
    created_at: str | None
    updated_at: str | None
    raw: dict[str, Any]

    @property
    def attachments(self) -> list[tuple[str, str]]:
        """(file name, extracted text) of every attachment in the conversation."""
        found = []
        for message in self.raw.get("chat_messages") or []:
            for attachment in message.get("attachments") or []:
                text = attachment.get("extracted_content")
                if text:
                    found.append((attachment.get("file_name") or "attachment.txt", text))
        return found

    @property
    def messages(self) -> int:
        return len(self.raw.get("chat_messages") or [])


@dataclass
class Project:
    uuid: str
    name: str
    description: str
    instructions: str
    created_at: str | None
    docs: list[tuple[str, str]] = field(default_factory=list)  # (file name, content)


class ClaudeAiExport:
    """One export file. Unknown or missing parts are tolerated: the format may grow."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _json(self, *names: str) -> Any:
        with zipfile.ZipFile(self.path) as archive:
            for info in archive.infolist():
                base = info.filename.rsplit("/", 1)[-1]
                if base in names:
                    return json.loads(archive.read(info).decode("utf-8"))
        return None

    def is_valid(self) -> bool:
        try:
            return self._json("conversations.json") is not None
        except (zipfile.BadZipFile, OSError, ValueError):
            return False

    def emails(self) -> list[str]:
        users = self._json("users.json") or []
        users = users if isinstance(users, list) else [users]
        return [u["email_address"] for u in users if isinstance(u, dict) and u.get("email_address")]

    @property
    def account(self) -> str:
        """The account the export belongs to (its e-mail address)."""
        emails = self.emails()
        return emails[0] if emails else self.path.stem

    def conversations(self) -> list[Conversation]:
        return [Conversation(c.get("uuid", ""), c.get("name") or "", c.get("created_at"),
                             c.get("updated_at"), c)
                for c in self._json("conversations.json") or [] if isinstance(c, dict) and c.get("uuid")]

    def projects(self) -> list[Project]:
        found = []
        for p in self._json("projects.json") or []:
            if not isinstance(p, dict) or not p.get("uuid") or p.get("is_starter_project"):
                continue
            docs = [(d.get("filename") or "document.txt", d.get("content") or "")
                    for d in p.get("docs") or [] if isinstance(d, dict)]
            found.append(Project(p["uuid"], p.get("name") or p["uuid"], p.get("description") or "",
                                 p.get("prompt_template") or "", p.get("created_at"), docs))
        return found

    def memories(self) -> list[str]:
        data = self._json("memories.json", "memory.json")
        if isinstance(data, dict):
            entries = data.get("memories") or []
        else:
            entries = data or []
        texts = []
        for entry in entries:
            if isinstance(entry, str):
                texts.append(entry)
            elif isinstance(entry, dict):
                text = entry.get("content") or entry.get("memory") or entry.get("text")
                if text:
                    texts.append(str(text))
        return texts
