"""``MondayAdapter``: back up what was built in monday.com's AI layer.

What is locked in monday when AI credits run out is the AI work, so that comes
first (boards and their data are applications of their own; a later step):

  agents ............... core/agents/<name>.yaml: role, goal, identity, instructions,
                         policies, knowledge (references), skills, model, MCP tools
  agent jobs ........... core/workflows/<agent>-<job>.yaml (instructions + triggers)
  workflows ............ core/workflows/<title>.yaml (blocks kept under native)
  MCP tools ............ core/connections.yaml
  agent runs ........... sessions/<profile>/run-<id>/ (+ the full run in transcript storage)

Reading uses monday's API only, never AI credits. Each monday account is a profile.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from ...credentials import CredentialStore
from ...harvest import Captured, HarvestReport, HarvestSync, Kind
from ...local import LocalHome, StateFile
from ...profiles import ProfileRegistry
from ...provenance import Origin, now_iso, to_iso
from ...repo import ContentRepo
from ...sessions import SessionRecord
from ...storage import Storage
from ...text import slugify
from ..base import Account, AccountBoundAdapter, HarnessNotConfigured, adapters
from .client import MondayClient
from .reader import MondayAgent, MondayReader

TOOL = "monday"
#: Fields that change on every read (would make every capture look like a change).
VOLATILE = frozenset({"cursor", "is_running", "has_pending_user_input", "saved_by_count", "saved_by"})
#: Fields mapped to the agent schema (everything else is kept under native).
MAPPED = frozenset({"profile", "goal", "identity", "user_prompt", "policies", "knowledge", "resources",
                    "agent_model", "effective_agent_model", "skill_ids", "mcp_tools"})


@adapters.register
class MondayAdapter(AccountBoundAdapter):
    tool = TOOL
    capture_modes = ("on_demand", "scheduled")
    capture_reason = "always reachable through its API, and reading costs no AI credits"
    environment = "cloud"  # an online service, not a machine

    def __init__(self, local: LocalHome | None = None,
                 reader_factory: Callable[[str], MondayReader] | None = None) -> None:
        super().__init__(local)
        self._reader_factory = reader_factory or self._default_reader

    # --- accounts -----------------------------------------------------------------------

    def is_present(self) -> bool:
        return bool(self.bindings())  # set up explicitly (it needs an API token)

    def accounts(self) -> list[Account]:
        return [Account(key, f"monday.com account {key}") for key in self.bindings()]

    def _default_reader(self, account: str) -> MondayReader:
        token = CredentialStore().get(f"monday:{account}") or CredentialStore().get("monday")
        if not token:
            raise HarnessNotConfigured(f"No monday.com API token for account {account!r}. "
                                       "Run `harness monday probe --account <name>` to add one.")
        settings = self.repo().config.monday
        return MondayReader(MondayClient(token, settings.endpoint, settings.api_version),
                            settings.runs_per_agent)

    # --- what the account holds ------------------------------------------------------------

    def harvest(self, exclude: list[str] | None = None) -> list[Captured]:
        items: list[Captured] = []
        for account in self.bindings():
            reader = self._reader_factory(account)
            items += self._items(reader.agents(), reader.workflows(), exclude or [])
        return items

    def _items(self, agents: list[MondayAgent], workflows: list[dict[str, Any]],
               exclude: list[str]) -> list[Captured]:
        items: list[Captured] = []
        for agent in agents:
            items.append(_agent_item(agent))
            for tool in agent.definition.get("mcp_tools") or []:
                server = tool.get("mcp_server") or tool.get("display_name")
                if server:
                    items.append(Captured(Kind.CONNECTION, server, f"monday agent {agent.name}", meta={
                        "tool": TOOL, "kind": "mcp", "description": tool.get("display_name") or server,
                        "notes": (tool.get("description") or "")[:300]}))
            items += [_job_item(agent, job) for job in agent.jobs]
        items += [_workflow_item(w) for w in workflows]
        return [i for i in items if not any(fnmatch(f"{i.kind.value}:{i.name}", p) for p in exclude)]

    def preview(self, exclude: list[str]) -> list[str]:
        return [f"{i.kind.value:11} {i.name}" for i in self.harvest(exclude)]

    # --- capture -------------------------------------------------------------------------------

    def run_harvest(self, session: str | None = None) -> HarvestReport:
        repo = self.repo()
        config = repo.config
        report = HarvestReport()
        for account, profile in self.bindings().items():
            reader = self._reader_factory(account)
            agents = reader.agents()
            if config.harvest_enabled:
                part = HarvestSync(repo, self.local.state("harvest", profile)).run(
                    self._items(agents, reader.workflows(), config.harvest_exclude),
                    Origin.now(profile, session))
                report.counts.update(part.counts)
                report.conflicts += part.conflicts
                report.errors += part.errors
            storage = repo.storage("transcripts", profile)
            state = self.local.state("conversations", profile)
            with storage.batch():
                for agent in agents:
                    for run in reader.runs(agent):
                        action = RunImporter(repo, profile, storage, state).run(agent, run)
                        if action:
                            report.counts[f"conversations {action}"] += 1
            state.save()
            report.errors += reader.problems
        return report

    # --- installation ------------------------------------------------------------------------------

    def install(self, profile_id: str, label: str, repo_root: Path | None = None, hooks: bool = True,
                environment: str | None = None, account_key: str | None = None) -> list[str]:
        if repo_root:
            self.local.save_settings(content_repo=str(Path(repo_root).resolve()))
        if not account_key:
            raise HarnessNotConfigured("Which monday.com account? (the part before .monday.com)")
        profile = ProfileRegistry(self.repo()).add(self.tool, label, profile_id=profile_id,
                                                   environment=environment or self.environment)
        self.bind(account_key, profile.id)
        done = [f"monday.com {account_key} -> {profile.id}"]
        if hooks:
            done.append(self.schedule())
        return done


from ...conversation_log import ConversationLog  # noqa: E402
from .run_replies import run_reply  # noqa: E402


class RunImporter:
    """One agent run (a conversation) -> a session record + the full run in transcript storage."""

    FINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED", "completed", "failed", "cancelled"})

    def __init__(self, repo: ContentRepo, profile: str, storage: Storage, state: StateFile) -> None:
        self.repo = repo
        self.profile = profile
        self.storage = storage
        self.state = state

    def run(self, agent: MondayAgent, run: dict[str, Any]) -> str | None:
        run_id = str(run.get("run_id") or "")
        status = str(run.get("status") or "")
        session = SessionRecord(self.repo, self.profile, f"run-{run_id}")
        log = ConversationLog(session)
        if not run_id or (self.state.get(run_id) == status and status in self.FINAL):
            if run_id and session.meta_path.is_file() and not log.path.is_file():
                log.write(str(run.get("title") or agent.name), [run_reply(run)])   # runs saved before logs
                return "updated"
            return None
        new = not session.meta_path.is_file()
        ended = _when(run.get("completed_at")) or _when(run.get("started_at"))
        if new:
            session.touch(activity_at=ended, started_at=_when(run.get("started_at")) or now_iso(),
                          imported_at=now_iso())
        key = session.storage_key("run.json")
        self.storage.write_text(key, json.dumps(run, ensure_ascii=False, indent=1))
        session.touch(activity_at=ended, topic=run.get("title") or None, transcript=key,
                      agent=slugify(agent.name), conversation=run.get("conversation_id") or None)
        log.write(str(run.get("title") or agent.name), [run_reply(run)])   # the engine's readable log
        self.state.set(run_id, status)
        return "imported" if new else "updated"


def _agent_item(agent: MondayAgent) -> Captured:
    d = agent.definition
    profile = d.get("profile") or {}
    resources = agent.knowledge.get("resources") or d.get("resources") or []
    knowledge = [{"type": r.get("scope_type"), "id": r.get("resource_id"),
                  "permission": r.get("permission_type")} for r in resources]
    knowledge += [{"type": "file", **f} for f in agent.knowledge.get("files") or []]
    knowledge += [{"type": "cloud_file", **f} for f in agent.knowledge.get("cloud_files") or []]
    servers = [slugify(t.get("mcp_server") or t.get("display_name") or "") for t in d.get("mcp_tools") or []]
    definition = {
        "name": agent.name,
        "description": profile.get("role_description") or profile.get("role") or agent.name,
        "role": profile.get("role"),
        "goal": d.get("goal"),
        "identity": d.get("identity"),
        "instructions": d.get("user_prompt") or "",
        "policies": d.get("policies") or [],
        "knowledge": knowledge,
        "skills": agent.skills,
        "model": d.get("effective_agent_model") or d.get("agent_model"),
        "requires": {"connections": [s for s in dict.fromkeys(servers) if s]} if any(servers) else None,
    }
    native = {k: v for k, v in d.items() if k not in MAPPED | VOLATILE}
    native["profile"] = {k: v for k, v in profile.items() if k not in ("name", "role", "role_description")}
    return Captured(Kind.AGENT, agent.name, f"monday agent {agent.id}", meta={"agent": definition,
                                                                               "native": native})


def _job_item(agent: MondayAgent, job: dict[str, Any]) -> Captured:
    triggers = [t.get("name") or t.get("summary") or "" for t in job.get("triggers") or []]
    return Captured(Kind.WORKFLOW, f"{agent.name}-{job.get('name') or job.get('job_id')}",
                    f"monday agent {agent.id} job {job.get('job_id')}", meta={
                        "description": job.get("name") or "agent job",
                        "prompt": job.get("instructions") or job.get("name") or "",
                        "trigger": ", ".join(t for t in triggers if t),
                        "agent": agent.name,
                        "native": job})


def _workflow_item(workflow: dict[str, Any]) -> Captured:
    title = workflow.get("title") or f"workflow-{workflow.get('id')}"
    return Captured(Kind.WORKFLOW, title, f"monday workflow {workflow.get('id')}", meta={
        "description": workflow.get("description") or title,
        "prompt": workflow.get("description") or title,
        "native": {k: v for k, v in workflow.items() if k not in VOLATILE}})


def _when(value: Any) -> str | None:
    """monday timestamps arrive as ISO text or epoch numbers."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        number = float(value)
        seconds = number / 1000 if number > 1e11 else number
        return datetime.fromtimestamp(seconds, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return to_iso(str(value))
