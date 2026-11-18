"""Writers turn ``Captured`` items into harness content, one writer per kind.

Every writer stamps provenance. Before overwriting, it checks who changed
the target last: if a *different* profile did, the incoming version goes to
``inbox/conflicts/`` instead, and the conflict is reported.
"""

from __future__ import annotations

import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import yaml_io
from ..documents import MarkdownDocument
from ..memory import MemoryStore
from ..provenance import Origin, Provenance
from ..repo import ContentRepo
from ..text import slugify
from .item import Captured, Kind

CONFLICTS_DIR = "inbox/conflicts"


@dataclass(frozen=True)
class WriteResult:
    action: str  # created | updated | conflict
    path: Path


class ItemWriter(ABC):
    kind: Kind

    def __init__(self, repo: ContentRepo) -> None:
        self.repo = repo

    @abstractmethod
    def write(self, item: Captured, origin: Origin) -> WriteResult:
        """Write ``item`` into the repository."""

    def location(self, name: str, scope: str, profile: str) -> Path | None:
        """Where this writer puts an item by convention (None if not separable)."""
        return None

    def retract(self, name: str, scope: str, profile: str, known_path: Path | None = None) -> bool:
        """The tool no longer has this item: remove what ``profile`` contributed. True if removed."""
        target = known_path or self.location(name, scope, profile)
        if target is None or not target.exists():
            return False
        shutil.rmtree(target) if target.is_dir() else target.unlink()
        return True

    # --- shared helpers -------------------------------------------------------

    def _conflicting(self, existing: dict[str, Any] | None, origin: Origin) -> bool:
        last = Provenance.last_profile(existing)
        return last is not None and last != origin.profile

    def _conflict_path(self, target: Path, origin: Origin) -> Path:
        relative = target.relative_to(self.repo.root)
        return self.repo.path(CONFLICTS_DIR, origin.profile, *relative.parts)


class InstructionWriter(ItemWriter):
    """CLAUDE.md-style files -> core/instructions/<profile>/<scope>-<name>.md"""

    kind = Kind.INSTRUCTION

    def write(self, item: Captured, origin: Origin) -> WriteResult:
        name = "global" if item.scope == "global" else slugify(item.scope.split(":", 1)[-1])
        target = self.repo.path("core", "instructions", origin.profile, f"{name}-{item.name}.md")
        return _write_markdown(self, target, item, origin, item.text(next(iter(item.files))),
                               {"scope": item.scope, "origin": item.origin})


class SkillWriter(ItemWriter):
    """A skill folder (or single prompt file) -> core/skills/<name>/ with SKILL.md + supporting files."""

    kind = Kind.SKILL
    MAIN = "SKILL.md"

    def location(self, name: str, scope: str, profile: str) -> Path | None:
        return self.repo.path("core", "skills", slugify(name))

    def write(self, item: Captured, origin: Origin) -> WriteResult:
        folder = self.repo.path("core", "skills", slugify(item.name))
        main = MarkdownDocument.parse(item.text(self.MAIN))
        native = {k: v for k, v in main.meta.items() if k not in ("name", "description")}
        meta = {
            "name": slugify(item.name),
            "description": str(main.meta.get("description") or _first_line(main.body) or item.name),
            "origin": item.origin,
        }
        if native:
            meta["native"] = {origin.profile: native}
        result = _write_markdown(self, folder / self.MAIN, item, origin, main.body, meta)
        destination = result.path.parent
        for relative, content in item.files.items():
            if relative != self.MAIN:
                path = destination.joinpath(*relative.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        return result


class AgentWriter(ItemWriter):
    """A sub-agent (Markdown with frontmatter) -> core/agents/<name>.yaml"""

    kind = Kind.AGENT

    def write(self, item: Captured, origin: Origin) -> WriteResult:
        source = MarkdownDocument.parse(item.text(next(iter(item.files))))
        name = slugify(str(source.meta.get("name") or item.name))
        target = self.repo.path("core", "agents", f"{name}.yaml")
        existing = yaml_io.load(target.read_text("utf-8")) if target.is_file() else None
        same_content = bool(existing) and existing.get("instructions") == source.body.strip()
        conflict = bool(existing) and not same_content and \
            self._conflicting(existing.get("provenance"), origin)
        if conflict:
            target = self._conflict_path(target, origin)

        tools = source.meta.get("tools")
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",") if t.strip()]
        native = {k: v for k, v in source.meta.items() if k not in ("name", "description", "tools")}
        agent: dict[str, Any] = {
            "name": name,
            "description": str(source.meta.get("description") or name),
            "instructions": source.body.strip(),
            "origin": item.origin,
        }
        if tools:
            agent["requires"] = {"tools": list(dict.fromkeys(tools))}
        if native:
            agent["native"] = {origin.profile: native}
        previous = None if conflict or not existing else existing.get("provenance")
        agent["provenance"] = Provenance.updated(previous, origin)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml_io.dump(agent), encoding="utf-8")
        return WriteResult("conflict" if conflict else ("updated" if existing else "created"), target)


class MemoryWriter(ItemWriter):
    """A memory document -> memory/<profile>-<scope>-<name>.md (conflicts handled by MemoryStore)."""

    kind = Kind.MEMORY

    def write(self, item: Captured, origin: Origin) -> WriteResult:
        scope = "" if item.scope == "global" else item.scope.split(":", 1)[-1] + "-"
        entry_id = slugify(f"{origin.profile}-{scope}{item.name}")
        body = MarkdownDocument.parse(item.text(next(iter(item.files)))).body
        result = MemoryStore(self.repo).put(entry_id, body, origin, kind="project-state",
                                            subject=item.meta.get("subject"))
        return WriteResult(result.action, result.path)


class ConnectionWriter(ItemWriter):
    """MCP servers / plugins -> one entry in core/connections.yaml.

    Availability is recorded per *tool* (item.meta["tool"]), not per account:
    it describes what the tool can connect to.
    """

    kind = Kind.CONNECTION

    def write(self, item: Captured, origin: Origin) -> WriteResult:
        path = self.repo.path(self.repo.layout.connections_file)
        document = yaml_io.load(path.read_text("utf-8")) if path.is_file() else None
        connections: list[dict[str, Any]] = list((document or {}).get("connections") or [])
        entry_id = slugify(item.name)
        current = next((c for c in connections if c.get("id") == entry_id), None)

        tool = item.meta["tool"]
        previous = ((current or {}).get("available_in") or {}).get(tool) or {}
        available = {"kind": item.meta["kind"],
                     "profiles": sorted(set(previous.get("profiles", [])) | {origin.profile})}
        if item.meta.get("notes"):
            available["notes"] = item.meta["notes"]
        if current is None:
            connections.append({
                "id": entry_id, "kind": item.meta["kind"],
                "description": item.meta.get("description", item.name),
                "available_in": {tool: available},
                "provenance": Provenance.new(origin),
            })
            action = "created"
        else:
            current.setdefault("available_in", {})[tool] = available
            if item.meta.get("description") and not str(item.meta["description"]).startswith("Plugin '"):
                current["description"] = item.meta["description"]  # a real description wins
            current["provenance"] = Provenance.updated(current.get("provenance"), origin)
            action = "updated"
        self._save(path, connections)
        return WriteResult(action, path)

    def retract(self, name: str, scope: str, profile: str, known_path: Path | None = None) -> bool:
        """Drop ``profile`` from the connection; drop the tool when no profile has it any more,
        and the connection when no tool does."""
        path = self.repo.path(self.repo.layout.connections_file)
        if not path.is_file():
            return False
        connections = list((yaml_io.load(path.read_text("utf-8")) or {}).get("connections") or [])
        entry = next((c for c in connections if c.get("id") == slugify(name)), None)
        if entry is None:
            return False
        source = ((entry.get("provenance") or {}).get("source") or {}).get("profile")
        changed = False
        for tool, available in list((entry.get("available_in") or {}).items()):
            profiles = set(available.get("profiles") or ([source] if source else []))
            if profile in profiles:
                profiles.discard(profile)
                changed = True
                if profiles:
                    available["profiles"] = sorted(profiles)
                else:
                    del entry["available_in"][tool]
        if not changed:
            return False
        if not entry.get("available_in"):
            connections.remove(entry)
        self._save(path, connections)
        return True

    @staticmethod
    def _save(path: Path, connections: list[dict[str, Any]]) -> None:
        path.write_text(yaml_io.dump({"connections": connections}), encoding="utf-8")


class PluginWriter(ItemWriter):
    """A plugin the user built -> core/plugins/<name>/ (its files as-is) + plugin.yaml (provenance)."""

    kind = Kind.PLUGIN
    DESCRIPTOR = "plugin.yaml"

    def location(self, name: str, scope: str, profile: str) -> Path | None:
        return self.repo.path("core", "plugins", slugify(name))

    def write(self, item: Captured, origin: Origin) -> WriteResult:
        folder = self.location(item.name, item.scope, origin.profile)
        descriptor = folder / self.DESCRIPTOR
        existing = yaml_io.load(descriptor.read_text("utf-8")) if descriptor.is_file() else None
        same_content = bool(existing) and _folder_matches(folder, item.files)
        conflict = bool(existing) and not same_content and \
            self._conflicting(existing.get("provenance"), origin)
        if conflict:
            folder = self._conflict_path(folder, origin)
            descriptor = folder / self.DESCRIPTOR
        elif folder.is_dir():
            shutil.rmtree(folder)  # the plugin as it is now; Git keeps every earlier version
        for relative, content in item.files.items():
            path = folder.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        previous = None if conflict or not existing else existing.get("provenance")
        descriptor.write_text(yaml_io.dump({
            "name": slugify(item.name), "description": item.meta.get("description", item.name),
            "origin": item.origin, "provenance": Provenance.updated(previous, origin),
        }), encoding="utf-8")
        return WriteResult("conflict" if conflict else ("updated" if existing else "created"), descriptor)


class NativeWriter(ItemWriter):
    """Tool-specific files kept as-is (secrets already removed) -> native/<profile>/<scope>/...

    Rule: a native item occupies one entry in its scope folder, named after the
    item (``settings`` -> ``settings.json``, ``output-styles`` -> ``output-styles/``).
    """

    kind = Kind.NATIVE

    def write(self, item: Captured, origin: Origin) -> WriteResult:
        folder = self._folder(item.scope, origin.profile)
        existed = False
        for relative, content in item.files.items():
            path = folder.joinpath(*relative.split("/"))
            existed = existed or path.exists()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        entry = folder / next(iter(item.files)).split("/", 1)[0]
        return WriteResult("updated" if existed else "created", entry)

    def location(self, name: str, scope: str, profile: str) -> Path | None:
        folder = self._folder(scope, profile)
        matches = [p for p in folder.glob(f"{name}*") if p.name == name or p.stem == name]
        return matches[0] if matches else None

    def _folder(self, scope: str, profile: str) -> Path:
        name = "global" if scope == "global" else slugify(scope.split(":", 1)[-1])
        return self.repo.path("native", profile, name)


DEFAULT_WRITERS: tuple[type[ItemWriter], ...] = (
    InstructionWriter, SkillWriter, AgentWriter, MemoryWriter, ConnectionWriter, PluginWriter,
    NativeWriter,
)


def _write_markdown(writer: ItemWriter, target: Path, item: Captured, origin: Origin, body: str,
                    meta: dict[str, Any]) -> WriteResult:
    """Shared path for Markdown items: provenance, conflict diversion, write."""
    current = MarkdownDocument.read(target) if target.is_file() else None
    existing = current.meta if current else None
    same_content = current is not None and current.body.strip() == body.strip()
    conflict = bool(existing) and not same_content and writer._conflicting(existing.get("provenance"), origin)
    if conflict:
        target = writer._conflict_path(target, origin)
    previous = None if conflict or not existing else existing.get("provenance")
    meta = {**meta, "provenance": Provenance.updated(previous, origin)}
    MarkdownDocument(meta, body).write(target)
    return WriteResult("conflict" if conflict else ("updated" if existing else "created"), target)


def _folder_matches(folder: Path, files: dict[str, bytes]) -> bool:
    """Whether ``folder`` already holds exactly ``files`` (besides plugin.yaml)."""
    present = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()} - {"plugin.yaml"}
    return present == set(files) and all(
        folder.joinpath(*k.split("/")).read_bytes() == v for k, v in files.items())


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = re.sub(r"^#+\s*", "", line).strip()
        if line:
            return line[:200]
    return ""
