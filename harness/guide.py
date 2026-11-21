"""The repository's guide: README.md, written by the engine from the content on every save.

It explains the logic of the structure and shows a few real examples, one of each kind (an
agent and its parts, a workflow that calls a backend function that writes a table, a rule of
one agent, a conversation and how to continue it...). Its size does not grow with the content:
the complete list of everything, with its links, is the connector's index (connector/index.json),
which the README teaches how to search.

Links between items are found from the content itself, the same way for every tool:
  - declared: an agent's ``skills`` / ``requires.connections``, a workflow step's ``agent``,
    an instruction's ``scope: agent:<name>``, a conversation's ``agent``, an app or plugin
    named after the agent, memory whose ``subject`` names the agent;
  - used: an item whose text names another item (a workflow naming a backend function, a
    rule telling the agent to call one, a function naming a table); a webhook of the tool
    calling a function;
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

TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".jsonc", ".ts", ".js", ".py", ".sh", ".txt", ".html"}
SHELL_VARS = re.compile(r"\$\{?([A-Z][A-Z0-9_]{3,})\}?")  # a workflow's $ACCESS_TOKEN
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
    #: Written by engine 0.28.0 and no longer (it grew with the content): removed when found.
    RETIRED = ("sessions/README.md",)

    def __init__(self, repo: ContentRepo) -> None:
        self.repo = repo
        self.root = repo.root
        self.items: list[Item] = []

    # --- public -------------------------------------------------------------------------------

    def write(self) -> list[str]:
        """Write README.md when its content changed; returns the paths written or removed."""
        self.load()
        written = []
        for relative in self.RETIRED:
            path = self.root / relative
            if path.is_file() and "_Written by the engine" in path.read_text("utf-8"):
                path.unlink()
                written.append(relative)
        path, text = self.root / self.README, self.readme()
        if not (path.is_file() and path.read_text("utf-8") == text):
            path.write_text(text, encoding="utf-8")
            written.append(self.README)
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
            agent = str(
                doc.meta.get("agent") or (scope.split(":", 1)[1] if scope.startswith("agent:") else "")
            )
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
                    str(doc.meta.get("agent") or ""),
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
                    {"trigger": _one_line(data.get("trigger")), "status": _status(data)},
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
                    str(data.get("agent") or ""),
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
                str(data.get("agent") or ""),
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
                        app.agent,
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
                        app.agent,
                        text,
                        {
                            "app": folder.name,
                            "settings": sorted(set(ENV_READS.findall(text))),
                            "automations": (manifest.get(function.name) or {}).get("automations") or [],
                            "webhooks": (manifest.get(function.name) or {}).get("webhooks") or [],
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
                    str(doc.meta.get("agent") or ""),
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
                        "summary_reply": meta.get("summary_reply"),
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
            if item.extra.get("webhooks"):
                entry["called_from_outside"] = [
                    f"webhook on {', '.join(w.get('events') or [])}: {w.get('description') or ''}".strip(": ")
                    + (f" (OFF since {str(w['off_since'])[:10]})" if w.get("off_since") else "")
                    for w in item.extra["webhooks"]
                ]
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
        callers = self.callers()
        explainers = self._of("memory")
        for entry in entries:
            path = str(entry.get("path") or "")
            item = by_path.get(path) or by_path.get(path.rsplit("/", 1)[0])  # a function's / skill's file
            if item is None or entry.get("kind") == "file":
                continue
            if id(item) in agent_of and not entry.get("agent"):
                entry["agent"] = agent_of[id(item)]
            elif not entry.get("agent"):  # built for an agent elsewhere, e.g. a skill named after it
                named = [
                    a.name for a in self._of("agent") if len(a.name) >= 4 and a.name in item.name.lower()
                ]
                if named:
                    entry["for_agent"] = named[0]
            if item.kind in ("workflow", "skill", "function"):
                used = self.uses(item)
                if used:
                    entry["uses"] = [f"{u.kind}:{u.name}" for u in used]
            if item.kind in ("function", "table"):
                owner = agent_of.get(id(item))  # a name like "User" also appears in other agents' files
                users = [u for u in self.mentions(item, callers) if agent_of.get(id(u)) in (None, owner)]
                if users:
                    entry["used_by"] = [u.path for u in users]
                elif item.kind == "function" and not entry.get("called_from_outside"):
                    entry["called_from_outside"] = [
                        "nothing in this repository calls it: another service or the agent itself does "
                        "(see the comment at the top of the code, and explained_in)"
                    ]
            if item.kind == "function":
                explained = self.mentions(item, explainers)
                if explained:
                    entry["explained_in"] = [m.path for m in explained[:8]]
            if item.kind == "workflow":
                settings = sorted(set(SHELL_VARS.findall(item.text)))
                if settings:
                    entry["needs_settings"] = settings
                if item.extra["trigger"]:
                    entry["runs"] = item.extra["trigger"]
                if item.extra["status"]:
                    entry["status"] = item.extra["status"]

    # --- links ---------------------------------------------------------------------------------

    def _of(self, kind: str) -> list[Item]:
        return [i for i in self.items if i.kind == kind]

    def belongs(self, agent: Item) -> dict[str, list[Item]]:
        """Everything that declares it is part of ``agent``: its own ``agent`` field (written by the
        engine for every item a tool says belongs to an agent), the skills and connections the agent
        lists, a workflow step's agent, a conversation's agent."""
        names = {agent.name, agent.name.replace("-", "_")}
        parts: dict[str, list[Item]] = defaultdict(list)
        for item in self.items:
            if item is agent:
                continue
            declared = (
                item.agent in names
                or (item.kind == "skill" and item.name in agent.extra["skills"])
                or (item.kind == "connection" and item.name in agent.extra["connections"])
            )
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

    def callers(self) -> list[Item]:
        """What can call a function or use a table: workflows, skills, other functions, and the
        rules that tell an agent to call it."""
        return self._of("workflow") + self._of("skill") + self._of("function") + self._of("rule")

    def uses(self, item: Item) -> list[Item]:
        """The functions, tables, skills and connections ``item``'s text names."""
        targets = [i for i in self.items if i.kind in ("function", "table", "skill") and i is not item]
        return [t for t in targets if item in self.mentions(t, [item])]

    # --- README --------------------------------------------------------------------------------

    def readme(self) -> str:
        from . import __version__

        owner = str(self.repo.config.data.get("owner") or "").strip()
        out = [
            f"# {owner}'s AI harness" if owner else "# AI harness",
            "",
            f"_Written by the [my-harness](https://github.com/chanaza/my-harness) engine (v{__version__}) "
            "from this repository, on every save. Do not edit it: it is rebuilt. Its size stays the "
            "same however much is saved: the full list of everything is the index (see below)._",
            "",
        ]
        out += STATIC_START.splitlines()
        out += self._examples()
        out += STATIC_FIND.splitlines()
        out += self._accounts()
        out += STATIC_END.splitlines()
        return "\n".join(out).rstrip() + "\n"

    def _examples(self) -> list[str]:
        """One real example of each kind of thing and link, taken from this repository."""
        examples = [
            self._example_agent(),
            self._example_chain(),
            self._example_outside(),
            self._example_rule(),
            self._example_two_tools(),
            self._example_conversation(),
            self._example_setting(),
        ]
        examples = [e for e in examples if e]
        if not examples:
            return []
        out = [
            "## Examples from this harness",
            "",
            "Real items, one of each kind, to show how the pieces fit. Everything else of the "
            "same kind follows the same pattern.",
            "",
        ]
        for number, lines in enumerate(examples, 1):
            out += [f"{number}. {lines[0]}"] + [f"   {line}" for line in lines[1:]] + [""]
        return out

    def _example_agent(self) -> list[str]:
        agents = self._of("agent")
        if not agents:
            return []
        agent = max(agents, key=lambda a: (len(self.belongs(a)), a.name))
        parts = self.belongs(agent)
        lines = [
            f"**An agent and its parts.** `{agent.name}` (from `{agent.profile}`) is defined in "
            f"`{agent.path}`. Its other parts sit in the shared folders and point back to it:"
        ]
        labels = (
            ("rule", "a rule only it follows"),
            ("skill", "a skill it lists"),
            ("workflow", "a workflow it runs"),
            ("plugin", "a plugin it runs"),
            ("connection", "a connection it needs"),
            ("app", "its app"),
            ("memory", "memory about it"),
            ("conversation", "a conversation with it"),
        )
        for kind, label in labels:
            group = parts.get(kind) or []
            if group:
                more = f" (and {len(group) - 1} more)" if len(group) > 1 else ""
                where = (
                    f"`{group[0].name}` in `{group[0].path}`"
                    if kind == "connection"
                    else f"`{group[0].path}`"
                )
                lines.append(f"- {label}: {where}{more}")
        if len(str(self._yaml(agent.path).get("instructions") or "")) < 200:
            lines.append(
                "- its `instructions` field is short: what it really does is in its "
                "identity, rules and memory."
            )
        lines.append(f'To list all its parts: search the index for `"agent": "{agent.name}"`.')
        return lines

    def _example_chain(self) -> list[str]:
        callers = self._of("workflow") + self._of("skill")
        for function in self._of("function"):
            users = self.mentions(function, callers)
            tables = [u for u in self.uses(function) if u.kind == "table"]
            if users and tables:
                caller = users[0]
                runs = f" (runs {caller.extra['trigger']})" if caller.extra.get("trigger") else ""
                return [
                    f"**What calls what.** The {caller.kind} `{caller.path}`{runs} names the backend "
                    f"function `{function.name}` (`{function.path}/`), which writes the table "
                    f"`{tables[0].name}` (`{tables[0].path}`; its rows stay in the tool).",
                    "In the index this is `uses` on the workflow and `used_by` on the function.",
                ]
        return []

    def _example_outside(self) -> list[str]:
        for function in self._of("function"):
            if self.mentions(function, self.callers()):
                continue
            explained = self.mentions(function, self._of("memory"))
            hooks = function.extra.get("webhooks") or []
            if hooks or explained:
                how = (
                    f"the tool calls it (a webhook on {', '.join(hooks[0].get('events') or [])})"
                    if hooks
                    else "something outside this repository calls it"
                )
                lines = [
                    f"**Called from outside.** Nothing here calls `{function.name}` "
                    f"(`{function.path}/`): {how}."
                ]
                if explained:
                    lines.append(
                        f"How it fits is explained in `{explained[0].path}`. In the index: "
                        "`called_from_outside`, `explained_in`."
                    )
                return lines
        return []

    def _example_rule(self) -> list[str]:
        rules = [r for r in self._of("rule") if r.agent]
        for rule in rules:
            used = [u for u in self.uses(rule) if u.kind == "function"]
            calls = f" It tells the agent to call `{used[0].name}`." if used else ""
            return [
                f"**A rule of one agent.** `{rule.path}` has `scope: {rule.extra['scope']}`: only "
                f"that agent follows it.{calls} Rules for a whole account have `scope: global`."
            ]
        return []

    def _example_two_tools(self) -> list[str]:
        for agent in self._of("agent"):
            for other in self.items:
                if (
                    other.kind in ("skill", "agent", "workflow")
                    and other is not agent
                    and agent.name.lower() in other.name.lower()
                    and other.profile
                    and other.profile != agent.profile
                ):
                    return [
                        f"**One agent, two tools.** `{agent.name}` was defined in `{agent.profile}` "
                        f"(`{agent.path}`); the {other.kind} `{other.path}` (from `{other.profile}`) "
                        "does its work in another tool. Search for the name to find both."
                    ]
        return []

    def _example_conversation(self) -> list[str]:
        conversations = [c for c in self._of("conversation") if c.extra["summary"] and c.extra["log"]]
        if not conversations:
            return []
        c = max(conversations, key=lambda c: (bool(c.extra.get("summary_reply")), c.extra["last"]))
        upto = (
            f"the state up to reply {c.extra['summary_reply']} (`summary_reply` in `meta.yaml`)"
            if c.extra.get("summary_reply")
            else "the state when it was written"
        )
        return [
            f"**A conversation, and how to continue it.** `{c.path}/` ({c.extra['last']}): "
            f"`summary.md` is {upto}; `log.md` has every reply word for word - read the replies "
            "after that. Files made in it and the full raw transcript are where its account "
            "keeps them (see Accounts)."
        ]

    def _example_setting(self) -> list[str]:
        for function in self._of("function"):
            if function.extra.get("settings"):
                names = ", ".join(f"`{s}`" for s in function.extra["settings"][:3])
                return [
                    f"**A secret a part needs.** `{function.path}/` reads {names}. The value is never "
                    "in Git: set it again in the tool. In the index: `needs_settings`."
                ]
        return []

    def _accounts(self) -> list[str]:
        from .adapters import adapters

        out = [
            "## Accounts",
            "",
            "Every item records the account it came from (`provenance.source.profile`).",
            "",
            "| Account (profile) | Tool | Runs on | Full transcripts and conversation files |",
            "|---|---|---|---|",
        ]
        tools: list[str] = []
        for p in self.profiles:
            where = str(p.get("environment") or "") + (f" ({p['machine']})" if p.get("machine") else "")
            out.append(
                f"| `{p.get('id')}` | {p.get('tool')} | {where} | {self._transcripts_place(p.get('id'))} |"
            )
            if p.get("tool") not in tools:
                tools.append(p.get("tool"))
        kept = [(tool, getattr(adapters.kind(tool), "kept_in_tool", ())) for tool in tools]
        kept = [(tool, notes) for tool, notes in kept if notes]
        if kept:
            out += ["", "**Not saved - stays in the tool** (to rebuild there, set these up again by hand):"]
            out += [f"- {tool}: " + "; ".join(notes) + "." for tool, notes in kept]
        return out + [""]

    def _transcripts_place(self, profile: str) -> str:
        try:
            settings = self.repo.config.storage_settings("transcripts", profile)
        except Exception:  # noqa: BLE001 - a guide never fails over one setting
            return "not set"
        if settings.get("backend") == "git":
            return f"branch `{settings.get('branch', 'transcripts')}` of this repository"
        return f"folder `{settings.get('path')}` (on that computer)"

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


def _status(data: dict[str, Any]) -> str:
    """A workflow's status as its tool keeps it (native.<profile>.status / enabled)."""
    for record in (data.get("native") or {}).values():
        if isinstance(record, dict):
            if record.get("status"):
                return str(record["status"])
            if "enabled" in record:
                return "active" if record["enabled"] else "off"
    return ""


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
## What this is

Everything built around AI tools - agents with their instructions and skills, workflows, apps,
memory, and every conversation - kept outside any single tool, so work can move to another tool
at any time. A person or an agent who has never seen this repository should be able to find
anything from this page.

## Start here

- **Continue a conversation** in any tool: find it in the index (by `last_active` date, topic,
  tool, agent or project). Read its `summary.md`, then the replies in its `log.md` after the
  reply the summary covers (`summary_reply` in `meta.yaml`; an older summary without it: the
  replies dated after the summary's `updated_at`). No `summary.md` (runs and conversations pulled
  from a tool)? Read `log.md` from the start, or its last replies for a long one. The log is
  written at the end of each turn: for the very latest minutes, read the raw transcript.
- **Rebuild an agent** in another tool: take its definition from `core/agents/`, then everything
  the index lists with `"agent": "<name>"` (its parts) or `"for_agent": "<name>"` (built for it
  in another tool) - rules, skills, workflows, plugins, connections, app (tables and backend
  functions), memory - and set up again what stays in the tool (see Accounts).
- **Rebuild something that spans agents** (a service such as "WhatsApp"): search the index for
  the word - names, descriptions and memory subjects - then follow `uses` / `used_by`; the
  memory files in `explained_in` usually describe the whole service.
- **Find anything else**: the index (below).

## The logic of the structure

Each kind of thing has one place, whichever tool it came from. An agent's parts are kept by kind
in the shared folders - so one skill or connection can serve several agents - and each part says
which agent it belongs to.

- `core/` holds **what makes agents behave as they do**, portable between tools; it changes only
  with the owner's approval.
- Outside `core/` is **what accumulates** (memory, conversations), **what was built** (apps,
  assets) and **what only one tool understands** (`native/`).
- **Not on this branch:** full raw transcripts and files made in conversations (the transcripts
  branch or a synced folder, per account - see Accounts), and secrets (never in Git).

| Folder | What is in it |
|---|---|
| `core/agents/<agent>.yaml` | An agent: instructions, identity (when the tool has one), model, the skills and connections it uses; the tool's own record under `native:` (e.g. channels, webhooks). Where `instructions` is short, the behaviour is in its rules and memory |
| `core/instructions/<account>/` | Rules and standing instructions. `scope: global` = everything in that account; `agent:<name>` = one agent; `project:<name>` = one project |
| `core/skills/<skill>/` | A skill: `SKILL.md` (when and how to use it) with its scripts and references |
| `core/workflows/<workflow>.yaml` | A scheduled or triggered task: when it runs (`trigger`), which agent does it (`steps[].agent`), the tool's full definition and status under `native:` |
| `core/plugins/<plugin>/` | A plugin or MCP server that was built: its code, `plugin.yaml`, its config (`mcp-config.json`, values left out) |
| `core/connections.yaml` | Every connector, MCP server and channel (WhatsApp, phone...), and which accounts have it. Sign-ins stay in the tool |
| `core/profiles.yaml` | The accounts (tool + account) that feed this harness |
| `core/profile/`, `core/projects/` | Who the owner is; projects with their instructions and knowledge |
| `apps/<app>/` | An app built in a tool: `app.yaml`; table structures (`entities/`, all together in `entities.json`); backend code (`functions/<name>/`, with `functions.json`: what runs each one); the rows of settings tables (`data/`, secret values hidden); pages. Other table rows stay in the tool |
| `memory/` | One fact, decision or preference per file; `subject` says what it is about (for an agent's memory: the agent, then its first words), `provenance` where it came from |
| `sessions/<account>/<id>/` | One conversation or agent run: `summary.md`, `log.md` (word for word), `meta.yaml` (dates, topic, agent, where the raw transcript is); `replies/` when a tool sent its replies one by one |
| `native/<account>/` | A tool's own settings that no other tool understands, kept as they are |
| `assets/` | Reference files (examples, decks, designs) |
| `connector/` | Written by the engine: the index and the instructions the harness connector serves |
| `inbox/` | What tools sent, waiting to be filed by the engine. `inbox/conflicts/` = an incoming version that clashes with another account's (kept for the owner to choose); `inbox/rejected/` = files that could not be saved, with the reason - nothing to rebuild from either |

## How files point to each other

| Field | In | Means |
|---|---|---|
| `provenance.source.profile` | every item | the account it came from; `updates` lists later changes |
| `origin` | items | where in the tool it came from (e.g. `base44 superagent <id>`) |
| `skills`, `requires.connections` | agent | the skills and connections it uses |
| `steps[].agent` | workflow | the agent that runs it |
| `scope: agent:<name>` | instruction | a rule of that agent only |
| `agent`, `project` | conversation `meta.yaml` | the agent or project it belongs to |
| `summary_reply` | conversation `meta.yaml` | the last reply the summary covers |
| `transcript`, `files` | conversation `meta.yaml` | the raw transcript and the files made in it, on the transcripts branch |
| a name inside text | workflows, rules, code | a workflow or rule that says "call ingestCalendarInvites" uses that function |
"""

STATIC_FIND = """\
## Finding everything: the index

`connector/index.json` lists every item and every file, one entry each, rebuilt on every save.
Each entry has `kind`, `name`, `path` and the account (`profile`), and, where known:

- `agent` - the agent it belongs to; `for_agent` - built for that agent in another tool;
- `uses` / `used_by` - functions, tables and skills it names, and what names it;
- `called_from_outside` - for code called from outside this repository (a webhook - marked OFF
  when switched off - or another service), `explained_in` - the memory files that explain it;
- `needs_settings` - secrets and settings it reads (names only), `runs` and `status` for
  workflows (`active`, or not scheduled any more);
- for conversations: `date` (started), `last_active`, `tool`, `account`, `project`, `agent`,
  the goal from the summary,
  the first message, and where the `summary`, `log`, `raw` transcript and `files` are.

Kinds: `guide`, `agent`, `instruction`, `skill`, `workflow`, `plugin`, `connection`, `app`,
`function`, `table`, `memory`, `project`, `conversation`, `profile`, `file`.

**With the harness connector** (any tool with MCP): `harness_find` with words and optionally a
`kind`, then `harness_read` with the `path`. **On a computer**: search `connector/index.json`
(e.g. for `"agent": "<name>"` or a word such as a table's name), then open the paths.

A link is found when a file names the other item. Something set up only inside a tool (a
schedule, a sign-in) has no file that names it: look at `explained_in` and at the agent's memory.
"""

STATIC_END = """\
## Outside this branch

- **Raw transcripts and files made in conversations**: where each account keeps them is in the
  table above. On the transcripts branch: `git fetch origin transcripts`, then
  `git show origin/transcripts:<path>` - the path is `transcript:` in the conversation's
  `meta.yaml`, and its files are under `<account>/<id>/files/`. Through the connector:
  `harness_read` with `transcripts:<path>`.
- **Secrets** (passwords, tokens, keys) are never stored here, not even in this private
  repository; only their names (`needs_settings` in the index). They are set in the tool
  itself; the harness engine keeps its own in the computer's password store, a cloud
  environment's secrets, or the connector's Cloudflare secrets.

## Changing this repository

Content is written by the engine and the tools' adapters, never by hand: a hand edit can be
overwritten or lose its source. Bring in a tool with `python -m harness harvest <tool>`; tools
that cannot reach Git save through the harness connector. Check with `python -m harness validate`.
"""
