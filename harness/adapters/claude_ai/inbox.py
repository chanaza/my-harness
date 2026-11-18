"""``AccountInbox``: what the ``harness-account`` skill writes for a Claude account.

The skill (in claude.ai, Claude Desktop and Cowork alike) writes one file per run
into a Google Drive folder that this computer syncs (``claude_ai.inbox_folder``):

  describe-<time>.yaml ............ everything the account has built, in a fixed form
                                     (checked against schemas/claude-account.schema.json)
  conversation-<time>-<title>.md .. a conversation's summary in the harness's sections

A file that does not match its form is reported and not saved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ... import yaml_io
from ...documents import MarkdownDocument
from ...harvest import Captured, Kind
from ...text import slugify

DESCRIBE_PATTERN = "describe-*.yaml"
CONVERSATION_PATTERN = "conversation-*.md"


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads(resources.files("harness.schemas").joinpath(name).read_text("utf-8"))
    return Draft202012Validator(schema)


@dataclass
class InboxFile:
    path: Path
    data: dict[str, Any]
    body: str = ""

    @property
    def account(self) -> str:
        return str(self.data.get("account") or "")


class AccountInbox:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.problems: list[str] = []

    def files(self, pattern: str) -> list[Path]:
        return sorted(p for p in self.folder.glob(pattern) if p.is_file()) if self.folder.is_dir() else []

    def describes(self) -> list[InboxFile]:
        found = []
        validator = _validator("claude-account.schema.json")
        for path in self.files(DESCRIBE_PATTERN):
            try:
                data = json.loads(json.dumps(yaml_io.load(path.read_text("utf-8")) or {}, default=str))
            except Exception as exc:  # noqa: BLE001 - any unreadable file is reported, not fatal
                self.problems.append(f"{path.name}: not readable ({exc})")
                continue
            errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
            if errors:
                where = "/".join(str(p) for p in errors[0].path) or "(top)"
                self.problems.append(f"{path.name}: does not match the form at {where}: {errors[0].message}")
                continue
            found.append(InboxFile(path, data))
        return found

    def conversations(self) -> list[InboxFile]:
        found = []
        validator = _validator("claude-conversation.schema.json")
        for path in self.files(CONVERSATION_PATTERN):
            document = MarkdownDocument.parse(path.read_text("utf-8"))
            meta = json.loads(json.dumps(dict(document.meta), default=str))
            errors = list(validator.iter_errors(meta))
            if errors:
                self.problems.append(f"{path.name}: does not match the form: {errors[0].message}")
                continue
            found.append(InboxFile(path, meta, document.body))
        return found


def describe_items(describe: InboxFile, tool: str) -> list[Captured]:
    """A describe file -> harness items, each kind in its own place."""
    data, origin = describe.data, describe.path.name
    items: list[Captured] = []
    for entry in data.get("instructions") or []:
        name = slugify(entry["name"])
        items.append(Captured(Kind.INSTRUCTION, name, origin, {f"{name}.md": entry["text"].encode()}))
    for number, entry in enumerate(data.get("memory") or [], 1):
        items.append(Captured(Kind.MEMORY, f"memory-{number}", origin,
                              {f"memory-{number}.md": entry["text"].encode()}))
    for entry in data.get("skills") or []:
        if entry.get("origin") == "mine":
            text = f"---\nname: {entry['name']}\ndescription: {entry.get('description', '')}\n---\n"
            items.append(Captured(Kind.SKILL, entry["name"], origin, {"SKILL.md": text.encode()},
                                  meta={"description": entry.get("description")}))
    for entry in data.get("agents") or []:
        items.append(Captured(Kind.AGENT, entry["name"], origin, meta={"agent": {
            "name": slugify(entry["name"]), "description": entry.get("description") or entry["name"]}}))
    for entry in data.get("plugins") or []:
        if entry.get("origin") == "mine":
            items.append(Captured(Kind.PLUGIN, entry["name"], origin,
                                  {"README.md": (entry.get("description") or "").encode()},
                                  meta={"description": entry.get("description") or entry["name"]}))
    for entry in data.get("connections") or []:
        items.append(Captured(Kind.CONNECTION, entry["name"], origin, meta={
            "tool": tool, "kind": entry.get("kind", "connector"),
            "description": entry.get("purpose") or entry["name"]}))
    for entry in data.get("projects") or []:
        items.append(Captured(Kind.PROJECT, entry["name"], origin,
                              {"instructions.md": (entry.get("instructions") or "").encode()},
                              meta={"description": entry.get("description") or entry["name"],
                                    "fields": {"title": entry["name"],
                                               "knowledge_files": entry.get("files") or []}}))
    for entry in data.get("workflows") or []:
        items.append(Captured(Kind.WORKFLOW, entry["name"], origin, meta={
            "description": entry["name"], "prompt": entry.get("prompt"), "trigger": entry.get("schedule")}))
    rest = {key: data[key] for key in ("profile", "apps", "native", "cannot_see", "surface") if data.get(key)}
    items.append(Captured(Kind.NATIVE, "account", origin,
                          {"account/account.yaml": yaml_io.dump(rest).encode()}))
    return items
