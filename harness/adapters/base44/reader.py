"""``Base44Reader``: what a Superagent consists of, read from Base44's API.

A Superagent is an app (app_type ``user_agent``). Its own definition sits in its sandbox
files (``.agents/``: identity and soul, rules, skills, MCP servers, legacy memory), its
structured memory behind ``/api/agents/<id>/memory``, and its data model in the app record.
Some things are read through the endpoints Base44's own editor uses, because the public API
does not have them: every conversation (``/api/apps/<id>/user-agent/conversations/v2``) with
all its messages (``.../conversations/<id>/messages``, paged back by date - the public API
returns only the last 200), and standing goals (``/api/agents/<id>/notes/goal?name=``, named
in conversations' ``active_goal_names``). Reading it needs a full-access token.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from .client import Base44Client, Base44Error

CONVERSATION_ID = re.compile(r"\b[0-9a-f]{24}\b")


@dataclass
class Superagent:
    id: str
    name: str
    app: dict[str, Any]
    profile: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    memory: list[dict[str, Any]] = field(default_factory=list)
    conversation_ids: list[str] = field(default_factory=list)
    functions: list[dict[str, Any]] = field(default_factory=list)  # its backend functions (server code)
    webhooks: list[dict[str, Any]] = field(default_factory=list)  # events it sends to a URL
    channels: list[dict[str, Any]] = field(default_factory=list)  # WhatsApp, phone, Telegram...
    workflow_status: dict[str, str] = field(default_factory=dict)  # automation -> active / ...
    settings_rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # rows the harness keeps
    goals: list[dict[str, Any]] = field(default_factory=list)  # standing goals, each with its tasks
    #: Conversations named in its goals and memory but not listed (e.g. a goal's working "room").
    mentioned_conversation_ids: list[str] = field(default_factory=list)


class Base44Reader:
    def __init__(self, client: Base44Client, wants_rows: Callable[[str], bool] = lambda table: False) -> None:
        self.client = client
        self.wants_rows = wants_rows  # the harness's choice (harvest.table_rows), not the tool's
        self.problems: list[str] = []

    def superagents(self) -> list[Superagent]:
        found = []
        for app in self.client.get("/api/apps") or []:
            if app.get("app_type") != "user_agent" or app.get("is_deleted"):
                continue
            agent = Superagent(app["id"], app.get("name") or app["id"], app)
            agent.profile = self._get(f"/api/agents/{agent.id}") or {}
            agent.files = (self._get(f"/api/apps/{agent.id}/sandbox/files") or {}).get("files") or {}
            agent.functions = (self._get(f"/api/apps/{agent.id}/backend-functions") or {}).get(
                "functions"
            ) or []
            agent.webhooks = list(self._get(f"/api/agents/{agent.id}/webhooks") or [])
            agent.channels = list((self._get(f"/api/agents/{agent.id}/channels") or {}).get("channels") or [])
            agent.workflow_status = {
                str(w.get("name") or w.get("file_key")): str(w.get("status") or "")
                for w in self._get(f"/api/apps/{agent.id}/workflows") or []
            }
            agent.settings_rows = {
                table: list(self._get(f"/api/apps/{agent.id}/entities/{table}") or [])
                for table in (app.get("entities") or {})
                if self.wants_rows(table)
            }
            agent.memory = list(self._get(f"/api/agents/{agent.id}/memory") or [])
            listed = self._conversations(agent.id)
            in_files = sorted({p.split("/")[1] for p in agent.files if p.startswith("conversations/")})
            agent.conversation_ids = list(dict.fromkeys([c["id"] for c in listed] + in_files))
            names = {n for c in listed for n in ((c.get("metadata") or {}).get("active_goal_names") or [])}
            agent.goals = [g for g in (self._goal(agent.id, n) for n in sorted(names)) if g]
            text = (
                json.dumps(agent.goals)
                + json.dumps(agent.memory, ensure_ascii=False)
                + "".join(
                    v
                    for k, v in agent.files.items()
                    if isinstance(v, str) and k.startswith(("notes/", "base44/"))
                )
            )
            agent.mentioned_conversation_ids = sorted(
                set(CONVERSATION_ID.findall(text)) - set(agent.conversation_ids) - {agent.id}
            )
            found.append(agent)
        return found

    def _conversations(self, agent_id: str) -> list[dict[str, Any]]:
        """Every conversation of the agent (the editor's list, page by page, archived ones too)."""
        found: list[dict[str, Any]] = []
        for archived in ("false", "true"):
            cursor = ""
            while True:
                page = (
                    self._get(
                        f"/api/apps/{agent_id}/user-agent/conversations/v2?limit=100"
                        f"&is_archived={archived}{f'&cursor={quote(cursor)}' if cursor else ''}"
                    )
                    or {}
                )
                found += [c for c in page.get("items") or [] if c.get("id")]
                cursor = page.get("next_cursor") or ""
                if not cursor:
                    break
        return found

    def _goal(self, agent_id: str, name: str) -> dict[str, Any] | None:
        return self._get(f"/api/agents/{agent_id}/notes/goal?name={quote(name)}")

    def conversation(
        self, agent: Superagent, conversation_id: str, mentioned: bool = False
    ) -> dict[str, Any] | None:
        """A conversation with all its messages, oldest first (the plain API returns only the
        last 200; the editor's endpoint pages back through all of them)."""
        try:
            conversation = self.client.get(f"/api/agents/{agent.id}/conversations/{conversation_id}")
        except Base44Error as exc:
            if " 404 " in str(exc):  # not a conversation (a mentioned id), or deleted in Base44
                return None if mentioned else {"id": conversation_id, "messages": [], "gone": True}
            self.problems.append(str(exc))
            return None
        messages = self._all_messages(agent.id, conversation_id)
        if messages is not None:
            conversation["messages"] = messages
        return conversation

    def _all_messages(self, agent_id: str, conversation_id: str) -> list[dict[str, Any]] | None:
        seen: dict[str, dict[str, Any]] = {}
        before = ""
        for _ in range(500):  # 100,000 messages at most
            page = self._get(
                f"/api/apps/{agent_id}/user-agent/conversations/{conversation_id}/messages"
                f"?limit=200{f'&before={quote(before)}' if before else ''}"
            )
            if page is None:
                return None
            batch = [m for m in page.get("messages") or [] if m.get("id") not in seen]
            for message in batch:
                created = (message.get("metadata") or {}).get("created_date")
                seen[message["id"]] = {"created_date": created, **message}
            if not batch or not page.get("has_more"):
                break
            before = min(str(m.get("created_date") or "") for m in seen.values() if m.get("created_date"))
        return sorted(seen.values(), key=lambda m: str(m.get("created_date") or ""))

    def _get(self, path: str) -> Any:
        try:
            return self.client.get(path)
        except Base44Error as exc:
            self.problems.append(str(exc))
            return None
