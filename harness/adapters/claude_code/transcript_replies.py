"""Claude Code's transcript (JSON lines) as ``Reply`` objects for the engine's log.

Only what is particular to Claude Code lives here: which entries are messages the user
typed, how text, images, actions and messages sent while Claude was working are stored.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ...conversation_log import Reply


def transcript_replies(transcript: Path) -> list[Reply]:
    replies: list[Reply] = []
    for entry in _entries(transcript):
        content = (entry.get("message") or {}).get("content")
        if _typed_by_user(entry):
            replies.append(Reply(len(replies) + 1, _at(entry), [_user_text(content)]))
        elif not replies:
            continue
        elif _queued_by_user(entry):
            prompt = entry["attachment"]["prompt"]
            replies[-1].assistant.append(f"> (Message from the user while Claude was working:)\n> {prompt}")
        elif entry.get("type") == "assistant" and isinstance(content, list):
            for part in content:
                if part.get("type") == "text" and part.get("text", "").strip():
                    replies[-1].assistant.append(part["text"].strip())
                elif part.get("type") == "tool_use":
                    data = part.get("input") or {}
                    replies[-1].assistant.append(Reply.action(part.get("name", "tool"), _what(data)))
    return replies


def _entries(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _typed_by_user(entry: dict[str, Any]) -> bool:
    """A message the user typed (not tool results, injected context or a compaction summary)."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return not content.lstrip().startswith(("<command-", "<local-command", "<system-reminder"))
    return isinstance(content, list) and not any(p.get("type") == "tool_result" for p in content)


def _queued_by_user(entry: dict[str, Any]) -> bool:
    attachment = entry.get("attachment") or {}
    return (entry.get("type") == "attachment" and attachment.get("type") == "queued_command"
            and isinstance(attachment.get("prompt"), str)
            and (attachment.get("origin") or {}).get("kind") == "human")


def _user_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    parts = [p.get("text", "").strip() if p.get("type") == "text" else "[image]"
             for p in content if p.get("type") in ("text", "image")]
    return "\n\n".join(p for p in parts if p)


def _what(data: dict[str, Any]) -> str:
    return str(data.get("description") or data.get("file_path") or data.get("pattern")
               or data.get("query") or data.get("command") or data.get("url") or "")


def _at(entry: dict[str, Any]) -> str:
    stamp = str(entry.get("timestamp") or "")
    return stamp.split(".")[0].replace("T", " ") + (" UTC" if stamp else "")
