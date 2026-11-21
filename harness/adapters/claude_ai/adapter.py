"""``ClaudeAiAdapter``: capture a Claude account (claude.ai, Claude Desktop, Cowork in the cloud).

The account is saved by the ``harness-account`` skill, uploaded once per account: it
sends what the account has built, and conversation summaries, through the harness
connector into the repository's inbox (see ``harness/inbox.py``). A data export, when
one is found, is imported too (the history from before the skill).

claude.ai keeps chats and projects in the account, not on the computer; the
complete, official way out is the data export (a zip sent by e-mail). This
adapter imports every export it finds in ``claude_ai.watch_folder`` (all
settings under ``claude_ai:`` in harness.config.yaml). It runs on the same
schedule as other tools without hooks, so a downloaded export is saved without
anything else to do. Each account (by e-mail) is its own profile.

  conversations ... session records (real dates, title, message count); the
                    full conversation and its attachments go to transcript storage
  projects ........ core/projects/<name>/ (instructions + knowledge files)
  memory .......... memory/
"""

from __future__ import annotations

import hashlib
import json
import os
from fnmatch import fnmatch
from pathlib import Path

from ...harvest import Captured, HarvestReport, HarvestSync, Kind
from ...local import LocalHome, StateFile
from ...profiles import ProfileRegistry
from ...provenance import Origin, now_iso, to_iso
from ...repo import ContentRepo
from ...sessions import SessionRecord
from ...storage import Storage
from ...text import slugify
from ..base import Account, HarnessNotConfigured, adapters
from ..connector import ConnectorAdapter
from .export import ClaudeAiExport, Conversation

TOOL = "claude-ai"
#: Skill names may not contain "claude" (reserved by claude.ai).
SKILL_NAME = "harness-account"


@adapters.register
class ClaudeAiAdapter(ConnectorAdapter):
    tool = TOOL
    capture_modes = ("scheduled", "on_demand")
    capture_reason = ("the account skill sends through the harness connector; the inbox is "
                      "processed in GitHub (Actions), exports are picked up when downloaded")
    environment = "cloud"  # an account service, not a machine
    account_question = ("The e-mail address of your claude.ai account (several: separate them with "
                        "commas). If you don't use claude.ai, just press Enter")
    offered_everywhere = True
    ALWAYS_ON = "claude.ai Settings > General > personal preferences (they apply in Cowork too)"
    #: What is particular to the Claude account, filled into the engine's save instructions.
    TOOL_NOTES = {
        "TOOL_TITLE": "Claude account",
        "SCOPE": "this Claude account (claude.ai, Claude Desktop, Cowork)",
        "NOT_HERE_SHORT": "Not for Claude Code (it saves itself). ",
        "NOT_HERE_LONG": ("Not in Claude Code (a coding agent in a terminal, IDE or Claude Code on the "
                          "web): there, do nothing with this skill."),
        "NOT_HERE": ("**Not in Claude Code:** Claude Code is saved by the harness itself (completely, "
                     "with its own hooks). If you are running as Claude Code (a coding agent in a "
                     "terminal, IDE or Claude Code on the web), do nothing with this skill."),
        "SETUP": ('Create one Cowork scheduled task: name "Harness - describe account", every day, '
                  'prompt: "Run the harness-account skill in describe mode." Then run describe mode '
                  "once now."),
        "WHERE_SKILLS": " (read them where skills are kept for you, e.g. /mnt/skills/user/<skill>/)",
        "APPS_NAME": "artifacts",
        "APPS_HOW": ("Read the files with the artifact tools and copy them exactly: for a plain page its "
                     "HTML as `index.html`; for an artifact made from a type (slides, docs...) only its "
                     "own files under `project/` (never the type's files such as `artifact-type/` or the "
                     "type's `index.html`). The artifact's own database is not copied."),
        "SURFACE": "claude-ai",
        "SURFACES": "cowork | claude-ai | desktop",
    }

    def __init__(self, local: LocalHome | None = None, watch_folder: Path | None = None) -> None:
        super().__init__(local)
        self._watch_folder = watch_folder

    # --- where exports are ----------------------------------------------------------------

    def _settings(self):
        root = self.local.content_repo()
        if root and ContentRepo(root).config_file.path.is_file():
            return ContentRepo(root).config.claude_ai
        from ...config import ClaudeAiSettings
        return ClaudeAiSettings()

    def exports(self) -> list[ClaudeAiExport]:
        settings = self._settings()
        folder = self._watch_folder or Path(settings.watch_folder).expanduser()
        if not folder.is_dir():
            return []
        found = [ClaudeAiExport(p) for p in sorted(folder.glob(settings.file_pattern)) if p.is_file()]
        return [e for e in found if e.is_valid()]

    def is_present(self) -> bool:
        return bool(self.exports())

    def is_connected(self) -> bool:
        """Connected once its accounts (e-mails) are named, even before the first export arrives."""
        return bool(self.bindings())

    def accounts(self) -> list[Account]:
        summary: dict[str, list[ClaudeAiExport]] = {}
        for export in self.exports():
            summary.setdefault(export.account, []).append(export)
        accounts = []
        for email, exports in summary.items():
            latest = exports[-1]
            accounts.append(Account(email, f"claude.ai {email}: {len(latest.conversations())} conversations, "
                                           f"{len(latest.projects())} projects"))
        return accounts

    def skill_folder(self) -> Path:
        configured = self._settings().skill_folder
        return Path(configured).expanduser() if configured else _visible_folder()

    @property
    def SKILLS_PAGE(self) -> str:  # noqa: N802 - the base's setting, from this harness's config
        return self._settings().skills_page

    def after_setup(self, profiles: list[str]) -> list[str]:
        """One skill file per account, and the steps for each account by its e-mail."""
        settings = self._settings()
        steps = ["Once for all accounts and tools: set up the harness connector "
                 "(docs/connector.md) and add it in claude.ai: Settings > Connectors."]
        for email, profile in self.bindings().items():
            if profile not in profiles:
                continue
            target = self.deliver_skill(account=email)
            steps.append(f"Signed in to claude.ai as {email}: upload {target} on {settings.skills_page}.")
            steps.append("Then, in Cowork (same account), type: Set up harness-account")
            steps.append(f"Required, once: add to {self.ALWAYS_ON}: {self.always_on_line()}")
        steps.append("Can't find a skill file later? Run: python -m harness skill claude-ai")
        return steps

    def scheduled_tasks(self) -> list[tuple[str, str]]:
        """The Cowork scheduled task the skill's setup mode creates: (when, what it runs)."""
        return [("every day", f"Run the {SKILL_NAME} skill in describe mode.")]

    # --- what an export holds ----------------------------------------------------------------

    def harvest(self, exclude: list[str] | None = None) -> list[Captured]:
        return [item for export in self.exports() for item in self._items(export, exclude or [])]

    def _items(self, export: ClaudeAiExport, exclude: list[str]) -> list[Captured]:
        items: list[Captured] = []
        for project in export.projects():
            files = {f"knowledge/{name}": content.encode("utf-8") for name, content in project.docs}
            items.append(Captured(Kind.PROJECT, project.name, f"{export.path.name}: project {project.uuid}",
                                  files, meta={"description": project.description or project.name,
                                               "fields": {"title": project.name,
                                                          "instructions": project.instructions,
                                                          "created_at": to_iso(project.created_at) or ""}}))
        for number, text in enumerate(export.memories(), 1):
            items.append(Captured(Kind.MEMORY, f"memory-{number}", f"{export.path.name}: memory",
                                  {f"memory-{number}.md": text.encode("utf-8")}))
        return [i for i in items if not any(fnmatch(f"{i.kind.value}:{i.name}", p) for p in exclude)]

    def preview(self, exclude: list[str]) -> list[str]:
        lines = []
        for export in self.exports():
            counts = (len(export.conversations()), len(export.projects()), len(export.memories()))
            lines.append(f"{export.path.name} ({export.account}): {counts[0]} conversations, "
                         f"{counts[1]} projects, {counts[2]} memories")
            lines += [f"  project     {p.name}" for p in export.projects()]
        return lines

    # --- capture ----------------------------------------------------------------------------------

    def run_harvest(self, session: str | None = None) -> HarvestReport:
        repo = self.repo()
        config = repo.config
        report = HarvestReport()
        processed = self.local.state("exports", self.tool)
        for export in self.exports():
            signature = _file_signature(export.path)
            if processed.get(export.path.name) == signature:
                continue
            profile = self.bindings().get(export.account)
            if not profile:
                report.errors.append(f"{export.path.name}: account {export.account} is not connected "
                                     "(run `harness setup claude-ai`)")
                continue
            part = HarvestSync(repo, self.local.state("harvest", profile)).run(
                self._items(export, config.harvest_exclude), Origin.now(profile, session))
            report.merge(part)
            storage = repo.storage("transcripts", profile)
            state = self.local.state("conversations", profile)
            with storage.batch():
                for conversation in export.conversations():
                    action = ConversationImporter(repo, profile, storage, state).run(conversation)
                    if action:
                        report.counts[f"conversations {action}"] += 1
                if config.claude_ai.archive_exports:
                    storage.write_bytes(f"{profile}/exports/{export.path.name}", export.path.read_bytes())
            state.save()
            processed.set(export.path.name, signature)
            processed.save()
        return report

    # --- installation --------------------------------------------------------------------------

    def install(self, profile_id: str, label: str, repo_root: Path | None = None, hooks: bool = True,
                environment: str | None = None, account_key: str | None = None) -> list[str]:
        done: list[str] = []
        if repo_root:
            self.local.save_settings(content_repo=str(Path(repo_root).resolve()))
        if not account_key:
            raise HarnessNotConfigured("Which claude.ai account? (its e-mail address)")
        profile = ProfileRegistry(self.repo()).add(self.tool, label, profile_id=profile_id,
                                                   environment=environment or self.environment)
        self.bind(account_key, profile.id)
        done.append(f"claude.ai {account_key} -> {profile.id}")
        if hooks:
            done.append(self.schedule())
        return done


class ConversationImporter:
    """One claude.ai conversation -> session record + transcript (+ attachments) in storage."""

    def __init__(self, repo: ContentRepo, profile: str, storage: Storage, state: StateFile) -> None:
        self.repo = repo
        self.profile = profile
        self.storage = storage
        self.state = state

    def run(self, conversation: Conversation) -> str | None:
        version = conversation.updated_at or str(conversation.messages)
        if self.state.get(conversation.uuid) == version:
            return None
        session = SessionRecord(self.repo, self.profile, conversation.uuid)
        new = not session.meta_path.is_file()
        ended = to_iso(conversation.updated_at)
        if new:
            session.touch(activity_at=ended, started_at=to_iso(conversation.created_at) or now_iso(),
                          imported_at=now_iso())
        key = session.storage_key("conversation.json")
        self.storage.write_text(key, json.dumps(conversation.raw, ensure_ascii=False, indent=1))
        files = []
        for name, text in conversation.attachments:
            relative = f"attachments/{slugify(Path(name).stem)}{Path(name).suffix or '.txt'}"
            self.storage.write_text(session.storage_key(f"files/{relative}"), text)
            files.append({"path": relative, "size": len(text.encode("utf-8"))})
        session.touch(activity_at=ended, topic=conversation.name or None, transcript=key,
                      files=files or None)
        self.state.set(conversation.uuid, version)
        return "imported" if new else "updated"


def _file_signature(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha256(f"{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()


def _visible_folder() -> Path:
    """When claude_ai.skill_folder is empty: the desktop the user actually sees (on Windows
    often redirected into OneDrive), else Downloads, else home."""
    candidates = [_windows_desktop()] if os.name == "nt" else []
    candidates += [Path.home() / "Desktop", Path.home() / "Downloads"]
    for folder in candidates:
        if folder and folder.is_dir():
            return folder
    return Path.home()


def _windows_desktop() -> Path | None:
    """The Desktop folder as Windows has it configured (it may live in OneDrive)."""
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            value, _ = winreg.QueryValueEx(handle, "Desktop")
        return Path(os.path.expandvars(value))
    except OSError:
        return None
