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
        items = [i for i in describe_items(file, tool, self.repo)
                 if not any(fnmatch(f"{i.kind.value}:{i.name}", p) for p in exclude)]
        # A partial description (e.g. one project, from inside it) keeps its own records, so it
        # neither removes nor replaces what the full daily description saved.
        scope = "describe" if not file.data.get("partial") else \
            "partial-" + slugify("-".join(p["name"] for p in file.data.get("projects") or []) or "items")
        state = StateFile(self.repo.path("inbox", ".state", f"{file.profile}-{scope}.json"))
        part = HarvestSync(self.repo, state).run(items, Origin.now(file.profile, None))
        report.counts.update(part.counts)
        report.conflicts += part.conflicts
        if part.errors:   # an item that could not be saved: keep the file (rejected), never drop it
            raise ValueError("not everything could be saved: " + "; ".join(part.errors))

    def _conversation(self, file: InboxFile, report: HarvestReport) -> None:
        data = file.data
        record = SessionRecord(self.repo, file.profile, file.path.stem)
        record.touch(topic=data.get("title"), surface=data.get("surface"),
                     project=data.get("project") or None, activity_at=to_iso(data.get("saved_at")))
        recorder = CheckpointRecorder(self.local, self.repo, record)
        recorder.write(file.body, "saved through the harness connector")
        # The reply the summary was written at, so the connector knows when the next is due.
        record.touch(summary_reply=int(record.meta().get("log_last") or 0) or None)
        report.counts["conversations saved"] += 1

    def add(self, source: Path) -> Path:
        """Put a file into the inbox after the same form check the processing does (for content
        read by other means, e.g. files copied exactly from a tool; never by hand)."""
        self._read(source)  # raises ValueError when it does not match its form
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / source.name
        shutil.copyfile(source, target)
        return target

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


def conversation_gaps(repo: ContentRepo) -> dict[str, list[int]]:
    """Conversations saved reply by reply in which replies are missing: path -> numbers."""
    gaps = {}
    for meta_path in sorted(repo.root.glob("sessions/*/*/meta.yaml")):
        folder = meta_path.parent
        missing = ConversationLog(SessionRecord(repo, folder.parent.name, folder.name)).missing()
        if missing:
            gaps[folder.relative_to(repo.root).as_posix()] = missing
    return gaps


def write_connector_instructions(repo: ContentRepo) -> list[str]:
    """What the harness connector serves, kept current by the engine:
      connector/instructions/<tool>.md  a tool's skill instructions (saving)
      connector/instructions/reader.md  how any tool reads the harness (served when a tool
                                        has no instructions of its own)
      connector/index.json              everything in the harness, for harness_find"""
    from string import Template

    from . import __version__
    from .adapters import adapters
    files: dict[str, str] = {}
    for tool in adapters.names():
        text = adapters.create(tool).connector_instructions(repo)
        if text is not None:
            files[f"{tool}.md"] = text
    reader = resources.files("harness.templates").joinpath("connector", "reader.md").read_text("utf-8")
    files["reader.md"] = Template(reader).safe_substitute(VERSION=__version__)
    written = []
    for name, text in files.items():
        written += _write_if_changed(repo, repo.path(*INSTRUCTIONS_FOLDER, name), text)
    index = json.dumps(HarnessIndex(repo).entries(), ensure_ascii=False, indent=0)
    return written + _write_if_changed(repo, repo.path("connector", "index.json"), index)


def _write_if_changed(repo: ContentRepo, path: Path, text: str) -> list[str]:
    if path.is_file() and path.read_text("utf-8") == text:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return [path.relative_to(repo.root).as_posix()]


class HarnessIndex:
    """Everything in the harness, so another tool can find it in its own words.

    Every file of the repository is listed (nothing can be missed: a file the index does not
    describe more richly is still listed by its path); items the engine knows are described
    by name and description; conversations by what a person remembers of them - title, date,
    tool and account, project, agent, the goal from their summary and their first message;
    single connections and profiles by name; files kept in transcript storage by their
    `transcripts:` path."""

    SKIPPED = (".git", "inbox/.state", "connector")

    def __init__(self, repo: ContentRepo) -> None:
        self.repo = repo
        self.profiles = {p.id: p for p in ProfileRegistry(repo).all()}

    def entries(self) -> list[dict[str, Any]]:
        from .guide import RepoGuide

        guide = RepoGuide(self.repo)
        guide.load()
        rich: dict[str, dict[str, Any]] = {}
        for entry in self._guides() + self._items() + guide.index_entries() + self._conversations():
            rich.setdefault(entry["path"], entry)
        guide.annotate(found := list(rich.values()))  # which agent each belongs to, what it uses
        described = set(rich)
        for path in sorted(p for p in self.repo.root.rglob("*") if p.is_file()):
            rel = path.relative_to(self.repo.root).as_posix()
            if rel in described or any(rel == s or rel.startswith(f"{s}/") for s in self.SKIPPED):
                continue
            found.append({"kind": "file", "name": path.name, "path": rel, "in": rel.rsplit("/", 1)[0]})
        return found + self._connections() + self._profile_entries()

    def _items(self) -> list[dict[str, Any]]:
        found = []
        for kind, pattern in (("agent", "core/agents/*.yaml"), ("project", "core/projects/*/project.yaml"),
                              ("plugin", "core/plugins/*/plugin.yaml"), ("app", "apps/*/app.yaml"),
                              ("workflow", "core/workflows/*.yaml")):
            for path in sorted(self.repo.root.glob(pattern)):
                data = self._yaml(path)
                name = data.get("title") or data.get("name") or path.parent.name
                about = data.get("description") or data.get("purpose")
                found.append(self._entry(kind, name, about, path, data))
        for path in sorted(self.repo.root.glob("core/skills/*/SKILL.md")):
            meta = MarkdownDocument.parse(path.read_text("utf-8")).meta
            name = meta.get("name") or path.parent.name
            found.append(self._entry("skill", name, meta.get("description"), path, meta))
        for kind, pattern in (("instruction", "core/instructions/**/*.md"), ("memory", "memory/*.md")):
            for path in sorted(self.repo.root.glob(pattern)):
                document = MarkdownDocument.parse(path.read_text("utf-8"))
                first = next((x.strip("# ").strip() for x in document.body.splitlines() if x.strip()), "")
                about = document.meta.get("subject") or first
                found.append(self._entry(kind, path.stem, about, path, document.meta))
        return found

    def _conversations(self) -> list[dict[str, Any]]:
        found = []
        for meta_path in sorted(self.repo.root.glob("sessions/*/*/meta.yaml")):
            data, folder = self._yaml(meta_path), meta_path.parent
            profile = self.profiles.get(folder.parent.name)
            title = data.get("topic") or folder.name
            entry = self._entry("conversation", title, self._goal(folder), folder, data)
            started = str(data.get("started_at") or "")
            missing = ConversationLog(SessionRecord(self.repo, folder.parent.name, folder.name)).missing()
            last = str(data.get("last_activity_at") or data.get("activity_at") or "")
            # `date` is when it was last active: a long conversation still going is found among
            # the recent ones (harness_find's date filter); `started` keeps its first day
            extra = {"date": last[:10] or started[:10], "started": started[:10] or None,
                     "tool": profile.tool if profile else None,
                     "replies_saved": data.get("log_last"), "replies_missing": missing or None,
                     "account": profile.label if profile else None, "project": data.get("project"),
                     "agent": data.get("agent"), "first_message": self._first_message(folder),
                     "summary": self._rel(folder / "summary.md"), "log": self._rel(folder / "log.md"),
                     "raw": f"transcripts:{data['transcript']}" if data.get("transcript") else None,
                     "files": [f"transcripts:{folder.parent.name}/{folder.name}/files/{f['path']}"
                               for f in data.get("files") or [] if f.get("path")] or None}
            entry.update({k: v for k, v in extra.items() if v})
            found.append(entry)
        return found

    def _guides(self) -> list[dict[str, Any]]:
        return [
            {"kind": "guide", "name": "README.md - start here", "path": "README.md",
             "description": "How the harness is organised and why, how its files point to each other, "
                            "real examples of each kind (an agent and its parts, a workflow calling a "
                            "backend function, a conversation and how to continue it), and how to "
                            "search this index for everything else."},
        ]

    def _connections(self) -> list[dict[str, Any]]:
        path = self.repo.path("core", "connections.yaml")
        data = self._yaml(path) if path.is_file() else {}
        return [{"kind": "connection", "name": c.get("id"), "description": c.get("description"),
                 "tools": sorted(c.get("available_in") or {}),
                 "accounts": sorted({p for t in (c.get("available_in") or {}).values()
                                     for p in t.get("profiles") or []}),
                 "path": "core/connections.yaml"}
                for c in data.get("connections") or []]

    def _profile_entries(self) -> list[dict[str, Any]]:
        return [{"kind": "profile", "name": p.id, "tool": p.tool, "account": p.label,
                 "path": "core/profiles.yaml"} for p in self.profiles.values()]

    @staticmethod
    def _goal(folder: Path) -> str | None:
        summary = folder / "summary.md"
        if not summary.is_file():
            return None
        from .digest import split_sections
        body = MarkdownDocument.parse(summary.read_text("utf-8")).body
        return (split_sections(body).get("Goal") or "").strip()

    @staticmethod
    def _first_message(folder: Path) -> str | None:
        log = folder / "log.md"
        if not log.is_file():
            return None
        text = log.read_text("utf-8")
        start = text.find("## User")
        if start < 0:
            return None
        body = text[start + len("## User"):].split("## Assistant", 1)[0]
        return " ".join(body.split())[:200] or None

    def _entry(self, kind: str, name: Any, description: Any, path: Path,
               data: dict[str, Any]) -> dict[str, Any]:
        source = (data.get("provenance") or {}).get("source") or {}
        entry = {"kind": kind, "name": str(name), "path": self._rel(path)}
        if description:
            entry["description"] = " ".join(str(description).split())[:300]
        if data.get("profile") or source.get("profile"):
            entry["profile"] = data.get("profile") or source.get("profile")
        return entry

    def _rel(self, path: Path) -> str | None:
        return path.relative_to(self.repo.root).as_posix() if path.exists() else None

    @staticmethod
    def _yaml(path: Path) -> dict[str, Any]:
        return dict(yaml_io.load(path.read_text("utf-8")) or {})


def _files(entries: list[dict[str, Any]] | None, folder: str = "") -> dict[str, bytes]:
    return {f"{folder}{e['path'].lstrip('/')}": e["content"].encode("utf-8") for e in entries or []}


def _memory_name(entry: dict[str, Any]) -> str:
    """By topic (stable when the tool lists memory in another order)."""
    topic = entry.get("name") or entry["text"].strip().splitlines()[0][:60]
    return slugify(Path(topic).stem if topic.startswith("/") else topic) or "memory"


def saved_apps(repo: ContentRepo) -> dict[str, dict[str, Any]]:
    """apps/<name>/app.yaml of every saved app: its link and version (so unchanged apps are not
    copied again)."""
    found = {}
    for descriptor in sorted(repo.path("apps").glob("*/app.yaml")):
        data = yaml_io.load(descriptor.read_text("utf-8")) or {}
        found[descriptor.parent.name] = {k: data.get(k) for k in ("url", "version")}
    return found


def _complete(path: str, content: str) -> bool:
    """A copied file is whole: a full HTML page ends its document, JSON parses."""
    text = content.strip().lower()
    if path.endswith((".html", ".htm")) and "<html" in text:
        return text.endswith("</html>")
    if path.endswith(".json"):
        try:
            json.loads(content)
        except ValueError:
            return False
    return True


def describe_items(describe: InboxFile, tool: str, repo: ContentRepo | None = None) -> list[Captured]:
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
    saved = saved_apps(repo) if repo else {}
    for entry in data.get("apps") or []:
        if not entry.get("files"):
            same = saved.get(slugify(entry["name"]), {}).get("version") == str(entry.get("version"))
            if entry.get("version") and same:
                continue   # unchanged since it was saved: nothing to copy
            unreadable.append(f"apps: {entry['name']} ({entry.get('not_readable') or 'no content sent'})")
            continue
        broken = [f["path"] for f in entry["files"] if not _complete(f["path"], f["content"])]
        if broken:
            unreadable.append(f"apps: {entry['name']} (incomplete copy of {', '.join(broken)}; not saved)")
            continue
        fields = {k: str(entry[k]) for k in ("link", "version") if entry.get(k)}
        items.append(Captured(Kind.APP, entry["name"], origin, _files(entry["files"]),
                              meta={"description": entry.get("description") or entry["name"],
                                    "fields": fields}))
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
