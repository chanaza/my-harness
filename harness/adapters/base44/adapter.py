"""``Base44Adapter``: Base44 Superagents, pulled on demand (like monday.com).

Only what is particular to Base44 lives here: where a Superagent keeps each thing, and how
its messages read. Everything goes into the harness through the engine (HarvestSync,
ConversationLog), so every item carries this profile as its source.

  Superagent definition (identity, soul, model, skills, connections) .. core/agents/
  rules (.agents/rules/*.md, always-on) ................................ core/instructions/
  skills (.agents/skills/) ............................................. core/skills/
  MCP servers it runs (.agents/mcps/<name>/) ........................... core/plugins/ (+ connections)
  memory (structured memory, legacy USER.md / memory.md, notes/) ...... memory/
  data model (entities, base44/) ...................................... apps/<superagent>/
  conversations (last 200 messages each, kept growing by message id) .. sessions/ (+ log.md)
  files made in a conversation (conversations/<id>/) .................. with that conversation

Never saved: .agents/.env and anything that looks like a secret, Base44's own docs
(.agents/platform-docs/), the table data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from ...conversation_log import ConversationLog, Reply
from ...credentials import CredentialStore
from ...harvest import Captured, HarvestReport, HarvestSync, Kind
from ...local import LocalHome
from ...profiles import ProfileRegistry
from ...provenance import Origin, now_iso, to_iso
from ...sessions import SessionRecord
from ...text import slugify
from ..base import Account, AccountBoundAdapter, HarnessNotConfigured, adapters
from .client import Base44Client
from .reader import Base44Reader, Superagent

TOOL = "base44"
NEVER = (".agents/.env", ".agents/platform-docs/", ".gitignore")
SECRET = re.compile(
    r"(ghp_|github_pat_|sk-ant-|sk-[A-Za-z0-9]{20}|xox[bp]-|AKIA|b44k_)[A-Za-z0-9_-]{8,}"
    r"|(password|passwd|secret|api_?key|token)\"?\s*[:=]\s*\"?[^\s\"${}]{6,}",
    re.IGNORECASE,
)


@adapters.register
class Base44Adapter(AccountBoundAdapter):
    tool = TOOL
    environment = "cloud"
    capture_modes = ("on_demand", "scheduled")
    capture_reason = "always reachable through its API with a personal access token"

    def __init__(
        self, local: LocalHome | None = None, reader_factory: Callable[[str], Base44Reader] | None = None
    ) -> None:
        super().__init__(local)
        self._reader_factory = reader_factory or self._default_reader

    def is_present(self) -> bool:
        return bool(self.bindings())  # set up explicitly (it needs a token)

    def accounts(self) -> list[Account]:
        return [Account(key, f"Base44 account {key}") for key in self.bindings()]

    def _default_reader(self, account: str) -> Base44Reader:
        token = CredentialStore().get(f"base44:{account}") or CredentialStore().get("base44")
        if not token:
            raise HarnessNotConfigured(
                "No Base44 token: set HARNESS_BASE44_TOKEN (in a cloud session "
                "with the token saved as a network secret: proxy-injected)."
            )
        return Base44Reader(Base44Client(token))

    # --- what a Superagent is, as harness items -----------------------------------------------------

    def harvest(self, exclude: list[str] | None = None) -> list[Captured]:
        items: list[Captured] = []
        for account in self.bindings():
            for agent in self._reader_factory(account).superagents():
                items += superagent_items(agent, [])
        return [i for i in items if not any(fnmatch(f"{i.kind.value}:{i.name}", p) for p in exclude or [])]

    def run_harvest(self, session: str | None = None) -> HarvestReport:
        repo = self.repo()
        report = HarvestReport()
        for account, profile in self.bindings().items():
            reader = self._reader_factory(account)
            agents = reader.superagents()
            skipped: list[str] = []
            items = [
                i
                for agent in agents
                for i in superagent_items(agent, skipped)
                if not any(fnmatch(f"{i.kind.value}:{i.name}", p) for p in repo.config.harvest_exclude)
            ]
            part = HarvestSync(repo, self.local.state("harvest", profile)).run(
                items, Origin.now(profile, session)
            )
            report.counts.update(part.counts)
            report.conflicts += part.conflicts
            report.errors += part.errors + [f"not saved (looks like a secret): {s}" for s in skipped]
            storage = repo.storage("transcripts", profile)
            with storage.batch():
                for agent in agents:
                    for conversation_id in agent.conversation_ids:
                        conversation = reader.conversation(agent, conversation_id)
                        if conversation and save_conversation(repo, profile, storage, agent, conversation):
                            report.counts["conversations saved"] += 1
            report.errors += reader.problems
        return report

    def install(
        self,
        profile_id: str,
        label: str,
        repo_root: Path | None = None,
        hooks: bool = True,
        environment: str | None = None,
        account_key: str | None = None,
    ) -> list[str]:
        if repo_root:
            self.local.save_settings(content_repo=str(Path(repo_root).resolve()))
        account_key = account_key or "default"
        profile = ProfileRegistry(self.repo()).add(
            self.tool, label, profile_id=profile_id, environment=environment or self.environment
        )
        self.bind(account_key, profile.id)
        done = [f"Base44 {account_key} -> {profile.id}"]
        if hooks:
            done.append(self.schedule())
        return done


# --- translation (what is particular to Base44) ------------------------------------------------------


def _safe(path: str, text: str, skipped: list[str]) -> bool:
    if any(path == n or path.startswith(n) for n in NEVER) or path.endswith(".env"):
        return False
    if SECRET.search(text or ""):
        skipped.append(path)
        return False
    return True


def _under(files: dict[str, str], folder: str, skipped: list[str]) -> dict[str, bytes]:
    return {
        p[len(folder) :]: t.encode("utf-8")
        for p, t in files.items()
        if p.startswith(folder) and isinstance(t, str) and _safe(p, t, skipped)
    }


def superagent_items(agent: Superagent, skipped: list[str]) -> list[Captured]:
    files, name, origin = agent.files, slugify(agent.name), f"base44 superagent {agent.id}"
    items: list[Captured] = []
    config = (agent.app.get("agents") or {}).get("your_agent") or {}
    text = lambda p: files.get(p) if isinstance(files.get(p), str) and _safe(p, files[p], skipped) else ""  # noqa: E731
    identity = "\n\n".join(
        t
        for t in (
            text(".agents/.memory/IDENTITY.md"),
            text(".agents/.memory/SOUL.md"),
            text(".agents/BOOTSTRAP.md"),
        )
        if t
    )
    skills = sorted({p.split("/")[2] for p in files if p.startswith(".agents/skills/") and p.count("/") >= 3})
    servers = sorted((_mcp_config(files).get("mcpServers") or {}).keys())
    items.append(
        Captured(
            Kind.AGENT,
            name,
            origin,
            meta={
                "agent": {
                    "name": name,
                    "description": agent.app.get("user_description") or f"Base44 Superagent {agent.name}",
                    "instructions": config.get("instructions") or "",
                    "identity": identity or None,
                    "skills": skills or None,
                    "model": config.get("model"),
                    "requires": {"connections": servers} if servers else None,
                },
                "native": {
                    "memory_config": config.get("memory_config"),
                    "tool_configs": config.get("tool_configs"),
                    "tools_permission_config": agent.app.get("tools_permission_config"),
                    "slug": agent.profile.get("slug"),
                    "lifecycle": agent.app.get("superagent_lifecycle"),
                },
            },
        )
    )
    for path in sorted(p for p in files if p.startswith(".agents/rules/")):
        if text(path):
            rule = f"{name}-rule-{slugify(Path(path).stem)}"
            items.append(Captured(Kind.INSTRUCTION, rule, origin, {f"{rule}.md": text(path).encode("utf-8")}))
    for skill in skills:
        skill_files = _under(files, f".agents/skills/{skill}/", skipped)
        if skill_files:
            items.append(Captured(Kind.SKILL, skill, origin, skill_files))
    for server in servers:
        code = _under(files, f".agents/mcps/{server}/", skipped)
        if code:
            items.append(
                Captured(
                    Kind.PLUGIN,
                    f"{name}-mcp-{server}",
                    origin,
                    code,
                    meta={"description": f"MCP server '{server}' of the Base44 Superagent {agent.name}"},
                )
            )
        items.append(
            Captured(
                Kind.CONNECTION,
                server,
                origin,
                meta={
                    "tool": TOOL,
                    "kind": "mcp",
                    "description": f"MCP server of the Base44 Superagent {agent.name}",
                },
            )
        )
    for memory in agent.memory:
        if memory.get("content") and _safe("memory", memory["content"], skipped):
            entry = f"{name}-{memory.get('id')}"
            items.append(
                Captured(
                    Kind.MEMORY,
                    entry,
                    origin,
                    {f"{entry}.md": memory["content"].encode("utf-8")},
                    meta={"subject": f"{agent.name}: {memory.get('scope') or 'memory'} memory"},
                )
            )
    for path in sorted(
        p for p in files if p.startswith((".agents/.memory/", "notes/")) and p.endswith(".md")
    ):
        if Path(path).name in ("IDENTITY.md", "SOUL.md") or not text(path):
            continue
        entry = f"{name}-{slugify(path.replace('.agents/.memory/', 'memory-'))}"
        items.append(Captured(Kind.MEMORY, entry, origin, {f"{entry}.md": text(path).encode("utf-8")}))
    app_files = _under(files, "base44/", skipped)
    app_files["entities.json"] = json.dumps(
        agent.app.get("entities") or {}, ensure_ascii=False, indent=1
    ).encode("utf-8")
    app_files[".agents/mcps/config.json"] = json.dumps(
        _mcp_config(files), ensure_ascii=False, indent=1
    ).encode()
    items.append(
        Captured(
            Kind.APP,
            name,
            origin,
            app_files,
            meta={
                "description": f"Data model of the Base44 Superagent {agent.name} (tables stay in Base44)",
                "fields": {"link": f"https://app.base44.com/superagents/{agent.id}"},
            },
        )
    )
    rest = {
        p: t
        for p, t in files.items()
        if p.startswith(".agents/")
        and p.count("/") == 1
        and p not in (".agents/BOOTSTRAP.md",)
        and isinstance(t, str)
        and _safe(p, t, skipped)
    }
    if rest:
        items.append(
            Captured(
                Kind.NATIVE,
                f"{name}-settings",
                origin,
                {f"{name}-settings/{Path(p).name}": t.encode("utf-8") for p, t in rest.items()},
            )
        )
    return items


def _mcp_config(files: dict[str, str]) -> dict[str, Any]:
    """The MCP servers a Superagent runs, with environment and header values left out (names only)."""
    try:
        config = json.loads(files.get(".agents/mcps/config.json") or "{}")
    except ValueError:
        return {}
    for server in (config.get("mcpServers") or {}).values():
        for key in ("env", "headers"):
            if isinstance(server.get(key), dict):
                server[key] = {k: "<set in Base44>" for k in server[key]}
    return config


def message_replies(messages: list[dict[str, Any]]) -> list[Reply]:
    """Base44 messages as replies: each user message opens one; assistant text and tool calls
    follow it (reasoning is left out, like thinking everywhere)."""
    replies: list[Reply] = []
    for message in messages:
        if message.get("hidden"):
            continue
        content = message.get("content") if isinstance(message.get("content"), str) else ""
        if message.get("role") == "user":
            replies.append(Reply(len(replies) + 1, "", [content.strip()]))
        elif replies and message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                replies[-1].assistant.append(
                    Reply.action(
                        str(call.get("name") or "tool"), str(call.get("arguments_string") or "")[:160]
                    )
                )
            if content.strip():
                replies[-1].assistant.append(content.strip())
    return replies


def save_conversation(repo, profile: str, storage, agent: Superagent, conversation: dict[str, Any]) -> bool:
    """One conversation: its messages kept growing by message id (the API returns the last 200),
    its log, and the files made in it. Returns whether anything changed."""
    record = SessionRecord(repo, profile, f"conversation-{conversation['id']}")
    key = record.storage_key("messages.json")
    kept = json.loads(storage.read_text(key)) if storage.exists(key) else []
    seen = {m.get("id") for m in kept}
    new = [m for m in conversation.get("messages") or [] if m.get("id") not in seen]
    if not new and record.meta_path.is_file():
        return False
    messages = kept + new
    storage.write_text(key, json.dumps(messages, ensure_ascii=False))
    files = []
    for path, text in agent.files.items():
        prefix = f"conversations/{conversation['id']}/"
        if path.startswith(prefix) and isinstance(text, str) and _safe(path, text, []):
            relative = path[len(prefix) :]
            storage.write_text(record.storage_key(f"files/{relative}"), text)
            files.append({"path": relative, "size": len(text.encode("utf-8"))})
    title = conversation.get("title") or conversation["id"]
    ConversationLog(record).write(title, message_replies(messages))
    started = to_iso(conversation.get("created_date"))
    if not record.meta_path.is_file():
        record.touch(started_at=started or now_iso(), imported_at=now_iso())
    total = (conversation.get("summary") or {}).get("message_count")
    record.touch(
        activity_at=to_iso(conversation.get("updated_date")),
        topic=title,
        transcript=key,
        agent=slugify(agent.name),
        files=files or None,
        note=(
            f"Base44 returned the last {len(conversation.get('messages') or [])} of {total} messages; "
            "earlier ones were not available"
        )
        if total and total > len(messages)
        else None,
    )
    return True
