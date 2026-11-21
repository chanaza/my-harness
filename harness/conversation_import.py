"""Saving a conversation (or an agent run) that a tool holds: once, for every tool.

An adapter only says what the tool's conversation is, in a ``ToolConversation``; the
``ConversationImporter`` does the rest the same way for every tool:

  - skips it when nothing changed since the last save (``version``), unless its readable
    log or what its meta says about it is out of date;
  - keeps the tool's record in transcript storage: its messages merged by id with what
    earlier saves kept (a tool that returns only recent messages loses nothing), or its
    record as JSON, or its transcript file as it is;
  - keeps the files made in it next to it;
  - writes the one readable ``log.md`` (``ConversationLog``) and ``meta.yaml`` (dates, topic,
    agent / project, where the raw record and the files are, and a ``note`` while one is true).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .conversation_log import ConversationLog, Reply
from .local import StateFile
from .provenance import now_iso
from .repo import ContentRepo
from .sessions import SessionRecord
from .storage import Storage


@dataclass
class ToolConversation:
    #: The conversation's folder under sessions/<profile>/ (e.g. ``conversation-<id>``).
    id: str
    #: Changes whenever the conversation changed; ``None``: always save (e.g. a run still going).
    version: str | None = None
    title: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    #: The tool's record, one of: messages (merged by ``id`` with earlier saves) ...
    messages: list[dict[str, Any]] | None = None
    message_date: Callable[[dict[str, Any]], str] = lambda message: ""
    #: ... the whole record as JSON ...
    raw: Any = None
    #: ... or the tool's transcript file, copied as it is.
    raw_file: Path | None = None
    #: Name of the stored record (messages / raw) in transcript storage.
    raw_name: str = "transcript.json"
    #: More of the tool's own records, kept beside it (name -> text).
    extra: dict[str, str] = field(default_factory=dict)
    #: Files made in the conversation (relative path -> content).
    files: dict[str, bytes | str] = field(default_factory=dict)
    #: The readable replies, from the (merged) messages or the raw record.
    replies: Callable[[Any], list[Reply]] | None = None
    #: More meta fields: agent, conversation, project...
    fields: dict[str, Any] = field(default_factory=dict)
    #: Something to know about it (e.g. deleted in the tool), kept while it is true.
    note: str | None = None


class ConversationImporter:
    def __init__(self, repo: ContentRepo, profile: str, storage: Storage, state: StateFile) -> None:
        self.repo = repo
        self.profile = profile
        self.storage = storage
        self.state = state

    def save(self, conversation: ToolConversation) -> str | None:
        """Returns 'imported', 'updated', or None when nothing needed saving."""
        session = SessionRecord(self.repo, self.profile, conversation.id)
        log = ConversationLog(session)
        if self._current(conversation, session, log):
            return None
        new = not session.meta_path.is_file()
        if new:
            session.touch(
                activity_at=conversation.ended_at,
                started_at=conversation.started_at or now_iso(),
                imported_at=now_iso(),
            )
        key, source = self._record(conversation, session)
        for name, text in conversation.extra.items():
            self.storage.write_text(session.storage_key(name), text)
        files = []
        for relative, content in conversation.files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            self.storage.write_bytes(session.storage_key(f"files/{relative}"), data)
            files.append({"path": relative, "size": len(data)})
        if conversation.replies is not None:
            log.write(conversation.title or conversation.id, conversation.replies(source))
        session.touch(
            activity_at=conversation.ended_at,
            topic=conversation.title or None,
            transcript=key,
            files=files or None,
            note=conversation.note,
            clear=() if conversation.note else ("note",),
            **conversation.fields,
        )
        if conversation.version is not None:
            self.state.set(conversation.id, conversation.version)
        return "imported" if new else "updated"

    def _current(self, conversation: ToolConversation, session: SessionRecord, log: ConversationLog) -> bool:
        if conversation.version is None or self.state.get(conversation.id) != conversation.version:
            return False
        if not session.meta_path.is_file() or (conversation.replies is not None and not log.path.is_file()):
            return False  # saved before the engine kept a log: write it now
        return session.meta().get("note") == conversation.note

    def _record(self, conversation: ToolConversation, session: SessionRecord) -> tuple[str | None, Any]:
        if conversation.messages is not None:
            key = session.storage_key(conversation.raw_name)
            kept = json.loads(self.storage.read_text(key)) if self.storage.exists(key) else []
            merged = {str(m.get("id")): m for m in kept}
            merged.update({str(m.get("id")): m for m in conversation.messages})
            messages = sorted(merged.values(), key=conversation.message_date)
            self.storage.write_text(key, json.dumps(messages, ensure_ascii=False))
            return key, messages
        if conversation.raw_file is not None:
            saved = session.save_transcript(
                self.storage, conversation.raw_file, activity_at=conversation.ended_at
            )
            return (saved[0] if saved else None), conversation.raw_file
        if conversation.raw is not None:
            key = session.storage_key(conversation.raw_name)
            self.storage.write_text(key, json.dumps(conversation.raw, ensure_ascii=False, indent=1))
            return key, conversation.raw
        return None, None
