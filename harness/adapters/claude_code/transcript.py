"""Reading Claude Code session transcripts (JSONL, one event per line)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Span:
    """When and where a transcript's conversation happened."""

    started_at: str | None
    ended_at: str | None
    cwd: str | None
    user_messages: int


@dataclass(frozen=True)
class Exchange:
    prompt: str
    answer: str


class TranscriptReader:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def entries(self) -> Iterator[dict[str, Any]]:
        if not self.path.is_file():
            return
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue  # a partially written last line

    # --- classification -------------------------------------------------------

    @staticmethod
    def text_of(entry: dict[str, Any]) -> str:
        """Plain text of a user/assistant entry (tool calls and results are skipped)."""
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text").strip()
        return ""

    @classmethod
    def is_user_prompt(cls, entry: dict[str, Any]) -> bool:
        """A message the person typed (not a tool result, meta note or compaction summary)."""
        if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
            return False
        if entry.get("isSidechain"):
            return False
        return bool(cls.text_of(entry))

    # --- queries ----------------------------------------------------------------

    def span(self) -> Span:
        first = last = cwd = None
        prompts = 0
        for entry in self.entries():
            stamp = entry.get("timestamp")
            if stamp:
                first = first or stamp
                last = stamp
            cwd = cwd or entry.get("cwd")
            prompts += self.is_user_prompt(entry)
        return Span(_iso(first), _iso(last), cwd, prompts)

    def context_tokens(self) -> int | None:
        """Tokens in context at the latest main-thread model call."""
        tokens = None
        for entry in self.entries():
            usage = (entry.get("message") or {}).get("usage")
            if entry.get("type") == "assistant" and usage and not entry.get("isSidechain"):
                tokens = sum(int(usage.get(k) or 0) for k in
                             ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        return tokens

    def exchanges(self, last: int | None = None) -> list[Exchange]:
        """User prompts with the assistant's final text answer, oldest first."""
        found: list[Exchange] = []
        prompt, answer = None, ""
        for entry in self.entries():
            if self.is_user_prompt(entry):
                if prompt is not None:
                    found.append(Exchange(prompt, answer))
                prompt, answer = self.text_of(entry), ""
            elif entry.get("type") == "assistant" and not entry.get("isSidechain"):
                answer = self.text_of(entry) or answer
        if prompt is not None:
            found.append(Exchange(prompt, answer))
        return found[-last:] if last else found

    def last_exchange(self) -> Exchange | None:
        exchanges = self.exchanges(last=1)
        return exchanges[0] if exchanges else None

    def latest_compact_summary(self) -> str | None:
        summary = None
        for entry in self.entries():
            if entry.get("isCompactSummary"):
                summary = self.text_of(entry) or summary
        return summary


class ContextMeter:
    """Turns token counts into a usage percent.

    Uses the configured window, but if the conversation already holds more
    tokens than that, the model clearly has a larger window: the next known
    size is used instead.
    """

    KNOWN_WINDOWS = (200_000, 1_000_000)

    def __init__(self, configured_window: int) -> None:
        self.configured_window = configured_window

    def window_for(self, tokens: int) -> int:
        if tokens <= self.configured_window:
            return self.configured_window
        return next((w for w in self.KNOWN_WINDOWS if w >= tokens), tokens)

    def percent(self, tokens: int | None) -> float | None:
        if tokens is None:
            return None
        return 100.0 * tokens / self.window_for(tokens)


def _iso(stamp: str | None) -> str | None:
    """Claude Code timestamps ('2026-11-18T07:20:10.123Z') in the schema format."""
    if not stamp:
        return None
    return stamp.split(".")[0].rstrip("Z") + "Z"
