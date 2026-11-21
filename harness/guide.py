"""The repository's guide: README.md (structure, links, dependencies, every agent with all its
parts) and sessions/README.md (every conversation), written by the engine from the content.

Nothing in them is typed by hand: they are rebuilt from the files on every save, so they are
never out of date, and a person or an agent who has never seen this repository can read them
and know where everything is and what depends on what.

Links between items are found from the content itself, the same way for every tool:
  - declared: an agent's ``skills`` / ``requires.connections``, a workflow step's ``agent``,
    an instruction's ``scope: agent:<name>``, a conversation's ``agent``, an app or plugin
    named after the agent, memory whose ``subject`` names the agent;
  - used: an item whose text names another item (a workflow naming a backend function, a
    skill naming a table) - found by searching each item's files for the other items' names;
  - settings it needs: environment variables code reads, MCP config values kept out of Git.
"""

# ruff: noqa: E501  (the Markdown it writes has long table rows)
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import yaml_io
from .documents import MarkdownDocument
from .repo import ContentRepo
from .text import slugify

TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".jsonc", ".ts", ".js", ".py", ".sh", ".txt", ".html"}
ENV_READS = re.compile(
    r"(?:Deno\.env\.get\(\s*['\"]|process\.env\.|process\.env\[['\"]|os\.environ(?:\.get)?\(?\[?['\"]|os\.getenv\(['\"])"
    r"([A-Z][A-Z0-9_]{2,})"
)


@dataclass
class Item:
    """One thing in the harness, as the guide shows it."""

    kind: str  # agent, rule, skill, workflow, plugin, connection, app, function, table, memory, conversation
    name: str
    path: str  # relative path (file or folder)
    description: str = ""
    profile: str = ""  # the profile it came from (provenance)
    agent: str = ""  # the agent it declares it belongs to
    text: str = ""  # searched for other items' names
    extra: dict[str, Any] = field(default_factory=dict)


class RepoGuide:
    README = "README.md"
    SESSIONS = "sessions/README.md"

    def __init__(self, repo: ContentRepo) -> None:
        self.repo = repo
        self.root = repo.root
        self.items: list[Item] = []

    # --- public -------------------------------------------------------------------------------

    def write(self) -> list[str]:
        """Write both guides when their content changed; returns the paths written."""
        self.load()
        written = []
        for relative, text in ((self.README, self.readme()), (self.SESSIONS, self.sessions_index())):
            path = self.root / relative
            if path.is_file() and path.read_text("utf-8") == text:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written.append(relative)
        return written

    # --- loading ------------------------------------------------------------------------------

    def load(self) -> None:
        self.items = []
        self.profiles = self._yaml("core/profiles.yaml").get("profiles") or []
        self._agents()
        self._rules()
        self._skills()
        self._workflows()
        self._plugins()
        self._connections()
        self._apps()
        self._memory()
        self._conversations()

    def _agents(self) -> None:
        for path in sorted((self.root / "core" / "agents").glob("*.yaml")):
            data = self._yaml(path)
            requires = data.get("requires") or {}
            self.items.append(
                Item(
                    "agent",
                    data.get("name") or path.stem,
                    self._rel(path),
                    _one_line(data.get("description")),
                    _source(data),
                    data.get("name") or path.stem,
                    path.read_text("utf-8"),
                    {
                        "skills": data.get("skills") or [],
                        "connections": requires.get("connections") or [],
                        "origin": data.get("origin") or "",
                        "role": data.get("role") or "",
                    },
                )
            )

    def _rules(self) -> None:
        for path in sorted((self.root / "core" / "instructions").glob("*/*.md")):
            doc = MarkdownDocument.read(path)
            scope = str(doc.meta.get("scope") or "global")
            agent = scope.split(":", 1)[1] if scope.startswith("agent:") else ""
            self.items.append(
                Item(
                    "rule",
                    path.stem,
                    self._rel(path),
                    _first_line(doc.body),
                    _source(doc.meta) or path.parent.name,
                    agent,
                    doc.body,
                    {"scope": scope},
                )
            )

    def _skills(self) -> None:
        for folder in sorted(p for p in (self.root / "core" / "skills").glob("*") if p.is_dir()):
            skill_md = folder / "SKILL.md"
            doc = MarkdownDocument.read(skill_md) if skill_md.is_file() else MarkdownDocument()
            self.items.append(
                Item(
                    "skill",
                    folder.name,
                    self._rel(folder),
                    _one_line(doc.meta.get("description")),
                    _source(doc.meta),
                    "",
                    self._folder_text(folder),
                    {"files": sorted(self._rel(p, folder) for p in folder.rglob("*") if p.is_file())},
                )
            )

    def _workflows(self) -> None:
        for path in sorted((self.root / "core" / "workflows").glob("*.yaml")):
            data = self._yaml(path)
            agents = [
                s.get("agent") for s in data.get("steps") or [] if isinstance(s, dict) and s.get("agent")
            ]
            self.items.append(
                Item(
                    "workflow",
                    data.get("name") or path.stem,
                    self._rel(path),
                    _one_line(data.get("description")),
                    _source(data),
                    agents[0] if agents else "",
                    path.read_text("utf-8"),
                    {"trigger": _one_line(data.get("trigger"))},
                )
            )

    def _plugins(self) -> None:
        for folder in sorted(p for p in (self.root / "core" / "plugins").glob("*") if p.is_dir()):
            data = self._yaml(folder / "plugin.yaml")
            self.items.append(
                Item(
                    "plugin",
                    folder.name,
                    self._rel(folder),
                    _one_line(data.get("description")),
                    _source(data),
                    "",
                    self._folder_text(folder),
                    {"settings": self._mcp_settings(folder)},
                )
            )

    def _connections(self) -> None:
        for entry in self._yaml("core/connections.yaml").get("connections") or []:
            available = entry.get("available_in") or {}
            where = ", ".join(
                f"{tool} ({', '.join(v.get('profiles') or [])})" for tool, v in available.items()
            )
            self.items.append(
                Item(
                    "connection",
                    str(entry.get("id")),
                    "core/connections.yaml",
                    _one_line(entry.get("description")),
                    _source(entry),
                    "",
                    "",
                    {"kind": entry.get("kind") or "", "where": where},
                )
            )

    def _apps(self) -> None:
        for folder in sorted(p for p in (self.root / "apps").glob("*") if p.is_dir()):
            data = self._yaml(folder / "app.yaml")
            app = Item(
                "app",
                folder.name,
                self._rel(folder),
                _one_line(data.get("purpose") or data.get("description")),
                _source(data),
                "",
                "",
                {"url": data.get("url") or ""},
            )
            self.items.append(app)
            for table in sorted((folder / "entities").glob("*")):
                self.items.append(
                    Item(
                        "table",
                        table.stem,
                        self._rel(table),
                        "",
                        app.profile,
                        "",
                        table.read_text("utf-8", errors="replace"),
                        {"app": folder.name},
                    )
                )
            manifest = {
                f.get("name"): f for f in _json(folder / "functions.json") or [] if isinstance(f, dict)
            }
            for function in sorted(p for p in (folder / "functions").glob("*") if p.is_dir()):
                text = self._folder_text(function)
                self.items.append(
                    Item(
                        "function",
                        function.name,
                        self._rel(function),
                        _code_comment(text),
                        app.profile,
                        "",
                        text,
                        {
                            "app": folder.name,
                            "settings": sorted(set(ENV_READS.findall(text))),
                            "automations": (manifest.get(function.name) or {}).get("automations") or [],
                        },
                    )
                )

    def _memory(self) -> None:
        for path in sorted((self.root / "memory").glob("*.md")):
            doc = MarkdownDocument.read(path)
            subject = str(doc.meta.get("subject") or "")
            self.items.append(
                Item(
                    "memory",
                    path.stem,
                    self._rel(path),
                    subject or _first_line(doc.body),
                    _source(doc.meta),
                    "",
                    doc.body,
                    {"subject": subject},
                )
            )

    def _conversations(self) -> None:
        for meta_path in sorted((self.root / "sessions").glob("*/*/meta.yaml")):
            folder = meta_path.parent
            meta = self._yaml(meta_path)
            summary = folder / "summary.md"
            topic = meta.get("topic") or self._summary_goal(summary) or self._first_request(folder / "log.md")
            self.items.append(
                Item(
                    "conversation",
                    folder.name,
                    self._rel(folder),
                    _one_line(topic)[:140],
                    str(meta.get("profile") or folder.parent.name),
                    str(meta.get("agent") or ""),
                    "",
                    {
                        "started": str(meta.get("started_at") or "")[:10],
                        "last": str(meta.get("last_activity_at") or meta.get("activity_at") or "")[:10],
                        "project": meta.get("project") or "",
                        "summary": summary.is_file(),
                        "log": (folder / "log.md").is_file(),
                        "transcript": meta.get("transcript") or "",
                        "note": meta.get("note") or "",
                    },
                )
            )

    # --- the connector's index (harness_find) ---------------------------------------------------

    def index_entries(self) -> list[dict[str, Any]]:
        """Items only the guide describes (a backend function, a table), for harness_find."""
        entries = []
        for item in self._of("function") + self._of("table"):
            path = item.path
            if item.kind == "function":  # a readable file, not the folder: its entry point
                files = sorted(p for p in (self.root / item.path).rglob("*") if p.is_file())
                main = next((p for p in files if p.stem in ("main", "index")), files[0] if files else None)
                path = self._rel(main) if main else item.path
            entry = {"kind": item.kind, "name": item.name, "path": path, "app": item.extra["app"]}
            if item.description:
                entry["description"] = item.description[:300]
            if item.profile:
                entry["profile"] = item.profile
            if item.extra.get("settings"):
                entry["needs_settings"] = item.extra["settings"]
            entries.append(entry)
        return entries

    def annotate(self, entries: list[dict[str, Any]]) -> None:
        """Add to index entries the agent they belong to and what they use / who uses them."""
        by_path = {i.path: i for i in self.items}
        agent_of: dict[int, str] = {}
        for agent in self._of("agent"):
            for group in self.belongs(agent).values():
                for item in group:
                    agent_of.setdefault(id(item), agent.name)
        callers = self._of("workflow") + self._of("skill") + self._of("function")
        for entry in entries:
            path = str(entry.get("path") or "")
            item = by_path.get(path) or by_path.get(path.rsplit("/", 1)[0])  # a function's / skill's file
            if item is None or entry.get("kind") == "file":
                continue
            if id(item) in agent_of and not entry.get("agent"):
                entry["agent"] = agent_of[id(item)]
            if item.kind in ("workflow", "skill", "function"):
                used = self.uses(item)
                if used:
                    entry["uses"] = [f"{u.kind}:{u.name}" for u in used]
            if item.kind in ("function", "table"):
                users = self.mentions(item, callers)
                if users:
                    entry["used_by"] = [u.path for u in users]

    # --- links ---------------------------------------------------------------------------------

    def _of(self, kind: str) -> list[Item]:
        return [i for i in self.items if i.kind == kind]

    def belongs(self, agent: Item) -> dict[str, list[Item]]:
        """Everything that declares it is part of ``agent``."""
        name = agent.name
        names = {name, name.replace("-", "_")}
        parts: dict[str, list[Item]] = defaultdict(list)
        for item in self.items:
            if item is agent:
                continue
            declared = item.agent in names
            if item.kind == "skill" and item.name in agent.extra["skills"]:
                declared = True
            if item.kind == "connection" and item.name in agent.extra["connections"]:
                declared = True
            if item.kind in ("app", "plugin") and (item.name == name or item.name.startswith(f"{name}-")):
                declared = True
            if item.kind in ("table", "function") and item.extra.get("app") == name:
                declared = True
            if item.kind == "memory" and slugify(item.extra["subject"].split(":", 1)[0]) == name:
                declared = True
            if declared:
                parts[item.kind].append(item)
        return parts

    def mentions(self, item: Item, among: list[Item] | None = None) -> list[Item]:
        """Items whose text names ``item`` (by its exact name, as a whole word)."""
        if len(item.name) < 4:
            return []
        variants = {item.name, item.name.replace("-", "_")}
        pattern = re.compile(
            r"(?<![\w-])(" + "|".join(re.escape(v) for v in variants) + r")(?![\w-])",
            re.IGNORECASE if item.kind == "agent" else 0,
        )
        return [
            other
            for other in (among if among is not None else self.items)
            if other is not item and other.text and pattern.search(other.text)
        ]

    def uses(self, item: Item) -> list[Item]:
        """The functions, tables, skills and connections ``item``'s text names."""
        targets = [i for i in self.items if i.kind in ("function", "table", "skill") and i is not item]
        return [t for t in targets if item in self.mentions(t, [item])]

    # --- README --------------------------------------------------------------------------------

    def readme(self) -> str:
        from . import __version__

        owner = (
            (self.repo.config.data.get("owner") or "").strip() if hasattr(self.repo.config, "data") else ""
        )
        out = [
            f"# {owner + chr(39) + 's ' if owner else ''}AI harness",
            "",
            f"_Written by the [my-harness](https://github.com/chanaza/my-harness) engine (v{__version__}) "
            "from this repository's content, on every save. Do not edit it: it is rebuilt. "
            "Every conversation is listed in [sessions/README.md](sessions/README.md)._",
            "",
        ]
        out += STATIC_START.splitlines()
        out += self._profiles_section()
        out += STATIC_LINKS.splitlines()
        out += self._agents_section()
        out += self._other_section()
        out += self._settings_section()
        out += STATIC_END.splitlines()
        return "\n".join(out).rstrip() + "\n"

    def _profiles_section(self) -> list[str]:
        out = [
            "## Accounts (profiles)",
            "",
            "Every item records the profile it came from (`provenance.source.profile`). "
            "Full transcripts are kept outside the main branch, where the last column says.",
            "",
            "| Profile | Tool | Account | Runs | Conversations | Full transcripts kept in |",
            "|---|---|---|---|---|---|",
        ]
        counts = defaultdict(int)
        for c in self._of("conversation"):
            counts[c.profile] += 1
        for p in self.profiles:
            pid = p.get("id")
            where = p.get("environment") or ""
            if p.get("machine"):
                where += f" ({p['machine']})"
            out.append(
                f"| `{pid}` | {p.get('tool')} | {p.get('label')} | {where} | {counts.get(pid, 0)} | "
                f"{self._transcripts_place(pid)} |"
            )
        return out + [""]

    def _transcripts_place(self, profile: str) -> str:
        try:
            settings = self.repo.config.storage_settings("transcripts", profile)
        except Exception:  # noqa: BLE001 - a guide never fails over one setting
            return "not set"
        if settings.get("backend") == "git":
            return f"branch `{settings.get('branch', 'transcripts')}` of this repository"
        return f"folder `{settings.get('path')}` (on that computer)"

    def _agents_section(self) -> list[str]:
        agents = self._of("agent")
        out = [
            "## Agents, with everything that belongs to them",
            "",
            "Each agent's parts live in the shared folders (so a skill or a connection can serve "
            "several agents); this section gathers them per agent. **Declared** = the file says it "
            "belongs to the agent. **Uses** = its text names that function / table / skill / "
            "connection. **Mentioned in** = other files that name it (often the explanation of why "
            "or how). To rebuild an agent in another tool, take every path in its section.",
            "",
            "Agents: " + ", ".join(f"[{a.name}](#agent-{a.name})" for a in agents),
            "",
        ]
        for agent in agents:
            out += self._agent(agent)
        return out

    def _agent(self, agent: Item) -> list[str]:
        parts = self.belongs(agent)
        out = [f'<a id="agent-{agent.name}"></a>', f"### Agent `{agent.name}`", ""]
        if agent.description:
            out.append(agent.description)
            out.append("")
        out.append(
            f"- **Definition** (instructions, identity, model, native settings): `{agent.path}` "
            f"- from `{agent.profile}`"
            + (f", originally {agent.extra['origin']}" if agent.extra["origin"] else "")
        )
        for rule in parts.get("rule", []):
            out.append(f"- **Rule** (always on for this agent): `{rule.path}` - {rule.description}")
        for skill in parts.get("skill", []):
            out.append(f"- **Skill**: `{skill.path}/` - {skill.description[:160]}" + self._uses(skill))
        for workflow in parts.get("workflow", []):
            trigger = f" - runs {workflow.extra['trigger']}" if workflow.extra["trigger"] else ""
            out.append(f"- **Workflow**: `{workflow.path}`{trigger}" + self._uses(workflow))
        for plugin in parts.get("plugin", []):
            settings = (
                f"; needs settings {', '.join(plugin.extra['settings'])}" if plugin.extra["settings"] else ""
            )
            out.append(f"- **Plugin / MCP server**: `{plugin.path}/` - {plugin.description}{settings}")
        for connection in parts.get("connection", []):
            out.append(
                f"- **Connection**: `{connection.name}` ({connection.extra['kind']}) - {connection.description}"
            )
        for app in parts.get("app", []):
            out.append(
                f"- **App**: `{app.path}/` - {app.description}"
                + (f" ({app.extra['url']})" if app.extra["url"] else "")
            )
            tables = parts.get("table", [])
            if tables:
                out.append("  - Tables (`entities/`: structure only; the rows stay in the tool):")
                code = self._of("function") + self._of("workflow") + self._of("skill")
                for table in tables:
                    users = self.mentions(table, code)
                    used = (
                        ", ".join(f"`{u.name}`" for u in users)
                        if users
                        else "nothing here names it (the agent uses it directly)"
                    )
                    out.append(f"    - `{table.name}` - used by {used}")
            for function in parts.get("function", []):
                out += self._function(function)
        out += self._related(agent, parts)
        memory = parts.get("memory", [])
        if memory:
            out.append(f"- **Memory** ({len(memory)} files, what the agent learned):")
            out += [f"  - `{m.path}` - {_first_line(m.text)[:110]}" for m in memory]
        conversations = sorted(parts.get("conversation", []), key=lambda c: c.extra["last"], reverse=True)
        if conversations:
            out.append(
                f"- **Conversations / runs** ({len(conversations)}; all listed in "
                f"[sessions/README.md](sessions/README.md)). Latest:"
            )
            out += [f"  - {c.extra['last']} `{c.path}/` - {c.description}" for c in conversations[:5]]
        return out + [""]

    def _function(self, function: Item) -> list[str]:
        callers = [
            i
            for i in self.mentions(function, self._of("workflow") + self._of("skill") + self._of("function"))
        ]
        described = self.mentions(function, self._of("memory"))
        line = f"  - Backend function `{function.name}`: `{function.path}/`"
        if function.description:
            line += f" - {function.description[:150]}"
        out = [line]
        if callers:
            out.append("    - called by: " + ", ".join(f"`{c.path}`" for c in callers))
        elif function.extra["automations"]:
            out.append(f"    - run by the tool's automations: {function.extra['automations']}")
        else:
            out.append(
                "    - not called by any workflow here: it is called from outside (a webhook or "
                "the agent itself) - see where it is described below"
            )
        if described:
            out.append("    - described in: " + ", ".join(f"`{d.path}`" for d in described[:6]))
        if function.extra["settings"]:
            out.append(
                "    - needs settings (kept in the tool, not in Git): "
                + ", ".join(f"`{s}`" for s in function.extra["settings"])
            )
        used = [u for u in self.uses(function) if u.kind == "table"]
        if used:
            out.append("    - reads/writes tables: " + ", ".join(f"`{u.name}`" for u in used))
        return out

    def _related(self, agent: Item, parts: dict[str, list[Item]]) -> list[str]:
        own = {id(i) for group in parts.values() for i in group}
        related = [
            i
            for i in self.mentions(agent)
            if id(i) not in own and i.kind in ("skill", "rule", "workflow", "plugin")
        ]
        related += [i for i in self.mentions(agent, self._of("memory")) if id(i) not in own]
        if not related:
            return []
        return ["- **Related** (not declared as its part, but names it):"] + [
            f"  - {i.kind} `{i.path}` (from `{i.profile}`) - {i.description[:120]}" for i in related[:12]
        ]

    def _uses(self, item: Item) -> str:
        used = self.uses(item)
        return f"; uses {', '.join(f'{u.kind} `{u.name}`' for u in used)}" if used else ""

    def _other_section(self) -> list[str]:
        claimed = {
            id(i) for agent in self._of("agent") for group in self.belongs(agent).values() for i in group
        }
        out = ["## Everything not tied to an agent", ""]
        rules = [r for r in self._of("rule") if not r.agent]
        if rules:
            out.append(
                "**Instructions** (how every agent of that account should behave; scope `global` = the "
                "whole account, `project:<name>` = one project):"
            )
            out += [f"- `{r.path}` - `{r.profile}`, scope `{r.extra['scope']}`" for r in rules]
            out.append("")
        for kind, title in (
            ("skill", "Skills"),
            ("workflow", "Workflows"),
            ("plugin", "Plugins"),
            ("app", "Apps"),
        ):
            loose = [i for i in self._of(kind) if id(i) not in claimed]
            if loose:
                out.append(f"**{title}:**")
                out += [f"- `{i.path}` - {i.description[:140]} (from `{i.profile}`)" for i in loose]
                out.append("")
        connections = [c for c in self._of("connection") if id(c) not in claimed]
        if connections:
            out.append(
                "**Connections** (`core/connections.yaml`; what each tool can connect to; sign-ins stay in the tool):"
            )
            out += [
                f"- `{c.name}` ({c.extra['kind']}) - {c.description[:100]} - in {c.extra['where']}"
                for c in connections
            ]
            out.append("")
        memory = [m for m in self._of("memory") if id(m) not in claimed]
        if memory:
            out.append(
                f"**Memory** ({len(memory)} files not tied to one agent): `memory/`, one fact or "
                "decision per file; its `provenance` says which account and conversation it came from."
            )
            out.append("")
        return out

    def _settings_section(self) -> list[str]:
        needed: dict[str, set[str]] = defaultdict(set)
        for item in self._of("function") + self._of("plugin"):
            for name in item.extra.get("settings") or []:
                needed[name].add(item.path)
        out = [
            "## Secrets and settings (never in Git)",
            "",
            "Passwords, tokens and keys are never stored here, not even in this private repository. "
            "Only their names are, so you know what to set up again:",
            "",
            "- In the tool itself (for example a Base44 Superagent's secrets, a monday agent's connectors): "
            "the code below reads them by name.",
            "- For the harness engine: on a computer, the system's password store (Windows Credential "
            "Manager); in a cloud session, the environment's network secrets; the harness connector's "
            "keys are Cloudflare Worker secrets.",
            "",
        ]
        if needed:
            out += ["| Setting | Needed by |", "|---|---|"]
            out += [
                f"| `{name}` | {', '.join(f'`{p}`' for p in sorted(paths))} |"
                for name, paths in sorted(needed.items())
            ]
            out.append("")
        return out

    # --- sessions/README.md ---------------------------------------------------------------------

    def sessions_index(self) -> str:
        out = [
            "# Conversations",
            "",
            "_Written by the engine on every save; do not edit._",
            "",
            "Every conversation and agent run saved in this harness, newest first, per account. "
            "To continue one anywhere: read its `summary.md` (the state at that point), then the "
            "replies in its `log.md` after that summary. The full original transcript is outside the "
            "main branch (see the account table in [README.md](../README.md)); its path is "
            "`transcript:` in the conversation's `meta.yaml`.",
            "",
        ]
        by_profile: dict[str, list[Item]] = defaultdict(list)
        for c in self._of("conversation"):
            by_profile[c.profile].append(c)
        for profile in sorted(by_profile):
            out += [
                f"## `{profile}` ({len(by_profile[profile])})",
                "",
                "| Last active | Started | Topic | Agent / project | Summary | Folder |",
                "|---|---|---|---|---|---|",
            ]
            for c in sorted(
                by_profile[profile], key=lambda c: (c.extra["last"], c.extra["started"]), reverse=True
            ):
                topic = (c.description or "-").replace("|", "/")
                if c.extra["note"]:
                    topic += f" _({c.extra['note']})_"
                owner = c.agent or c.extra["project"] or ""
                out.append(
                    f"| {c.extra['last']} | {c.extra['started']} | {topic} | {owner} | "
                    f"{'yes' if c.extra['summary'] else '-'} | [{c.name}]({Path(c.path).relative_to('sessions').as_posix()}/) |"
                )
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    # --- helpers --------------------------------------------------------------------------------

    def _yaml(self, path: str | Path) -> dict[str, Any]:
        path = self.root / path if isinstance(path, str) else path
        try:
            data = yaml_io.load(path.read_text("utf-8")) if path.is_file() else None
        except Exception:  # noqa: BLE001 - a broken file is reported by `harness validate`, not here
            data = None
        return data if isinstance(data, dict) else {}

    def _rel(self, path: Path, base: Path | None = None) -> str:
        return path.relative_to(base or self.root).as_posix()

    def _folder_text(self, folder: Path) -> str:
        return "\n".join(
            p.read_text("utf-8", errors="replace")
            for p in sorted(folder.rglob("*"))
            if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES and p.stat().st_size < 400_000
        )

    def _mcp_settings(self, folder: Path) -> list[str]:
        names = set(ENV_READS.findall(self._folder_text(folder)))
        for config in folder.glob("*config*.json"):
            for server in ((_json(config) or {}).get("mcpServers") or {}).values():
                names |= set((server.get("env") or {}).keys()) | set((server.get("headers") or {}).keys())
        return sorted(names)

    @staticmethod
    def _summary_goal(path: Path) -> str:
        if not path.is_file():
            return ""
        body = MarkdownDocument.read(path).body
        match = re.search(r"^## Goal\s*\n+(.+)", body, re.MULTILINE)
        return match.group(1) if match else ""

    @staticmethod
    def _first_request(path: Path) -> str:
        if not path.is_file():
            return ""
        match = re.search(r"^## User\s*\n+(.+)", path.read_text("utf-8", errors="replace"), re.MULTILINE)
        return match.group(1) if match else ""


def _source(meta: dict[str, Any]) -> str:
    return str(((meta.get("provenance") or {}).get("source") or {}).get("profile") or "")


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if line and line != "---":
            return _one_line(line)
    return ""


def _code_comment(text: str) -> str:
    """The opening comment of a code file: what it is, in its author's words."""
    lines = []
    for line in text.splitlines()[:8]:
        stripped = line.strip()
        if stripped.startswith(("//", "/**", "*", "#")) and not stripped.startswith("#!"):
            words = stripped.lstrip("/*# ").strip()
            if words:
                lines.append(words)
        elif lines:
            break
    return _one_line(" ".join(lines))


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text("utf-8")) if path.is_file() else None
    except ValueError:
        return None


STATIC_START = """\
## Start here

This repository keeps everything built around AI tools - agents, their instructions and skills,
workflows, apps, memory, and every conversation - outside any single tool, so work can move to
another tool at any time. A person or an agent reading this file should be able to find anything.

**Three common tasks:**

1. **Continue a conversation** in any tool: find it in [sessions/README.md](sessions/README.md)
   (by date, topic, agent or project). Read its `summary.md`, then the replies in `log.md` after
   that summary. That is the whole state; the full raw transcript is only needed for detail
   (where it is: the account table below, path in `meta.yaml` under `transcript:`).
2. **Rebuild an agent** in another tool: go to its section under "Agents" below. Take its
   definition (instructions and identity), its rules, skills, workflows, connections, app
   (tables and backend code) and memory - every path is listed there - and set up again the
   secrets named in "Secrets and settings".
3. **Find anything else**: the sections below list every item with its path. Through the harness
   connector, `harness_find` searches everything by meaning; on a computer, search the files.

## How the repository is organised

| Folder | What is in it | Format |
|---|---|---|
| `core/agents/` | Agent definitions: instructions, identity, model, skills and connections it uses, the tool's own settings under `native:` | one YAML per agent |
| `core/instructions/<profile>/` | Rules and standing instructions, per account. `scope: global` = the whole account; `agent:<name>` = that agent only; `project:<name>` = one project | Markdown with front matter |
| `core/skills/<name>/` | Skills: `SKILL.md` (when to use it, how) plus scripts and references | folder per skill |
| `core/workflows/` | Scheduled and triggered tasks: when it runs (`trigger`), which agent does it (`steps[].agent`), the tool's full definition under `native:` | one YAML per workflow |
| `core/plugins/<name>/` | Plugins and MCP servers that were built (their code), with `plugin.yaml` | folder per plugin |
| `core/connections.yaml` | Every connector / MCP server, which tools and accounts have it. Sign-ins stay in the tool | one file |
| `core/profiles.yaml` | The accounts that feed this harness (tool + account) | one file |
| `core/profile/`, `core/projects/` | Who the user is; projects with their instructions and knowledge | |
| `apps/<name>/` | Apps built in tools: `app.yaml`, table structures (`entities/`), backend code (`functions/`), pages. Table rows stay in the tool | folder per app |
| `memory/` | Facts, decisions and preferences learned; `subject` says what it is about | one Markdown per fact |
| `sessions/<profile>/<id>/` | One folder per conversation or agent run: `summary.md`, `log.md` (word for word), `meta.yaml`, files made in it | see [sessions/README.md](sessions/README.md) |
| `native/<profile>/` | A tool's own settings that no other tool understands, kept as they are | as in the tool |
| `assets/` | Reference files (examples, decks, designs) | folder per asset |
| `connector/` | Generated for the harness connector (search index, instructions it serves) | generated |
| `inbox/` | What tools sent, waiting to be filed; `inbox/conflicts/` = versions that clash | temporary |
| `harness.config.yaml` | Settings of this harness | YAML |

**Why `core/` and the rest:** `core/` is what makes agents behave as they do (definitions, rules,
skills, workflows, plugins, connections) - portable between tools, and changed only with the
user's approval. Outside it is what accumulates (memory, conversations), what was built (apps,
assets), and what is tool-specific (`native/`).

**Outside this branch:** full raw transcripts (a branch named `transcripts`, or a cloud-synced
folder - per account, below); secrets (never in Git - see the end of this file).
"""

STATIC_LINKS = """\
## How files refer to each other

| Field | In | Means |
|---|---|---|
| `provenance.source.profile` | every item | the account it came from (`core/profiles.yaml`); `updates` lists later changes |
| `origin` | items | where in the tool it came from (for example `base44 superagent <id>`, `monday agent <id>`) |
| `skills`, `requires.connections` | agent | the skills and connections the agent uses |
| `steps[].agent` | workflow | the agent that runs it |
| `scope: agent:<name>` | instruction | a rule of that agent only |
| `agent`, `project` | conversation `meta.yaml` | the agent or project of the conversation |
| `transcript` | conversation `meta.yaml` | the full transcript's path in transcript storage |
| `native.<profile>` | agent, workflow | the tool's own full record, kept as it was |
| `apps/<agent>/`, `core/plugins/<agent>-...` | names | an app or plugin named after an agent belongs to it |

Names inside text are links too: a workflow whose instructions say "call ingestCalendarInvites"
uses that backend function. The agent sections below list these.
"""

STATIC_END = """\
## Changing this repository

Content is written by the engine and the tools' adapters, never by hand: a hand edit can be
overwritten or lose its provenance. To bring in a tool: `python -m harness harvest <tool>`; tools
that cannot reach Git save through the harness connector. Check the repository with
`python -m harness validate`.
"""
