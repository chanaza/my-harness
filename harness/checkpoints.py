"""``CheckpointPolicy``: decides when the rolling session summary is due.

All thresholds come from the ``checkpoints`` section of harness.config.yaml.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import CheckpointSettings
from .digest import SummaryDigest
from .local import LocalHome
from .repo import ContentRepo
from .sessions import SessionRecord


@dataclass
class CheckpointProgress:
    """What happened in a session since its last checkpoint."""

    user_messages_since: int = 0
    percent_at_last: float = 0.0
    forced_done: bool = False


class CheckpointPolicy:
    def __init__(self, settings: CheckpointSettings) -> None:
        self.settings = settings

    def due(self, progress: CheckpointProgress, context_percent: float | None) -> str | None:
        """Return the reason a checkpoint is due now, or None."""
        s = self.settings
        if not s.enabled:
            return None
        if context_percent is not None:
            if s.force_at_context_percent and context_percent >= s.force_at_context_percent \
                    and not progress.forced_done:
                return f"context usage reached {context_percent:.0f}%"
            if s.every_context_percent and \
                    context_percent - progress.percent_at_last >= s.every_context_percent:
                return f"context usage grew to {context_percent:.0f}%"
        if s.every_user_messages and progress.user_messages_since >= s.every_user_messages:
            return f"{progress.user_messages_since} messages since the last checkpoint"
        return None

    def reset(self, progress: CheckpointProgress, context_percent: float | None) -> CheckpointProgress:
        """Progress right after a checkpoint was written."""
        percent = context_percent if context_percent is not None else progress.percent_at_last
        forced = progress.forced_done or bool(
            self.settings.force_at_context_percent and percent >= self.settings.force_at_context_percent
        )
        return CheckpointProgress(user_messages_since=0, percent_at_last=percent, forced_done=forced)


@dataclass(frozen=True)
class CheckpointResult:
    number: int
    digested: list[str] = field(default_factory=list)
    transcript: str | None = None


class CheckpointRecorder:
    """Keeps a session's checkpoint progress on this machine and writes checkpoints.

    Progress (messages since the last checkpoint, usage at that time) lives in
    local state, not in the content repository: it is bookkeeping, not content.
    """

    CURRENT_KEY = "current_session"

    def __init__(self, local: LocalHome, repo: ContentRepo, session: SessionRecord) -> None:
        self.local = local
        self.repo = repo
        self.session = session
        self.state = local.state("sessions", session.profile, session.id)

    @classmethod
    def current(cls, local: LocalHome, repo: ContentRepo, profile: str) -> CheckpointRecorder | None:
        """The recorder of the profile's most recently active session on this machine."""
        session_id = local.state("profiles", profile).get(cls.CURRENT_KEY)
        return cls(local, repo, SessionRecord(repo, profile, session_id)) if session_id else None

    def mark_current(self) -> None:
        marker = self.local.state("profiles", self.session.profile)
        if marker.get(self.CURRENT_KEY) != self.session.native_id:
            marker.set(self.CURRENT_KEY, self.session.native_id)
            marker.save()

    def progress(self) -> CheckpointProgress:
        return CheckpointProgress(**self.state.get("progress", {}))

    def count_user_message(self) -> None:
        progress = self.progress()
        progress.user_messages_since += 1
        self._save(progress)

    def record_turn(self, percent: float | None, transcript: Path | None) -> None:
        """Remember the latest usage and transcript location (used when a checkpoint is written)."""
        self.state.set("last_percent", percent)
        if transcript:
            self.state.set("transcript_path", str(transcript))
        self.state.save()

    def write(self, text: str, reason: str) -> CheckpointResult:
        """Store the summary as the next checkpoint, digest its sections, save the transcript,
        and reset progress."""
        progress = self.progress()
        percent = self.state.get("last_percent")
        number = self.session.write_summary(text, reason, percent, progress.user_messages_since)
        digest = SummaryDigest(self.repo, self.session).apply(text)
        transcript = None
        if self.repo.config.capture.transcript_on_checkpoint and self.state.get("transcript_path"):
            storage = self.repo.storage("transcripts", self.session.profile)
            transcript = self.session.save_transcript(storage, Path(self.state.get("transcript_path")))
        self._save(CheckpointPolicy(self.repo.config.checkpoints).reset(progress, percent))
        return CheckpointResult(number, digest.written, transcript)

    def _save(self, progress: CheckpointProgress) -> None:
        self.state.set("progress", asdict(progress))
        self.state.save()
