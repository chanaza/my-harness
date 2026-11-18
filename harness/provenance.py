"""Provenance: which profile (tool + account) and session an item came from, and who changed it since."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def to_iso(stamp: str | None) -> str | None:
    """A tool's timestamp ('2026-11-18T07:20:10.123456Z' / '+00:00') in the schema format."""
    if not stamp:
        return None
    text = str(stamp).strip().replace(" ", "T", 1).replace("+00:00", "Z")  # also YAML's own dates
    return text.split(".")[0].rstrip("Z") + "Z"


def now_iso() -> str:
    """Current UTC time in the format every schema expects."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Origin:
    """A single event: a profile (and optionally a session) touching an item at a time."""

    profile: str
    session: str | None = None
    at: str = ""
    note: str | None = None

    @classmethod
    def now(cls, profile: str, session: str | None = None, note: str | None = None) -> Origin:
        return cls(profile=profile, session=session, at=now_iso(), note=note)

    def to_dict(self) -> dict[str, Any]:
        event = {"profile": self.profile, "at": self.at or now_iso()}
        if self.session:
            event["session"] = self.session
        if self.note:
            event["note"] = self.note
        return event


class Provenance:
    """Builds and updates the ``provenance`` block stored on every cross-session item."""

    @staticmethod
    def new(origin: Origin) -> dict[str, Any]:
        return {"source": origin.to_dict()}

    @staticmethod
    def updated(existing: dict[str, Any] | None, origin: Origin) -> dict[str, Any]:
        """Return ``existing`` with ``origin`` appended to its updates (or a new block)."""
        if not existing or "source" not in existing:
            return Provenance.new(origin)
        block = {"source": existing["source"], "updates": list(existing.get("updates", []))}
        block["updates"].append(origin.to_dict())
        return block

    @staticmethod
    def last_profile(block: dict[str, Any] | None) -> str | None:
        """The profile that touched the item most recently."""
        if not block:
            return None
        updates = block.get("updates") or []
        return (updates[-1] if updates else block.get("source", {})).get("profile")
