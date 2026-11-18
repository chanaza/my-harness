"""``InboxProcessor``: files the harness connector dropped into ``inbox/connector/``.

Tools that cannot write to the harness directly (claude.ai, Cowork in the cloud, and
any other tool with connectors) run a harness skill that calls the harness connector,
which drops one file per call into the repository's inbox:

  describe-<time>.yaml ............ everything the tool account has built, in a fixed form
                                     (schemas/harness-describe.schema.json)
  conversation-<time>-<title>.md .. a conversation's summary in the harness's sections
                                     (front matter: schemas/harness-conversation.schema.json)
  exchange-<time>-<title>-<n>.md .. reply n of that conversation and the message before it,
                                     word for word, appended to the conversation's log.md
                                     (front matter: schemas/harness-exchange.schema.json)

To continue a conversation anywhere: its summary.md plus log.md after it.

The processor (run by `harness inbox`, e.g. from GitHub Actions) checks each file
against its form, saves it like any other capture, and removes it from the inbox. A
file that does not match goes to inbox/rejected/ with the reason next to it. Its own
records live in the repository (inbox/.state/), so it works from any machine.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import yaml_io
from .checkpoints import CheckpointRecorder
from .conversation_log import ConversationLog, Reply
from .documents import MarkdownDocument
from .harvest import Captured, HarvestReport, HarvestSync, Kind
from .local import LocalHome, StateFile
from .profiles import ProfileError, ProfileRegistry
from .provenance import Origin, to_iso
from .repo import ContentRepo
from .sessions import SessionRecord
from .text import slugify

DESCRIBE_PATTERN = "describe-*.yaml"
#: describe-<time>-2of3.yaml: one part of a description that was too large for one file.
PART = re.compile(r"^(describe-.+)-(\d+)of(\d+)\.yaml$")
CONVERSATION_PATTERN = "conversation-*.md"
EXCHANGE_PATTERN = "exchange-*.md"
EXCHANGE_NUMBER = re.compile(r"-(\d+)\.md$")


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
        def order(path: Path) -> tuple[str, int]:   # exchanges in reply order, not name order
            number = EXCHANGE_NUMBER.search(path.name)
            return (EXCHANGE_NUMBER.sub("", path.name), int(number.group(1)) if number else 0)
        return sorted((p for p in self.folder.iterdir() if p.is_file() and not p.name.startswith(".")),
                      key=order)

    def run(self) -> HarvestReport:
        report = HarvestReport()
        known = {p.id: p for p in ProfileRegistry(self.repo).all()}
        for paths in self._units():
            path = paths[0]
            try:
                file = self._merged([self._read(p) for p in paths])
                if file.profile not in known:
                    raise ValueError(f"profile {file.profile!r} is not registered in core/profiles.yaml")
                if path.name.startswith("describe-"):
                    self._describe(file, known[file.profile].tool, report)
                elif path.name.startswith("exchange-"):
                    self._exchange(file, report)
                else:
                    self._conversation(file, report)
                for done in paths:
                    done.unlink()
            except (ValueError, ProfileError) as exc:
                for bad in paths:
                    self._reject(bad, str(exc))
                report.errors.append(f"{path.name}: {exc}")
        return report

    def _units(self) -> list[list[Path]]:
        """Files to save together: a single file, or every part of a split description
        (a description whose parts have not all arrived yet waits for the next run)."""
        units: list[list[Path]] = []
        parts: dict[str, list[Path]] = {}
        for path in self.pending():
            match = PART.match(path.name)
            if match:
                parts.setdefault(match.group(1), []).append(path)
            else:
                units.append([path])
        for paths in parts.values():
            total = int(PART.match(paths[0].name).group(3))
            if len(paths) == total:
                units.append(sorted(paths, key=lambda p: int(PART.match(p.name).group(2))))
        return units

    @staticmethod
    def _merged(files: list[InboxFile]) -> InboxFile:
        """The parts of one description as one: lists joined, everything else from part 1."""
        if len(files) == 1:
            return files[0]
        data = dict(files[0].data)
        for file in files[1:]:
            if file.profile != files[0].profile:
                raise ValueError("the parts of one description name different profiles")
            for key, value in file.data.items():
                if isinstance(value, list):
                    data[key] = list(data.get(key) or []) + value
                else:
                    data.setdefault(key, value)
        data.pop("part", None)
        return InboxFile(files[0].path, data)

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
        if path.match(EXCHANGE_PATTERN):
            document = MarkdownDocument.parse(path.read_text("utf-8"))
            meta = _plain(dict(document.meta))
            self._check(meta, "harness-exchange.schema.json")
            return InboxFile(path, meta, document.body)
        raise ValueError("unknown kind of file (expected describe-*.yaml, conversation-*.md "
                         "or exchange-*.md)")

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
        # A partial description (e.g. one project, from inside it) keeps its own records, so it
        # neither removes nor replaces what the full daily description saved.
        scope = "describe" if not file.data.get("partial") else \
            "partial-" + slugify("-".join(p["name"] for p in file.data.get("projects") or []) or "items")
        state = StateFile(self.repo.path("inbox", ".state", f"{file.profile}-{scope}.json"))
        part = HarvestSync(self.repo, state).run(items, Origin.now(file.profile, None))
        report.counts.update(part.counts)
        report.errors += part.errors
        report.conflicts += part.conflicts

    def _conversation(self, file: InboxFile, report: HarvestReport) -> None:
        data = file.data
        record = SessionRecord(self.repo, file.profile, file.path.stem)
        record.touch(topic=data.get("title"), surface=data.get("surface"),
                     project=data.get("project") or None, activity_at=to_iso(data.get("saved_at")))
        recorder = CheckpointRecorder(self.local, self.repo, record)
        recorder.write(file.body, "saved through the harness connector")
        report.counts["conversations saved"] += 1

    def retry_rejected(self) -> list[str]:
        """Put rejected files back into the inbox (their problem notes are dropped)."""
        moved = []
        for path in sorted(self.rejected.glob("*")) if self.rejected.is_dir() else []:
            if path.name.endswith(".problem.txt"):
                path.unlink()
                continue
            self.folder.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(self.folder / path.name))
            moved.append(path.name)
        return moved

    def _exchange(self, file: InboxFile, report: HarvestReport) -> None:
        """One exchange into the conversation's log (the engine's ConversationLog)."""
        data = file.data
        record = SessionRecord(self.repo, file.profile, data["conversation"])
        reply = Reply.from_exchange(int(data["number"]), to_iso(data.get("at")) or "", file.body)
        last = ConversationLog(record).add(data.get("title") or data["conversation"], reply)
        record.touch(activity_at=to_iso(data.get("at")), log_last=last,
                     **{k: v for k, v in (("topic", data.get("title")), ("surface", data.get("surface")),
                                         ("project", data.get("project") or None)) if v})
        report.counts["exchanges saved"] += 1

    def _reject(self, path: Path, reason: str) -> None:
        self.rejected.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(self.rejected / path.name))
        (self.rejected / f"{path.name}.problem.txt").write_text(reason + "\n", encoding="utf-8")


INSTRUCTIONS_FOLDER = ("connector", "instructions")


def write_connector_instructions(repo: ContentRepo) -> list[str]:
    """connector/instructions/<tool>.md for every tool with a skill: what the connector serves,
    so a skill in a tool account always follows this engine's current instructions."""
    from .adapters import adapters
    written = []
    for tool in adapters.names():
        text = adapters.create(tool).connector_instructions(repo.config)
        if text is None:
            continue
        path = repo.path(*INSTRUCTIONS_FOLDER, f"{tool}.md")
        if not path.is_file() or path.read_text("utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written.append(path.relative_to(repo.root).as_posix())
    return written


def _files(entries: list[dict[str, Any]] | None, folder: str = "") -> dict[str, bytes]:
    return {f"{folder}{e['path'].lstrip('/')}": e["content"].encode("utf-8") for e in entries or []}


def _memory_name(entry: dict[str, Any]) -> str:
    """By topic (stable when the tool lists memory in another order)."""
    topic = entry.get("name") or entry["text"].strip().splitlines()[0][:60]
    return slugify(Path(topic).stem if topic.startswith("/") else topic) or "memory"


def describe_items(describe: InboxFile, tool: str) -> list[Captured]:
    """A describe file -> harness items, each kind in its own place, with full content.
    Things that are not the user's (e.g. Anthropic's skills), or whose content could not be
    read, are only recorded in the account's native file, never saved as empty copies."""
    data, origin = describe.data, describe.path.name
    items: list[Captured] = []
    unreadable: list[str] = []
    for entry in data.get("instructions") or []:
        name = slugify(entry["name"])
        items.append(Captured(Kind.INSTRUCTION, name, origin, {f"{name}.md": entry["text"].encode()}))
    for entry in data.get("memory") or []:
        name = _memory_name(entry)
        items.append(Captured(Kind.MEMORY, name, origin, {f"{name}.md": entry["text"].encode()}))
    for kind, key in ((Kind.SKILL, "skills"), (Kind.PLUGIN, "plugins")):
        for entry in data.get(key) or []:
            if entry.get("origin") != "mine":
                continue
            if not entry.get("files"):
                why = entry.get("not_readable") or "no content sent"
                unreadable.append(f"{key}: {entry['name']} ({why})")
                continue
            items.append(Captured(kind, entry["name"], origin, _files(entry["files"]),
                                  meta={"description": entry.get("description") or entry["name"]}))
    for entry in data.get("agents") or []:
        if entry.get("files"):
            items.append(Captured(Kind.AGENT, entry["name"], origin, _files(entry["files"])))
        else:
            items.append(Captured(Kind.AGENT, entry["name"], origin, meta={"agent": {
                "name": slugify(entry["name"]), "description": entry.get("description") or entry["name"]}}))
    for entry in data.get("connections") or []:
        items.append(Captured(Kind.CONNECTION, entry["name"], origin, meta={
            "tool": tool, "kind": entry.get("kind", "connector"),
            "description": entry.get("purpose") or entry["name"]}))
    for entry in data.get("projects") or []:
        files = {"instructions.md": (entry.get("instructions") or "").encode(),
                 **_files(entry.get("knowledge"), "knowledge/")}
        if entry.get("not_readable"):
            unreadable.append(f"projects: {entry['name']} ({entry['not_readable']})")
        items.append(Captured(Kind.PROJECT, entry["name"], origin, files,
                              meta={"description": entry.get("description") or entry["name"],
                                    "fields": {"title": entry["name"]}}))
    for entry in data.get("workflows") or []:
        items.append(Captured(Kind.WORKFLOW, entry["name"], origin, meta={
            "description": entry["name"], "prompt": entry.get("prompt"), "trigger": entry.get("schedule")}))
    for entry in data.get("apps") or []:
        if not entry.get("files"):
            unreadable.append(f"apps: {entry['name']} ({entry.get('not_readable') or 'no content sent'})")
            continue
        items.append(Captured(Kind.APP, entry["name"], origin, _files(entry["files"]),
                              meta={"description": entry.get("description") or entry["name"],
                                    "fields": {"link": entry.get("link")} if entry.get("link") else {}}))
    if data.get("partial"):   # only what is listed: the account's own file is left as it is
        return items
    rest = {key: data[key] for key in ("user_profile", "native", "cannot_see", "surface") if data.get(key)}
    others = {key: [{"name": e["name"], "description": e.get("description"), "origin": e.get("origin")}
                    for e in data.get(key) or [] if e.get("origin") not in (None, "mine")]
              for key in ("skills", "plugins")}
    rest.update({f"available_{key}": value for key, value in others.items() if value})
    if unreadable:
        rest["not_saved"] = unreadable
    items.append(Captured(Kind.NATIVE, "account", origin,
                          {"account/account.yaml": yaml_io.dump(rest).encode()}))
    return items
