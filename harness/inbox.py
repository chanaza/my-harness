"""``InboxProcessor``: files the harness connector dropped into ``inbox/connector/``.

Tools that cannot write to the harness directly (claude.ai, Cowork in the cloud, and
any other tool with connectors) run a harness skill that calls the harness connector,
which drops one file per call into the repository's inbox:

  describe-<time>.yaml ............ everything the tool account has built, in a fixed form
                                     (schemas/harness-describe.schema.json)
  conversation-<time>-<title>.md .. a conversation's summary in the harness's sections
                                     (front matter: schemas/harness-conversation.schema.json)

The processor (run by `harness inbox`, e.g. from GitHub Actions) checks each file
against its form, saves it like any other capture, and removes it from the inbox. A
file that does not match goes to inbox/rejected/ with the reason next to it. Its own
records live in the repository (inbox/.state/), so it works from any machine.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import yaml_io
from .checkpoints import CheckpointRecorder
from .documents import MarkdownDocument
from .harvest import Captured, HarvestReport, HarvestSync, Kind
from .local import LocalHome, StateFile
from .profiles import ProfileError, ProfileRegistry
from .provenance import Origin
from .repo import ContentRepo
from .sessions import SessionRecord
from .text import slugify

DESCRIBE_PATTERN = "describe-*.yaml"
CONVERSATION_PATTERN = "conversation-*.md"


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads(resources.files("harness.schemas").joinpath(name).read_text("utf-8"))
    return Draft202012Validator(schema)


def _plain(value: Any) -> Any:
    """YAML dates and times as text (the forms describe text)."""
    return json.loads(json.dumps(value, default=str))


@dataclass
class InboxFile:
    path: Path
    data: dict[str, Any]
    body: str = ""

    @property
    def profile(self) -> str:
        return str(self.data.get("profile") or "")


class InboxProcessor:
    def __init__(self, repo: ContentRepo, local: LocalHome | None = None) -> None:
        self.repo = repo
        self.local = local or LocalHome()
        self.folder = repo.path("inbox", "connector")
        self.rejected = repo.path("inbox", "rejected")

    def pending(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return sorted(p for p in self.folder.iterdir() if p.is_file() and not p.name.startswith("."))

    def run(self) -> HarvestReport:
        report = HarvestReport()
        known = {p.id: p for p in ProfileRegistry(self.repo).all()}
        for path in self.pending():
            try:
                file = self._read(path)
                if file.profile not in known:
                    raise ValueError(f"profile {file.profile!r} is not registered in core/profiles.yaml")
                if path.name.startswith("describe-"):
                    self._describe(file, known[file.profile].tool, report)
                else:
                    self._conversation(file, report)
                path.unlink()
            except (ValueError, ProfileError) as exc:
                self._reject(path, str(exc))
                report.errors.append(f"{path.name}: {exc}")
        return report

    def _read(self, path: Path) -> InboxFile:
        if path.match(DESCRIBE_PATTERN):
            try:
                data = _plain(yaml_io.load(path.read_text("utf-8")) or {})
            except Exception as exc:  # noqa: BLE001 - any unreadable file is rejected, not fatal
                raise ValueError(f"not readable ({exc})") from None
            self._check(data, "harness-describe.schema.json")
            return InboxFile(path, data)
        if path.match(CONVERSATION_PATTERN):
            document = MarkdownDocument.parse(path.read_text("utf-8"))
            meta = _plain(dict(document.meta))
            self._check(meta, "harness-conversation.schema.json")
            return InboxFile(path, meta, document.body)
        raise ValueError("unknown kind of file (expected describe-*.yaml or conversation-*.md)")

    @staticmethod
    def _check(data: Any, schema: str) -> None:
        errors = sorted(_validator(schema).iter_errors(data), key=lambda e: list(e.path))
        if errors:
            where = "/".join(str(p) for p in errors[0].path) or "(top)"
            raise ValueError(f"does not match the form at {where}: {errors[0].message}")

    def _describe(self, file: InboxFile, tool: str, report: HarvestReport) -> None:
        exclude = self.repo.config.harvest_exclude
        from fnmatch import fnmatch
        items = [i for i in describe_items(file, tool)
                 if not any(fnmatch(f"{i.kind.value}:{i.name}", p) for p in exclude)]
        state = StateFile(self.repo.path("inbox", ".state", f"{file.profile}-describe.json"))
        part = HarvestSync(self.repo, state).run(items, Origin.now(file.profile, None))
        report.counts.update(part.counts)
        report.errors += part.errors
        report.conflicts += part.conflicts

    def _conversation(self, file: InboxFile, report: HarvestReport) -> None:
        data = file.data
        record = SessionRecord(self.repo, file.profile, file.path.stem)
        record.touch(topic=data.get("title"), surface=data.get("surface"),
                     project=data.get("project") or None, activity_at=str(data.get("saved_at")))
        recorder = CheckpointRecorder(self.local, self.repo, record)
        recorder.write(file.body, "saved through the harness connector")
        report.counts["conversations saved"] += 1

    def _reject(self, path: Path, reason: str) -> None:
        self.rejected.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(self.rejected / path.name))
        (self.rejected / f"{path.name}.problem.txt").write_text(reason + "\n", encoding="utf-8")


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
    rest = {key: data[key] for key in ("user_profile", "apps", "native", "cannot_see", "surface")
            if data.get(key)}
    items.append(Captured(Kind.NATIVE, "account", origin,
                          {"account/account.yaml": yaml_io.dump(rest).encode()}))
    return items
