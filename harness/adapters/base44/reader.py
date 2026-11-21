"""``Base44Reader``: what a Superagent consists of, read from Base44's API.

A Superagent is an app (app_type ``user_agent``). Its own definition sits in its sandbox
files (``.agents/``: identity and soul, rules, skills, MCP servers, legacy memory), its
structured memory behind ``/api/agents/<id>/memory``, its conversations behind
``/api/agents/<id>/conversations/<id>`` (the last 200 messages of each), and its data
model in the app record (entities). Reading it needs a full-access token.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .client import Base44Client, Base44Error


@dataclass
class Superagent:
    id: str
    name: str
    app: dict[str, Any]
    profile: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    memory: list[dict[str, Any]] = field(default_factory=list)
    conversation_ids: list[str] = field(default_factory=list)


class Base44Reader:
    def __init__(self, client: Base44Client) -> None:
        self.client = client
        self.problems: list[str] = []

    def superagents(self) -> list[Superagent]:
        found = []
        for app in self.client.get("/api/apps") or []:
            if app.get("app_type") != "user_agent" or app.get("is_deleted"):
                continue
            agent = Superagent(app["id"], app.get("name") or app["id"], app)
            agent.profile = self._get(f"/api/agents/{agent.id}") or {}
            agent.files = (self._get(f"/api/apps/{agent.id}/sandbox/files") or {}).get("files") or {}
            agent.memory = list(self._get(f"/api/agents/{agent.id}/memory") or [])
            listed = [c["id"] for c in self._get(f"/api/agents/{agent.id}/conversations") or []]
            in_files = sorted({p.split("/")[1] for p in agent.files if p.startswith("conversations/")})
            agent.conversation_ids = list(dict.fromkeys(listed + in_files))
            found.append(agent)
        return found

    def conversation(self, agent: Superagent, conversation_id: str) -> dict[str, Any] | None:
        try:
            return self.client.get(f"/api/agents/{agent.id}/conversations/{conversation_id}")
        except Base44Error as exc:
            if " 404 " in str(exc):  # deleted in Base44; files made in it may still be in the agent's folder
                return {"id": conversation_id, "messages": [], "gone": True}
            self.problems.append(str(exc))
            return None

    def _get(self, path: str) -> Any:
        try:
            return self.client.get(path)
        except Base44Error as exc:
            self.problems.append(str(exc))
            return None
