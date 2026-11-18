"""``CoworkAdapter``: capture from Cowork in the Claude desktop app.

Cowork has no hooks, so capture runs on a schedule (Task Scheduler / cron, every
``capture_modes.cowork`` in the config). Each signed-in account is its own profile.

Per account it captures:
  skills ........... the account's skills (skills-plugin/.../skills/<name>/)
  plugins .......... plugins installed in Cowork (whole, unless excluded)
  memory ........... the agent memory folder
  scheduled tasks .. as workflows (Cowork's and the app's Claude Code's)
  conversations .... every Cowork conversation and persistent agent: a session
                     record, the full transcript, the action log (audit.jsonl),
                     and the files uploaded and produced (uploads/, outputs/)

Conversation files go to transcript storage, never into Git.
"""

from __future__ import annotations

import hashlib
import json
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from ...harvest import Captured, HarvestReport, HarvestSync, Kind
from ...local import LocalHome, StateFile
from ...profiles import ProfileRegistry
from ...provenance import Origin, now_iso
from ...repo import ContentRepo
from ...sessions import SessionRecord
from ...storage import Storage
from ..base import Account, AccountBoundAdapter, HarnessNotConfigured, adapters
from ..claude_code.transcript import TranscriptReader
from .locations import CoworkAccount, CoworkLocations

TOOL = "cowork"
MAX_FILE_BYTES = 50 * 1024 * 1024
#: Session sub-folders that are not the conversation's own content.
SKIPPED = frozenset({"host-cwd", "uploads-tmp"})
FILE_FOLDERS = ("uploads", "outputs")


@adapters.register
class CoworkAdapter(AccountBoundAdapter):
    tool = TOOL
    capture_modes = ("on_demand", "scheduled")
    capture_reason = "conversations and files live on one computer only"

    def __init__(self, local: LocalHome | None = None, locations: CoworkLocations | None = None) -> None:
        super().__init__(local)
        self.locations = locations or CoworkLocations.detect()

    # --- accounts and wiring ---------------------------------------------------------

    def accounts(self) -> list[Account]:
        found = []
        for account in self.locations.accounts():
            sessions = len(account.session_folders()) + len(account.agent_folders())
            skills = sorted(p.parent.name for p in (account.skills_folder / "skills").glob("*/SKILL.md"))
            found.append(Account(account.key, f"account {account.short}…: {sessions} conversations, "
                                              f"skills: {', '.join(skills) or 'none'}"))
        return found

    def _bound(self) -> list[tuple[CoworkAccount, str]]:
        bound = [(a, self.bindings()[a.key]) for a in self.locations.accounts() if a.key in self.bindings()]
        if not bound:
            raise HarnessNotConfigured("No Cowork account is connected. Run `harness setup cowork`.")
        return bound

    # --- what each account holds --------------------------------------------------------

    def harvest(self, exclude: list[str] | None = None) -> list[Captured]:
        return [item for account in self.locations.accounts() for item in self._items(account, exclude)]

    def _items(self, account: CoworkAccount, exclude: list[str] | None) -> list[Captured]:
        items: list[Captured] = []
        for main in sorted((account.skills_folder / "skills").glob("*/SKILL.md")):
            items.append(Captured(Kind.SKILL, main.parent.name, str(main.parent), _files(main.parent)))
        for folder in account.plugin_folders():
            manifest = _read_json(folder / ".claude-plugin" / "plugin.json")
            name = manifest.get("name") or folder.name
            description = manifest.get("description") or name
            items.append(Captured(Kind.CONNECTION, name, str(folder), meta={
                "tool": TOOL, "kind": "plugin", "description": description}))
            items.append(Captured(Kind.PLUGIN, name, str(folder), _files(folder),
                                  meta={"description": description}))
        for path in account.scheduled_task_files():
            surface = "cowork" if path.parent == account.folder else "claude-code"
            for task in _read_json(path).get("scheduledTasks") or []:
                if isinstance(task, dict):
                    items.append(_workflow_item(task, path, surface))
        if account.memory_folder.is_dir():
            for path in sorted(account.memory_folder.rglob("*.md")):
                items.append(Captured(Kind.MEMORY, path.stem, str(path), {path.name: path.read_bytes()}))
        rules = _Exclusions(exclude or [])
        return [i for i in items if not rules.match(i.kind.value, i.name)]

    # --- capture ---------------------------------------------------------------------------

    def run_harvest(self, session: str | None = None) -> HarvestReport:
        """Capture everything from every connected account (skills, plugins, memory, conversations)."""
        repo = self.repo()
        config = repo.config
        report = HarvestReport()
        for account, profile in self._bound():
            if config.harvest_enabled:
                items = self._items(account, config.harvest_exclude)
                part = HarvestSync(repo, self.local.state("harvest", profile)).run(
                    items, Origin.now(profile, session))
                report.counts.update(part.counts)
                report.conflicts += part.conflicts
                report.errors += part.errors
            storage = repo.storage("transcripts", profile)
            state = self.local.state("conversations", profile)
            with storage.batch():
                for folder in account.session_folders() + account.agent_folders():
                    try:
                        action = ConversationImporter(repo, profile, storage, state).run(folder)
                    except Exception as exc:  # one broken conversation must not stop the rest
                        report.errors.append(f"{folder.name}: {exc}")
                        continue
                    if action:
                        report.counts[f"conversations {action}"] += 1
            state.save()
        return report

    def preview(self, exclude: list[str]) -> list[str]:
        lines = [f"{i.kind.value:11} {i.name}" for i in self.harvest(exclude)]
        conversations = sum(len(a.session_folders()) + len(a.agent_folders())
                            for a in self.locations.accounts())
        return lines + [f"conversations: {conversations} (with their files)"]

    # --- installation ------------------------------------------------------------------------

    def install(self, profile_id: str, label: str, repo_root: Path | None = None, hooks: bool = True,
                environment: str | None = None, account_key: str | None = None) -> list[str]:
        done: list[str] = []
        if repo_root:
            self.local.save_settings(content_repo=str(Path(repo_root).resolve()))
            done.append(f"harness repository: {Path(repo_root).resolve()}")
        account_key = account_key or self._only_account_key()
        profile = ProfileRegistry(self.repo()).add(self.tool, label, profile_id=profile_id,
                                                   environment=environment or "local")
        self.bind(account_key, profile.id)
        done.append(f"Cowork account {account_key[:8]}… -> {profile.id}")
        if hooks:
            done.append(self.schedule())
        return done

    def _only_account_key(self) -> str:
        accounts = self.locations.accounts()
        if len(accounts) != 1:
            raise HarnessNotConfigured("Several Cowork accounts found; choose one (harness setup cowork).")
        return accounts[0].key


class ConversationImporter:
    """Copies one Cowork conversation (or agent) folder into the harness, when it changed."""

    def __init__(self, repo: ContentRepo, profile: str, storage: Storage, state: StateFile) -> None:
        self.repo = repo
        self.profile = profile
        self.storage = storage
        self.state = state

    def run(self, folder: Path) -> str | None:
        """Returns 'imported', 'updated', or None when nothing changed since last time."""
        name = folder.name if folder.parent.name != "agent" else f"agent-{folder.name}"
        signature = _signature(folder)
        if self.state.get(name) == signature:
            return None
        session = SessionRecord(self.repo, self.profile, name)
        new = not session.meta_path.is_file()
        transcript = _main_transcript(folder)
        span = TranscriptReader(transcript).span() if transcript else None
        ended = span.ended_at if span else None
        if new:
            session.touch(activity_at=ended, started_at=(span.started_at if span else None) or now_iso(),
                          imported_at=now_iso())
        if transcript:
            session.save_transcript(self.storage, transcript, activity_at=ended)
        audit = folder / "audit.jsonl"
        if audit.is_file():
            self.storage.write_text(session.storage_key("audit.jsonl"), audit.read_text("utf-8"))
        files = self._copy_files(folder, session)
        session.touch(activity_at=ended, files=files or None)
        self.state.set(name, signature)
        return "imported" if new else "updated"

    def _copy_files(self, folder: Path, session: SessionRecord) -> list[dict[str, Any]]:
        listed = []
        for kind in FILE_FOLDERS:
            base = folder / kind
            for path in sorted(base.rglob("*")) if base.is_dir() else []:
                if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                    continue
                relative = f"{kind}/{path.relative_to(base).as_posix()}"
                self.storage.write_bytes(session.storage_key(f"files/{relative}"), path.read_bytes())
                listed.append({"path": relative, "size": path.stat().st_size})
        return listed


class _Exclusions:
    def __init__(self, patterns: list[str]) -> None:
        self.patterns = patterns

    def match(self, kind: str, name: str) -> bool:
        return any(fnmatch(f"{kind}:{name}", p) for p in self.patterns)


def _workflow_item(task: dict[str, Any], source: Path, surface: str) -> Captured:
    """A scheduled task as a workflow. Field names vary, so common ones are tried and the
    whole original record is kept under ``native``."""
    def first(*keys: str) -> str:
        return next((str(task[k]) for k in keys if task.get(k)), "")

    prompt = first("prompt", "instructions", "message", "task", "text")
    name = first("name", "title", "label", "id") or "scheduled-task"
    return Captured(Kind.WORKFLOW, name, str(source), meta={
        "description": first("description", "summary") or prompt[:200] or name,
        "prompt": prompt or name,
        "trigger": first("schedule", "cron", "cronExpression", "rrule", "frequency", "interval"),
        "native": {"surface": surface, **task},
    })


def _main_transcript(folder: Path) -> Path | None:
    """The conversation's main transcript (sub-agent transcripts are part of it, not separate)."""
    candidates = [p for p in folder.rglob("*.jsonl") if p.name != "audit.jsonl"
                  and "subagents" not in p.parts and not set(p.relative_to(folder).parts) & SKIPPED]
    return max(candidates, key=lambda p: p.stat().st_size) if candidates else None


def _signature(folder: Path) -> str:
    """Cheap change detection: names, sizes and times of the folder's files."""
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file() and not set(path.relative_to(folder).parts) & SKIPPED:
            stat = path.stat()
            digest.update(f"{path.relative_to(folder).as_posix()}|{stat.st_size}|{stat.st_mtime_ns}".encode())
    return digest.hexdigest()


def _files(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*"))
            if p.is_file() and p.stat().st_size <= MAX_FILE_BYTES
            and not any(part.startswith(".") and part != ".claude-plugin"
                        for part in p.relative_to(folder).parts[:-1])}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


