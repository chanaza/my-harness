"""ConversationImporter: how every tool's conversations are saved, once, in the engine."""

from __future__ import annotations

import json

from harness.conversation_import import ConversationImporter, ToolConversation
from harness.conversation_log import Reply
from harness.local import LocalHome
from harness.repo import ContentRepo


def replies(messages):
    return [Reply(i + 1, "", [m["text"]]) for i, m in enumerate(m for m in messages if m["role"] == "user")]


def conversation(messages, version, note=None):
    return ToolConversation(id="conversation-1", version=version, title="Plans", messages=messages,
                            message_date=lambda m: m["at"], raw_name="messages.json",
                            files={"out/report.md": "# Report"}, replies=replies,
                            fields={"agent": "planner"}, note=note)


def test_messages_grow_by_id_logs_are_written_and_unchanged_ones_are_skipped(repo: ContentRepo):
    storage = repo.storage("transcripts", "tool-personal-cloud")
    importer = ConversationImporter(repo, "tool-personal-cloud", storage, LocalHome().state("c", "p"))
    first = [{"id": "a", "at": "1", "role": "user", "text": "q1"}]
    assert importer.save(conversation(first, "v1", note="only recent messages")) == "imported"
    assert importer.save(conversation(first, "v1", note="only recent messages")) is None  # nothing new
    later = [{"id": "b", "at": "2", "role": "user", "text": "q2"}]  # the tool now returns only these
    assert importer.save(conversation(later, "v2")) == "updated"
    folder = repo.path("sessions", "tool-personal-cloud", "conversation-1")
    log = (folder / "log.md").read_text()
    assert "q1" in log and "q2" in log  # nothing lost when the tool's window moved on
    meta = (folder / "meta.yaml").read_text()
    assert "agent: planner" in meta and "note" not in meta  # a note that is no longer true is gone
    saved = json.loads(storage.read_text("tool-personal-cloud/conversation-1/messages.json"))
    assert [m["id"] for m in saved] == ["a", "b"]
    assert storage.read_text("tool-personal-cloud/conversation-1/files/out/report.md") == "# Report"


def test_an_empty_conversation_is_not_kept_and_a_deleted_one_keeps_only_its_files(repo: ContentRepo):
    storage = repo.storage("transcripts", "tool-personal-cloud")
    importer = ConversationImporter(repo, "tool-personal-cloud", storage, LocalHome().state("c", "p"))
    empty = ToolConversation(id="conversation-2", version="v", messages=[], raw_name="messages.json",
                             replies=replies)
    assert importer.save(empty) is None
    assert not repo.path("sessions", "tool-personal-cloud", "conversation-2").exists()
    deleted = ToolConversation(id="conversation-3", version="v", messages=[], raw_name="messages.json",
                               files={"plan.md": "# Plan"}, replies=replies, note="Deleted in the tool")
    assert importer.save(deleted) == "imported"
    assert not storage.exists("tool-personal-cloud/conversation-3/messages.json")  # no empty record
    assert storage.read_text("tool-personal-cloud/conversation-3/files/plan.md") == "# Plan"
