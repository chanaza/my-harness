"""``ClaudeCodeAdapter``: capture from Claude Code through its hooks.

Hook events and what they do:

  SessionStart      register the session; harvest; after a compaction, make the
                    next Stop ask for a checkpoint
  UserPromptSubmit  count the message toward the next checkpoint
  Stop              harvest; workspace state; save the transcript; commit; when a
                    checkpoint is due, ask the model to refresh the summary
  PreCompact        save the transcript
  SessionEnd        save the transcript; commit and push

Per session this keeps exactly three things: meta.yaml and summary.md in Git,
and the full transcript in transcript storage. Everything else (recent
exchanges, compaction summaries) is derived from the transcript when needed.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any, TypeVar

from ...checkpoints import CheckpointPolicy, CheckpointRecorder
from ...config import HarnessConfig
from ...digest import SECTIONS
from ...git_sync import GitSync
from ...harvest import Captured, HarvestReport, HarvestSync
from ...local import LocalHome
from ...profiles import ProfileRegistry
from ...provenance import Origin
from ...repo import ContentRepo
from ...sessions import SessionRecord
from ...workspace import WorkspaceScanner, merge_workspace
from ..base import Adapter, adapters
from .constants import HOOK_EVENTS, HOOK_MARKER, SKILL_NAME, TOOL
from .harvester import ClaudeCodeHarvester
from .locations import ClaudeCodeLocations
from .transcript import ContextMeter, TranscriptReader

T = TypeVar("T")


class HarnessNotConfigured(Exception):
    pass


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

    # --- hooks -----------------------------------------------------------------------

    def handle_hook(self, event: dict[str, Any]) -> dict[str, Any] | None:
        name = event.get("hook_event_name", "")
        self.locations = self.locations.for_project(Path(event["cwd"]) if event.get("cwd") else None)
        context = _HookContext(self, event)
        handler = getattr(context, f"on_{_snake(name)}", None)
        return handler() if handler else None

    # --- installation ------------------------------------------------------------------

    def install(self, profile_id: str, label: str, repo_root: Path | None = None,
                hooks: bool = True, environment: str | None = None) -> list[str]:
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
        project = self.adapter.locations.project_dir
        self.session.touch(project=project.name if project else None)
        self._safely("harvest", lambda: self.adapter.run_harvest(self.session.id))
        if self.event.get("source") == "compact":
            self.recorder.mark_compacted()  # the next Stop asks for a checkpoint
        self._sync(f"session {self.session.id} started")

    def on_user_prompt_submit(self) -> None:
        self.recorder.count_user_message()

    def on_stop(self) -> dict[str, Any] | None:
        """Every turn: harvest, workspace, transcript, commit. A checkpoint request when due."""
        if self.event.get("stop_hook_active"):
            return None  # the model is already answering our request; never loop
        report = self._safely("harvest", lambda: self.adapter.run_harvest(self.session.id))
        percent = self._percent()
        self.recorder.record_turn(percent)
        self._safely("workspace", self._record_workspace)
        self._safely("transcript", self._save_transcript)
        changes = report.summary() if report and report.changed else "activity"
        self._sync(f"session {self.session.id} ({changes})")
        reason = self.policy.due(self.recorder.progress(), percent)
        return {"decision": "block", "reason": self._checkpoint_request(reason)} if reason else None

    def on_pre_compact(self) -> None:
        self._safely("transcript", self._save_transcript)

    def on_session_end(self) -> None:
        self._safely("transcript", self._save_transcript)
        self.session.touch()
        self._sync(f"session {self.session.id} ended", push=True)

    # --- helpers ---------------------------------------------------------------------

    def _safely(self, step: str, action: Callable[[], T]) -> T | None:
        """Run one step; log a failure instead of letting it stop the other steps."""
        try:
            return action()
        except Exception as exc:
            self.adapter.local.log(f"claude-code {self.profile} {step} failed: {exc!r}")
            return None

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
            f"[my-harness checkpoint: {reason}] Before finishing, refresh the user's harness summary "
            f"of this WHOLE conversation (not only the latest part), so that a new session in any "
            f"tool could continue from exactly this point. Use exactly these Markdown sections:\n\n"
            f"{sections}\n\n"
            f"'Open thread' = what is in progress right now and what you are waiting for from the "
            f"user. 'Standing instructions' = rules the user gave that should apply to future work, "
            f"in their words. 'Preferences learned' = how the user likes to work. 'Connections in "
            f"use' = one line per connector/MCP server available to you here ('- name: purpose'), "
            f"names only. Write 'None' in an empty section. At most {words} words, in "
            f"'{self.config.working_language}'. Run exactly this, with the summary in place of "
            f"<summary>:\n\n"
            f'"{sys.executable}" -m harness session checkpoint --profile {self.profile} '
            f'--session {self.session.native_id} --reason "{reason}" <<\'HARNESS_EOF\'\n'
            f"<summary>\nHARNESS_EOF\n\n"
            f"Then end your turn. No need to report this to the user."
        )


def _snake(name: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")
