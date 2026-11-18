"""``ClaudeAiAdapter``: capture claude.ai (chats, projects, memory) from its data export.

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
import webbrowser
import zipfile
from fnmatch import fnmatch
from importlib import resources
from pathlib import Path
from string import Template

from ...harvest import Captured, HarvestReport, HarvestSync, Kind
from ...local import LocalHome, StateFile
from ...profiles import ProfileRegistry
from ...provenance import Origin, now_iso, to_iso
from ...repo import ContentRepo
from ...sessions import SessionRecord
from ...storage import Storage
from ...text import slugify
from ..base import Account, AccountBoundAdapter, HarnessNotConfigured, adapters
from .export import ClaudeAiExport, Conversation

TOOL = "claude-ai"
#: Skill names may not contain "claude" (reserved by claude.ai).
SKILL_NAME = "harness-export"


@adapters.register
class ClaudeAiAdapter(AccountBoundAdapter):
    tool = TOOL
    environment = "cloud"  # an account service, not a machine
    account_question = ("Do you also use claude.ai (chats, projects)? "
                        "Its account e-mail(s), separated by commas")
    offered_everywhere = True

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

    def deliver_skill(self, target: Path | None = None) -> Path:
        """Write the export skill where the user sees it, show it, and open the upload page."""
        name, files = self.skill_package()
        target = target or _visible_folder() / f"{name}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, content in files.items():
                archive.writestr(path, content)
        webbrowser.open(self._settings().skills_page)
        return target

    def after_setup(self, profiles: list[str]) -> list[str]:
        """Put the export skill where the user will find it and open the page to upload it."""
        target = self.deliver_skill()
        accounts = "each of your claude.ai accounts" if len(profiles) > 1 else "your claude.ai account"
        return [f"In {accounts}, upload the file {target} in claude.ai (a page just opened): "
                f"Settings > Capabilities > Skills > Upload skill. "
                f"Can't find the file later? Run: python -m harness skill claude-ai",
                "Then, in Cowork (in each account), type: Set up my harness export"]

    def scheduled_tasks(self) -> list[tuple[str, str]]:
        """The two Cowork scheduled tasks that run the export skill: (when, what to type)."""
        s = self._settings()
        return [(f"every {s.export_every_days} days",
                 f"Run the {SKILL_NAME} skill in request mode."),
                (f"every {s.export_every_days} days, {s.download_after_hours} hours after the first",
                 f"Run the {SKILL_NAME} skill in download mode.")]

    def skill_package(self) -> tuple[str, dict[str, bytes]]:
        """The export skill, filled in from this harness's `claude_ai` settings."""
        settings = self._settings()
        template = resources.files(__package__).joinpath("skill", "SKILL.md").read_text("utf-8")
        text = Template(template).safe_substitute(
            WATCH_FOLDER=str(Path(settings.watch_folder).expanduser()),
            EVERY_DAYS=settings.export_every_days, DOWNLOAD_AFTER=settings.download_after_hours)
        return SKILL_NAME, {f"{SKILL_NAME}/SKILL.md": text.encode("utf-8")}

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
            report.counts.update(part.counts)
            report.errors += part.errors
            report.conflicts += part.conflicts
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
    """The desktop the user actually sees (on Windows often redirected into OneDrive),
    else Downloads, else home."""
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
