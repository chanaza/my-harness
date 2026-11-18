"""``MondayReader``: reads what was built in a monday.com account's AI layer.

Agents (definition, skills, knowledge), their jobs (= workflows), workflow-builder
workflows, and agent runs (= conversations). Read-only; uses no AI credits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .client import MondayClient, MondayError
from .schema import SchemaSelector


@dataclass
class MondayAgent:
    definition: dict[str, Any]
    skills: list[str] = field(default_factory=list)
    knowledge: dict[str, Any] = field(default_factory=dict)
    jobs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def id(self) -> str:
        return str(self.definition.get("id"))

    @property
    def name(self) -> str:
        return (self.definition.get("profile") or {}).get("name") or f"agent-{self.id}"


class MondayReader:
    #: Agent kinds looked up by agent user (monday's AgentKind values).
    AGENT_KINDS = ("PERSONAL", "ACCOUNT_LEVEL")

    def __init__(self, client: MondayClient, runs_per_agent: int = 50) -> None:
        self.client = client
        self.schema = SchemaSelector(client)
        self.runs_per_agent = runs_per_agent
        self.problems: list[str] = []

    def account(self) -> dict[str, Any]:
        me = self.client.query("query { me { email account { id name slug } } }").get("me") or {}
        return {"email": me.get("email"), **(me.get("account") or {})}

    def agents(self) -> list[MondayAgent]:
        agents = [MondayAgent(a) for a in self._custom_agents()]
        for agent in agents:
            agent.skills = [s.get("name") for s in self._each("agent_skill_names", "AgentSkillCatalogEntry",
                                                               agent.id) or [] if s.get("name")]
            agent.knowledge = self._each("agent_knowledge", "AgentKnowledge", agent.id) or {}
            agent.jobs = self._each("agent_jobs", "AgentJob", agent.id) or []
        return agents

    def _custom_agents(self) -> list[dict[str, Any]]:
        """Every agent the user owns or is a member of.

        The source of truth is the account's list of agent users (``agents``), which says who owns
        each one. ``custom_agents(limit: ...)`` is not: it leaves out workspace agents (e.g. a
        workspace's PMO agent created with the workspace), so definitions are read by agent user id.
        An agent of the user's that cannot be read is reported, never skipped silently."""
        selection = self.schema.selection("CustomAgent")
        listed = self.client.query(f"query {{ custom_agents(limit: 100) {{ {selection} }} }}")
        found = {a["agent_user_id"]: a for a in listed.get("custom_agents") or []}
        try:
            data = self.client.query("query { me { id } agents(limit: 100) { id user { name } "
                                     "subscribers { entity { ... on User { id } } } } }")
        except MondayError as exc:
            self.problems.append(f"agent list: {exc}")
            return list(found.values())
        me = str((data.get("me") or {}).get("id"))
        mine = {a["id"]: (a.get("user") or {}).get("name") or a["id"] for a in data.get("agents") or []
                if any(str((s.get("entity") or {}).get("id")) == me for s in a.get("subscribers") or [])}
        missing = [user for user in mine if user not in found]
        if missing:
            ids = ", ".join(f'"{user}"' for user in missing)
            for kind in self.AGENT_KINDS:
                try:
                    more = self.client.query(f"query {{ custom_agents(kinds: [{kind}], "
                                             f"agent_user_ids: [{ids}]) {{ {selection} }} }}")
                except MondayError as exc:
                    self.problems.append(f"{kind.lower()} agents: {exc}")
                    continue
                found.update({a["agent_user_id"]: a for a in more.get("custom_agents") or []})
        for user in mine:
            if user not in found:
                self.problems.append(f"agent {mine[user]}: yours, but monday did not return it")
        return list(found.values())

    def workflows(self) -> list[dict[str, Any]]:
        try:
            page = self.client.query(f"query {{ get_live_workflows_page {{ "
                                     f"{self.schema.selection('LiveWorkflowsPage')} }} }}")
        except MondayError as exc:
            self.problems.append(f"workflows: {exc}")
            return []
        return list((page.get("get_live_workflows_page") or {}).get("data") or [])

    def runs(self, agent: MondayAgent) -> list[dict[str, Any]]:
        selection = self.schema.selection("AgentRun")
        try:
            found = self.client.query(f"query {{ agent_runs(agent_id: {agent.id}, "
                                      f"limit: {self.runs_per_agent}) {{ {selection} }} }}")
        except MondayError as exc:
            self.problems.append(f"runs of {agent.name}: {exc}")
            return []
        return list(found.get("agent_runs") or [])

    def _each(self, query: str, type_name: str, agent_id: str) -> Any:
        try:
            data = self.client.query(f"query {{ {query}(agent_id: {agent_id}) "
                                     f"{{ {self.schema.selection(type_name)} }} }}")
        except MondayError as exc:
            self.problems.append(f"{query} for agent {agent_id}: {exc}")
            return None
        return data.get(query)
