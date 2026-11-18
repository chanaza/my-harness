"""``ClaudeCodeAdapter``: capture from Claude Code through its hooks.

Hook events and what they do:

  SessionStart      register the session; harvest (background)
  UserPromptSubmit  count the message; if a checkpoint is pending, hand the request to
                    the model as hidden context (nothing is shown to the user)
  Stop              decide whether a checkpoint is due; in the background: harvest,
                    workspace state, transcript, commit and push
  PreCompact        save the transcript
  SessionEnd        save the transcript; commit and push

Hooks are built to be invisible: they print nothing, return within moments,
and log problems to ~/.my-harness/logs/ instead of showing them
(`harness status` lists recent problems).

Per session this keeps exactly three things: meta.yaml and summary.md in Git,
and the full transcript in transcript storage. Everything else (recent
exchanges, compaction summaries) is derived from the transcript when needed.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any, TypeVar

from ...background import ProcessLock, spawn_detached
from ...checkpoints import CheckpointPolicy, CheckpointRecorder
from ...config import HarnessConfig
from ...digest import SECTIONS
from ...git_sync import GitSync
from ...harvest import Captured, HarvestReport, HarvestSync
from ...local import LocalHome
from ...profiles import ProfileRegistry
from ...provenance import Origin, now_iso
from ...repo import ContentRepo
from ...sessions import SessionRecord
from ...workspace import WorkspaceScanner, merge_workspace
from ..base import Account, Adapter, HarnessNotConfigured, adapters
from .constants import HOOK_EVENTS, HOOK_MARKER, SKILL_NAME, TOOL
from .harvester import ClaudeCodeHarvester
from .locations import ClaudeCodeLocations
from .transcript import ContextMeter, TranscriptReader

T = TypeVar("T")


@dataclass(frozen=True)
class BackfillEntry:
    session: str
    project: str | None
    started_at: str | None
    ended_at: str | None
    user_messages: int
    action: str = "found"  # found (dry run) | imported | updated | unchanged


@adapters.register
class ClaudeCodeAdapter(Adapter):
    tool = TOOL

    def __init__(self, local: LocalHome | None = None,
                 locations: ClaudeCodeLocations | None = None) -> None:
        super().__init__(local)
        self.locations = locations or ClaudeCodeLocations.detect()

    # --- wiring -------------------------------------------------------------------

    def repo(self) -> ContentRepo:
        root = self.local.content_repo()
        if not root:
            raise HarnessNotConfigured("No content repository configured. Run `harness install claude-code`.")
        return ContentRepo(root)

    def profile_id(self) -> str:
        profiles = (self.local.settings().get("profiles") or {}).get(self.tool) or {}
        profile = profiles.get(self.locations.key)
        if not profile:
            raise HarnessNotConfigured(f"No profile bound to {self.locations.config_dir}. "
                                       "Run `harness install claude-code --profile ...`.")
        return profile

    # --- harvest --------------------------------------------------------------------

    def harvest(self, exclude: list[str] | None = None) -> list[Captured]:
        return ClaudeCodeHarvester(self.locations, exclude).collect()

    def run_harvest(self, session: str | None = None) -> HarvestReport:
        """Harvest and write into the content repository (the only way content gets in)."""
        repo, profile = self.repo(), self.profile_id()
        config = repo.config
        if not config.harvest_enabled:
            return HarvestReport()
        items = self.harvest(config.harvest_exclude)
        state = self.local.state("harvest", profile)
        return HarvestSync(repo, state).run(items, Origin.now(profile, session))

    def prune_harvest(self) -> list[str]:
        """Remove previously harvested items that are now excluded (by config or as engine-owned)."""
        repo, profile = self.repo(), self.profile_id()
        excluded = ClaudeCodeHarvester(self.locations, repo.config.harvest_exclude).is_excluded
        return HarvestSync(repo, self.local.state("harvest", profile)).prune(excluded, profile)

    # --- backfill (sessions from before the harness was installed) -----------------------

    def transcripts(self) -> list[Path]:
        """Main-thread transcripts of every session this account has on this machine."""
        projects = self.locations.config_dir / "projects"
        return sorted(projects.glob("*/*.jsonl")) if projects.is_dir() else []

    def backfill(self, since_days: int | None = None, dry_run: bool = False) -> list[BackfillEntry]:
        """Import past sessions: a session record with their real dates, and the transcript.

        Idempotent. Sessions already recorded live keep their meta; only the
        transcript is refreshed. No summary is invented: imported sessions have
        none until the loading step derives one from the transcript.
        """
        repo, profile = self.repo(), self.profile_id()
        storage = None if dry_run else repo.storage("transcripts", profile)
        cutoff = (datetime.now(UTC) - timedelta(days=since_days)).isoformat() if since_days else None
        entries = []
        for path in self.transcripts():
            span = TranscriptReader(path).span()
            if cutoff and (span.ended_at or "") < cutoff[:19]:
                continue
            session = SessionRecord(repo, profile, path.stem)
            project = _folder_name(span.cwd)
            entry = BackfillEntry(session.id, project, span.started_at, span.ended_at, span.user_messages)
            if dry_run:
                entries.append(entry)
                continue
            new = not session.meta_path.is_file()
            if new:
                session.touch(activity_at=span.ended_at, started_at=span.started_at or now_iso(),
                              project=project, imported_at=now_iso())
            _, changed = session.save_transcript(storage, path, activity_at=span.ended_at)
            entries.append(replace(entry, action="imported" if new else
                                   ("updated" if changed else "unchanged")))
        return entries

    # --- hooks -----------------------------------------------------------------------

    def handle_hook(self, event: dict[str, Any], deferred: bool = False) -> dict[str, Any] | None:
        """React to a Claude Code hook event.

        Hooks return fast; slow work (harvest, transcript, commit, push) is handed to
        ``self.defer``, which by default runs it in a detached background process.
        """
        name = event.get("hook_event_name", "")
        self.locations = self.locations.for_project(Path(event["cwd"]) if event.get("cwd") else None)
        context = _HookContext(self, event)
        prefix = "deferred_" if deferred else "on_"
        handler = getattr(context, f"{prefix}{_snake(name)}", None)
        return handler() if handler else None

    def defer(self, event: dict[str, Any]) -> None:
        """Run the slow part of ``event`` later (background). Tests replace this to run inline."""
        if self.repo().config.capture.background:
            spawn_detached(["hook", self.tool, "--deferred"], json.dumps(event))
        else:
            self.handle_hook(event, deferred=True)

    # --- installation ------------------------------------------------------------------

    def is_present(self) -> bool:
        return self.locations.config_dir.is_dir()

    def accounts(self) -> list[Account]:
        return [Account(self.locations.key, f"Claude Code ({self.locations.config_dir})")]

    def preview(self, exclude: list[str]) -> list[str]:
        return super().preview(exclude) + [f"conversations: {len(self.transcripts())}"]

    def capture(self) -> str:
        report = self.run_harvest()
        return f"{report.summary()}; conversations: {len(self.backfill())}"

    def install(self, profile_id: str, label: str, repo_root: Path | None = None,
                hooks: bool = True, environment: str | None = None,
                account_key: str | None = None) -> list[str]:
        done: list[str] = []
        if repo_root:
            self.local.save_settings(content_repo=str(Path(repo_root).resolve()))
            done.append(f"content repository: {Path(repo_root).resolve()}")
        repo = self.repo()
        profile = ProfileRegistry(repo).add(self.tool, label, profile_id=profile_id,
                                            environment=environment)
        done.append(f"profile: {profile.id}")

        settings = self.local.settings()
        bound = settings.setdefault("profiles", {}).setdefault(self.tool, {})
        bound[self.locations.key] = profile.id
        self.local.save_settings(profiles=settings["profiles"])
        done.append(f"{self.locations.config_dir} -> {profile.id}")

        if hooks:
            self._install_hooks(f'"{sys.executable}" {HOOK_MARKER}')
            done.append(f"hooks in {self.locations.settings_file}: {', '.join(HOOK_EVENTS)}")
            done.append(f"skill: {self._install_skill(profile.id)}")
        return done

    def _install_hooks(self, command: str) -> None:
        path = self.locations.settings_file
        settings = json.loads(path.read_text("utf-8")) if path.is_file() else {}
        hooks = settings.setdefault("hooks", {})
        for event in HOOK_EVENTS:
            groups = [g for g in hooks.get(event, [])
                      if not any(HOOK_MARKER in h.get("command", "") for h in g.get("hooks", []))]
            groups.append({"hooks": [{"type": "command", "command": command, "timeout": 60}]})
            hooks[event] = groups
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def _install_skill(self, profile_id: str) -> Path:
        template = resources.files(__package__).joinpath("skill", "SKILL.md").read_text("utf-8")
        text = Template(template).safe_substitute(PYTHON=sys.executable, PROFILE=profile_id)
        target = self.locations.config_dir / "skills" / SKILL_NAME / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target


class _HookContext:
    """Everything one hook invocation needs, built once."""

    def __init__(self, adapter: ClaudeCodeAdapter, event: dict[str, Any]) -> None:
        self.adapter = adapter
        self.event = event
        self.repo = adapter.repo()
        self.config: HarnessConfig = self.repo.config
        self.profile = adapter.profile_id()
        self.session = SessionRecord(self.repo, self.profile, event.get("session_id") or "unknown")
        self.transcript = TranscriptReader(Path(event.get("transcript_path") or ""))
        self.recorder = CheckpointRecorder(adapter.local, self.repo, self.session)
        self.recorder.mark_current()
        self.policy = CheckpointPolicy(self.config.checkpoints)
        self.git = GitSync(self.repo.root, self.config.git)

    # --- events ---------------------------------------------------------------------

    def on_session_start(self) -> None:
        if self.event.get("source") == "compact":
            self.recorder.mark_compacted()  # a checkpoint is requested with the next prompt
        self.adapter.defer(self.event)

    def deferred_session_start(self) -> None:
        project = self.adapter.locations.project_dir
        self.session.touch(project=project.name if project else None)
        with self._sync_lock() as lock:
            if lock.acquired:
                self._safely("harvest", lambda: self.adapter.run_harvest(self.session.id))
                self._sync(f"session {self.session.id} started", push=self.config.git.push_every_turn)

    def on_user_prompt_submit(self) -> dict[str, Any] | None:
        """Count the message; if a checkpoint is pending, pass the request quietly to the model."""
        self.recorder.count_user_message()
        reason = self.recorder.pending_request()
        if not reason:
            return None
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                       "additionalContext": self._checkpoint_request(reason)}}

    def on_stop(self) -> dict[str, Any] | None:
        """Fast: decide whether a checkpoint is due. Slow work is deferred.

        A due checkpoint is normally requested quietly with the next prompt. Only the
        forced one (context nearly full: there may be no next prompt) blocks here, once.
        """
        if self.event.get("stop_hook_active"):
            return None  # the model is already answering our request; never loop
        percent = self._percent()
        self.recorder.record_turn(percent)
        self.adapter.defer(self.event)
        reason = self.policy.due(self.recorder.progress(), percent)
        if not reason:
            self.recorder.set_pending(None)
            return None
        if self.policy.is_forced(percent) and self.recorder.claim_forced_request():
            return {"decision": "block", "reason": self._checkpoint_request(reason)}
        self.recorder.set_pending(reason)
        return None

    def deferred_stop(self) -> None:
        with self._sync_lock() as lock:
            if not lock.acquired:
                return  # another background sync is running; the next turn catches up
            self.git.pull()  # settings changed on another machine apply before capturing
            report = self._safely("harvest", lambda: self.adapter.run_harvest(self.session.id))
            self._safely("workspace", self._record_workspace)
            self._safely("transcript", self._save_transcript)
            changes = report.summary() if report and report.changed else "activity"
            self._sync(f"session {self.session.id} ({changes})", push=self.config.git.push_every_turn)

    def on_pre_compact(self) -> None:
        self._safely("transcript", self._save_transcript)  # synchronous: before the tool compacts

    def on_session_end(self) -> None:
        self._safely("transcript", self._save_transcript)
        self.session.touch()
        with self._sync_lock(wait=60) as lock:
            if lock.acquired:
                self._sync(f"session {self.session.id} ended", push=True)

    # --- helpers ---------------------------------------------------------------------

    def _safely(self, step: str, action: Callable[[], T]) -> T | None:
        """Run one step; log a failure instead of letting it stop the other steps."""
        try:
            return action()
        except Exception as exc:
            self.adapter.local.log(f"claude-code {self.profile} {step} failed: {exc!r}")
            return None

    def _sync_lock(self, wait: float = 30) -> ProcessLock:
        return ProcessLock(self.adapter.local.root / "locks" / f"sync-{self.profile}.lock", wait=wait)

    def _sync(self, message: str, push: bool = False) -> None:
        result = self.git.sync(f"{self.profile}: {message}", push=push)
        if result.message.startswith("git failed"):
            self.adapter.local.log(result.message)

    def _percent(self) -> float | None:
        meter = ContextMeter(self.config.capture.context_window_tokens)
        return meter.percent(self.transcript.context_tokens())

    def _record_workspace(self) -> None:
        """Merge the repositories found from this turn's folder into the session's list."""
        project = self.adapter.locations.project_dir
        if not project:
            return
        found = [r.to_dict() for r in WorkspaceScanner(project).scan()]
        merged = merge_workspace(self.session.meta().get("workspace") or [], found)
        if merged != self.session.meta().get("workspace"):
            self.session.touch(workspace=merged)

    def _save_transcript(self) -> None:
        self.session.save_transcript(self.repo.storage("transcripts", self.profile), self.transcript.path)

    def _checkpoint_request(self, reason: str) -> str:
        words = self.config.checkpoints.summary_max_words
        sections = "\n".join(f"## {s}" for s in SECTIONS)
        return (
            f"[my-harness checkpoint: {reason}] This is a background housekeeping step for the user's "
            f"harness. Do it silently: do not mention it, do not comment on it, and do not let it "
            f"change your answer. Run the command below once, then continue normally.\n\n"
            f"Write a summary of this WHOLE conversation (not only the latest part) so that a new "
            f"session in any tool could continue from exactly this point, using exactly these "
            f"Markdown sections:\n\n{sections}\n\n"
            f"'Open thread' = what is in progress right now and what you are waiting for from the "
            f"user. 'Standing instructions' = rules the user gave that should apply to future work, "
            f"in their words. 'Preferences learned' = how the user likes to work. 'Connections in "
            f"use' = one line per connector/MCP server available to you here ('- name: purpose'), "
            f"names only. Write 'None' in an empty section. At most {words} words, in "
            f"'{self.config.working_language}'.\n\n"
            f'"{sys.executable}" -m harness session checkpoint --quiet --profile {self.profile} '
            f'--session {self.session.native_id} --reason "{reason}" <<\'HARNESS_EOF\'\n'
            f"<summary>\nHARNESS_EOF"
        )


def _folder_name(path: str | None) -> str | None:
    """Last folder of a path recorded on any OS (Windows or POSIX separators)."""
    if not path:
        return None
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1] or None


def _snake(name: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")
