"""``ClaudeCodeHarvester``: reads everything built in Claude Code. It never writes.

Sources, global (config dir) and per project:
  CLAUDE.md files ................ instructions
  skills/**/SKILL.md ............. skills (whole folder)
  commands/**/*.md ............... skills (single-file prompts)
  agents/*.md .................... agents
  projects/*/memory/**/*.md ...... memory (Claude Code's own memory files)
  .claude.json / .mcp.json ....... MCP connections (names, type, executable or host only)
  plugins/ ....................... plugin connections
  settings.json, output-styles/ .. native (secrets removed)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ...harvest import Captured, Kind
from .constants import HOOK_MARKER, SKILL_NAME, TOOL
from .locations import ClaudeCodeLocations

MAX_FILE_BYTES = 5 * 1024 * 1024
#: Settings keys that can hold secrets or machine-specific credentials helpers.
SECRET_SETTINGS = frozenset({"env", "apiKeyHelper", "awsAuthRefresh", "awsCredentialExport",
                             "otelHeadersHelper", "oauthAccount"})


class ClaudeCodeHarvester:
    def __init__(self, locations: ClaudeCodeLocations, exclude: list[str] | None = None) -> None:
        self.locations = locations
        self.exclude = list(exclude or [])

    def collect(self) -> list[Captured]:
        items: list[Captured] = []
        for source in (self._instructions, self._skills, self._commands, self._agents,
                       self._memory, self._mcp_servers, self._plugins, self._native):
            items.extend(source())
        return [i for i in items if not self.is_excluded(i.kind.value, i.name)]

    #: Installed by the engine itself, never the user's content.
    ENGINE_OWNED = (f"skill:{SKILL_NAME}",)

    def is_excluded(self, kind: str, name: str) -> bool:
        label = f"{kind}:{name}"
        return any(fnmatch(label, pattern) for pattern in (*self.ENGINE_OWNED, *self.exclude))

    # --- scopes ---------------------------------------------------------------

    def _scopes(self) -> Iterator[tuple[str, Path]]:
        """(scope, folder holding .claude-style content) for global and the current project."""
        yield "global", self.locations.config_dir
        if self.locations.project_dir:
            yield self._project_scope(), self.locations.project_dir / ".claude"

    def _project_scope(self) -> str:
        return f"project:{self.locations.project_dir.name}" if self.locations.project_dir else "global"

    # --- sources --------------------------------------------------------------

    def _instructions(self) -> Iterator[Captured]:
        candidates = [("global", self.locations.config_dir / "CLAUDE.md", "claude-md")]
        project = self.locations.project_dir
        if project:
            scope = self._project_scope()
            candidates += [(scope, project / "CLAUDE.md", "claude-md"),
                           (scope, project / ".claude" / "CLAUDE.md", "dot-claude-md"),
                           (scope, project / "CLAUDE.local.md", "claude-local-md")]
        for scope, path, name in candidates:
            if path.is_file():
                yield Captured(Kind.INSTRUCTION, name, str(path), {path.name: path.read_bytes()}, scope=scope)

    def _skills(self) -> Iterator[Captured]:
        for scope, base in self._scopes():
            skills = base / "skills"
            for main in sorted(skills.rglob("SKILL.md")) if skills.is_dir() else []:
                if _in_hidden_folder(main, skills):
                    continue  # e.g. skills/.trash: deleted skills are not the user's skills
                folder = main.parent
                files = {p.relative_to(folder).as_posix(): p.read_bytes()
                         for p in sorted(folder.rglob("*"))
                         if p.is_file() and p.stat().st_size <= MAX_FILE_BYTES}
                yield Captured(Kind.SKILL, folder.name, str(folder), files, scope=scope)

    def _commands(self) -> Iterator[Captured]:
        for scope, base in self._scopes():
            folder = base / "commands"
            for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
                if _in_hidden_folder(path, folder):
                    continue
                yield Captured(Kind.SKILL, path.stem, str(path), {"SKILL.md": path.read_bytes()},
                               meta={"source": "command"}, scope=scope)

    def _agents(self) -> Iterator[Captured]:
        for scope, base in self._scopes():
            folder = base / "agents"
            for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
                yield Captured(Kind.AGENT, path.stem, str(path), {path.name: path.read_bytes()}, scope=scope)

    def _memory(self) -> Iterator[Captured]:
        projects = self.locations.config_dir / "projects"
        for path in sorted(projects.glob("*/memory/**/*.md")) if projects.is_dir() else []:
            project = path.relative_to(projects).parts[0]
            yield Captured(Kind.MEMORY, path.stem, str(path), {path.name: path.read_bytes()},
                           scope=f"project:{project.strip('-') or 'root'}")

    def _mcp_servers(self) -> Iterator[Captured]:
        servers: dict[str, tuple[dict[str, Any], str]] = {}
        user_config = _read_json(self.locations.user_config_file)
        for name, spec in (user_config.get("mcpServers") or {}).items():
            servers[name] = (spec, str(self.locations.user_config_file))
        for project, settings in (user_config.get("projects") or {}).items():
            for name, spec in (settings.get("mcpServers") or {}).items():
                servers.setdefault(name, (spec, f"{self.locations.user_config_file} [{project}]"))
        if self.locations.project_dir:
            mcp_file = self.locations.project_dir / ".mcp.json"
            for name, spec in (_read_json(mcp_file).get("mcpServers") or {}).items():
                servers.setdefault(name, (spec, str(mcp_file)))
        for name, (spec, origin) in sorted(servers.items()):
            yield Captured(Kind.CONNECTION, name, origin, meta={
                "tool": TOOL, "kind": "mcp",
                "description": f"MCP server '{name}'",
                "notes": _describe_mcp(spec),
            })

    def _plugins(self) -> Iterator[Captured]:
        plugins_dir = self.locations.config_dir / "plugins"
        found: dict[str, tuple[str, str]] = {}  # name -> (origin, description)
        installed = _read_json(plugins_dir / "installed_plugins.json")
        for key in (installed.get("plugins") or {}):
            name = key.split("@", 1)[0]
            found[name] = (str(plugins_dir / "installed_plugins.json"), f"Plugin '{name}'")
        # Plugins synced from the account: listed, with a description, in a manifest.
        for manifest in plugins_dir.glob("*/*/manifest.json") if plugins_dir.is_dir() else []:
            for plugin in _read_json(manifest).get("plugins") or []:
                if isinstance(plugin, dict) and plugin.get("name"):
                    description = plugin.get("description") or f"Plugin '{plugin['name']}'"
                    found.setdefault(plugin["name"], (str(manifest), description))
        for name, (origin, description) in sorted(found.items()):
            yield Captured(Kind.CONNECTION, name, origin, meta={
                "tool": TOOL, "kind": "plugin", "description": description})

    def _native(self) -> Iterator[Captured]:
        for scope, base in self._scopes():
            settings = base / "settings.json"
            if settings.is_file():
                clean = _without_engine_hooks(
                    {k: v for k, v in _read_json(settings).items() if k not in SECRET_SETTINGS})
                if clean:
                    yield Captured(Kind.NATIVE, "settings", str(settings),
                                   {"settings.json": json.dumps(clean, indent=2).encode()}, scope=scope)
            styles = base / "output-styles"
            if styles.is_dir():
                files = {f"output-styles/{p.name}": p.read_bytes() for p in sorted(styles.glob("*.md"))}
                if files:
                    yield Captured(Kind.NATIVE, "output-styles", str(styles), files, scope=scope)


def _in_hidden_folder(path: Path, root: Path) -> bool:
    """Whether ``path`` sits inside a dot-folder under ``root`` (.trash, .staging, ...)."""
    return any(part.startswith(".") for part in path.relative_to(root).parts[:-1])


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _without_engine_hooks(settings: dict[str, Any]) -> dict[str, Any]:
    """Drop the hooks the engine installed; keep the user's own."""
    hooks = {}
    for event, groups in (settings.get("hooks") or {}).items():
        kept = [g for g in groups if not any(HOOK_MARKER in h.get("command", "") for h in g.get("hooks", []))]
        if kept:
            hooks[event] = kept
    cleaned = {k: v for k, v in settings.items() if k != "hooks"}
    return {**cleaned, "hooks": hooks} if hooks else cleaned


def _describe_mcp(spec: dict[str, Any]) -> str:
    """What is needed to recreate the connection, without arguments, env or headers."""
    kind = spec.get("type") or ("stdio" if spec.get("command") else "http")
    if spec.get("url"):
        return f"{kind}; host {urlparse(spec['url']).netloc}"
    if spec.get("command"):
        return f"{kind}; runs {Path(str(spec['command'])).name}"
    return kind
