"""The Claude Code adapter, run against a simulated Claude Code installation."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from conftest import CC_PROFILE as PROFILE
from conftest import event, validate, write_transcript

from harness.adapters.claude_code import (
    HOOK_EVENTS,
    ClaudeCodeAdapter,
    ClaudeCodeHarvester,
    ClaudeCodeLocations,
    ContextMeter,
    TranscriptReader,
)
from harness.harvest import Kind
from harness.repo import ContentRepo
from harness.sessions import SessionRecord

# --- transcript ------------------------------------------------------------------------

def test_transcript_reader(tmp_path: Path):
    reader = TranscriptReader(write_transcript(tmp_path / "t.jsonl", 3, 50_000, compact="Summary!"))
    assert reader.context_tokens() == 50_000
    assert reader.last_exchange().prompt == "question 2"
    assert reader.last_exchange().answer == "answer 2"
    assert reader.latest_compact_summary() == "Summary!"


def test_context_meter_detects_larger_window():
    meter = ContextMeter(200_000)
    assert meter.percent(100_000) == 50.0
    assert meter.percent(250_000) == 25.0  # more tokens than 200k => 1M window


# --- harvester ---------------------------------------------------------------------------

def test_harvester_finds_everything_and_strips_secrets(claude: ClaudeCodeLocations):
    collected = ClaudeCodeHarvester(claude).collect()
    items = {(i.kind, i.name): i for i in collected}
    assert (Kind.SKILL, "deck-review") in items
    assert "references/style.md" in items[(Kind.SKILL, "deck-review")].files
    assert (Kind.SKILL, "standup") in items
    assert (Kind.AGENT, "researcher") in items
    assert (Kind.MEMORY, "MEMORY") in items
    assert {i.scope for i in collected if i.kind is Kind.INSTRUCTION} == {"global", "project:app"}
    monday = items[(Kind.CONNECTION, "monday")]
    assert monday.meta["notes"] == "http; host mcp.monday.com"
    assert "Bearer" not in json.dumps(monday.meta)
    assert (Kind.CONNECTION, "my-plugin") in items
    assert (Kind.CONNECTION, ".staging") not in items and (Kind.CONNECTION, "data") not in items
    assert b"secret" not in items[(Kind.NATIVE, "settings")].files["settings.json"]


def test_harvester_exclusions(claude: ClaudeCodeLocations):
    items = ClaudeCodeHarvester(claude, exclude=["skill:*", "connection:monday"]).collect()
    assert not any(i.kind is Kind.SKILL for i in items)
    assert not any(i.name == "monday" for i in items)


# --- install + harvest into the repo ---------------------------------------------------------

def test_install_writes_hooks_skill_and_profile(adapter: ClaudeCodeAdapter, repo: ContentRepo):
    settings = json.loads(adapter.locations.settings_file.read_text())
    assert set(HOOK_EVENTS) <= set(settings["hooks"])
    assert settings["model"] == "opus"  # existing settings kept
    assert (adapter.locations.config_dir / "skills" / "harness-save" / "SKILL.md").is_file()
    assert PROFILE in repo.path("core", "profiles.yaml").read_text()
    adapter.install(PROFILE, "personal")  # idempotent
    settings = json.loads(adapter.locations.settings_file.read_text())
    assert all(len(settings["hooks"][e]) == 1 for e in HOOK_EVENTS)


def test_run_harvest_writes_valid_content(adapter: ClaudeCodeAdapter, repo: ContentRepo):
    report = adapter.run_harvest("sess-1")
    assert not report.errors, report.errors
    assert repo.path("core", "skills", "deck-review", "SKILL.md").is_file()
    assert repo.path("core", "skills", "deck-review", "references", "style.md").is_file()
    assert repo.path("core", "agents", "researcher.yaml").is_file()
    assert repo.path("core", "instructions", PROFILE, "global-claude-md.md").is_file()
    assert "monday" in repo.path("core", "connections.yaml").read_text()
    assert repo.path("native", PROFILE, "global", "settings.json").is_file()
    assert validate(repo).ok, validate(repo).problems

    again = adapter.run_harvest("sess-1")
    assert not again.changed  # nothing changed, nothing rewritten


def test_harvest_conflict_with_other_profile(adapter: ClaudeCodeAdapter, repo: ContentRepo):
    adapter.run_harvest()
    skill = repo.path("core", "skills", "deck-review", "SKILL.md")
    skill.write_text(skill.read_text().replace("profile: claude-code-personal", "profile: chatgpt-work"))
    (adapter.locations.config_dir / "skills" / "synced" / "bucket" / "deck-review" / "SKILL.md").write_text(
        "---\nname: deck-review\ndescription: Review decks v2\n---\nNew steps.\n")
    report = adapter.run_harvest()
    assert report.counts["conflict"] == 1
    assert "chatgpt-work" in skill.read_text()  # the other profile's version was not overwritten
    assert "New steps" in report.conflicts[0].read_text()


# --- hooks --------------------------------------------------------------------------------

def context_of(response: dict | None) -> str:
    return ((response or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")


def test_hook_flow(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    """Every turn: transcript saved and committed in the background; a due checkpoint is
    requested quietly with the next prompt, never shown at the end of a turn."""
    subprocess.run(["git", "init", "-q"], cwd=repo.root, check=True)
    repo.config_file.update({"checkpoints.every_user_messages": 3})
    project = adapter.locations.project_dir
    transcript = write_transcript(tmp_path / "t.jsonl", 3, 20_000)

    assert adapter.handle_hook(event("SessionStart", transcript, project, source="startup")) is None
    assert repo.path("sessions", PROFILE, "sess-1", "meta.yaml").is_file()

    for _ in range(3):
        assert context_of(adapter.handle_hook(event("UserPromptSubmit", transcript, project))) == ""
    assert adapter.handle_hook(event("Stop", transcript, project)) is None  # nothing shown
    saved = tmp_path / "transcripts" / PROFILE / "sess-1" / "transcript.jsonl"
    assert saved.read_text() == transcript.read_text()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo.root, capture_output=True, text=True)
    assert status.stdout == ""  # every turn is committed

    request = context_of(adapter.handle_hook(event("UserPromptSubmit", transcript, project)))
    assert "harness session checkpoint --quiet" in request and "silently" in request


def test_checkpoint_clears_the_pending_request(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    from harness.checkpoints import CheckpointRecorder
    repo.config_file.update({"checkpoints.every_user_messages": 1})
    project = adapter.locations.project_dir
    transcript = write_transcript(tmp_path / "t.jsonl", 1, 1000)
    adapter.handle_hook(event("UserPromptSubmit", transcript, project))
    adapter.handle_hook(event("Stop", transcript, project))
    assert context_of(adapter.handle_hook(event("UserPromptSubmit", transcript, project)))
    session = SessionRecord(repo, PROFILE, "sess-1")
    CheckpointRecorder(adapter.local, repo, session).write("## Goal\nX\n", "test")
    adapter.handle_hook(event("Stop", transcript, project))
    assert context_of(adapter.handle_hook(event("UserPromptSubmit", transcript, project))) == ""


def test_forced_checkpoint_blocks_once(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    """Near the end of the context there may be no next prompt: the model is asked at Stop, once."""
    project = adapter.locations.project_dir
    transcript = write_transcript(tmp_path / "t.jsonl", 1, 170_000)
    first = adapter.handle_hook(event("Stop", transcript, project))
    assert first["decision"] == "block" and "reached" in first["reason"]
    assert adapter.handle_hook(event("Stop", transcript, project)) is None
    assert context_of(adapter.handle_hook(event("UserPromptSubmit", transcript, project)))


def test_compaction_requests_a_checkpoint(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    transcript = write_transcript(tmp_path / "t.jsonl", 1, 10_000, compact="What we did so far")
    project = adapter.locations.project_dir
    adapter.handle_hook(event("SessionStart", transcript, project, source="compact"))
    adapter.handle_hook(event("Stop", transcript, project))
    assert "compacted" in context_of(adapter.handle_hook(event("UserPromptSubmit", transcript, project)))


def test_transcript_saved_on_pre_compact(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    transcript = write_transcript(tmp_path / "t.jsonl", 1, 10_000)
    adapter.handle_hook(event("PreCompact", transcript, adapter.locations.project_dir))
    copied = tmp_path / "transcripts" / PROFILE / "sess-1" / "transcript.jsonl"
    assert copied.read_text() == transcript.read_text()


def test_hook_survives_unusable_storage(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    repo.config_file.update({"storage.transcripts.path": "relative/not/allowed"})
    transcript = write_transcript(tmp_path / "t.jsonl", 1, 170_000)
    response = adapter.handle_hook(event("Stop", transcript, adapter.locations.project_dir))
    assert response["decision"] == "block"  # the forced checkpoint still happens
    assert "transcript failed" in (adapter.local.root / "logs" / "harness.log").read_text()


def test_background_lock_skips_overlapping_work(tmp_path: Path):
    from harness.background import ProcessLock
    with ProcessLock(tmp_path / "x.lock") as first:
        with ProcessLock(tmp_path / "x.lock", wait=0.3) as second:
            assert first.acquired and not second.acquired
    with ProcessLock(tmp_path / "x.lock") as again:
        assert again.acquired


def test_engine_artifacts_are_not_harvested(adapter: ClaudeCodeAdapter, repo: ContentRepo):
    items = adapter.harvest()
    assert not any(i.name == "harness-save" for i in items)
    settings = next(i for i in items if i.kind is Kind.NATIVE and i.name == "settings")
    assert b"harness hook" not in settings.files["settings.json"]


def test_prune_removes_newly_excluded(adapter: ClaudeCodeAdapter, repo: ContentRepo):
    adapter.run_harvest()
    skill = repo.path("core", "skills", "deck-review")
    assert skill.is_dir()
    repo.config_file.update({"harvest.exclude": ["skill:deck-review"]})
    assert adapter.prune_harvest() == ["core/skills/deck-review"]
    assert not skill.exists()
    assert repo.path("core", "agents", "researcher.yaml").is_file()  # untouched


def test_prune_works_for_items_harvested_before_paths_were_recorded(adapter, repo):
    adapter.run_harvest()
    state = adapter.local.state("harvest", PROFILE)
    state.set("written", {})
    state.save()
    repo.config_file.update({"harvest.exclude": ["skill:deck-review"]})
    assert adapter.prune_harvest() == ["core/skills/deck-review"]


def test_native_mirror_follows_the_tool(adapter: ClaudeCodeAdapter, repo: ContentRepo):
    adapter.run_harvest()
    mirrored = repo.path("native", PROFILE, "global", "settings.json")
    assert mirrored.is_file()
    adapter.locations.settings_file.write_text(json.dumps({"hooks": {}}))  # nothing of the user's left
    report = adapter.run_harvest()
    assert report.counts["removed"] == 1 and not mirrored.exists()
    assert repo.path("core", "skills", "deck-review").is_dir()  # knowledge is never mirrored away


def add_old_session(adapter: ClaudeCodeAdapter, session: str, cwd: str, stamp: str) -> Path:
    folder = adapter.locations.config_dir / "projects" / "-old-project"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session}.jsonl"
    lines = [{"type": "user", "timestamp": f"{stamp}T09:00:00.120Z", "cwd": cwd,
              "message": {"role": "user", "content": "old question"}},
             {"type": "assistant", "timestamp": f"{stamp}T09:01:00.000Z",
              "message": {"role": "assistant", "content": [{"type": "text", "text": "old answer"}]}}]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def test_backfill_imports_past_sessions(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    add_old_session(adapter, "old-1", r"C:\Users\me\projects\deck-tool", "2026-09-01")
    add_old_session(adapter, "old-2", "/home/me/api", "2026-11-17")

    assert [e.action for e in adapter.backfill(dry_run=True)] == ["found", "found"]
    assert not repo.path("sessions", PROFILE).exists()

    entries = {e.session: e for e in adapter.backfill()}
    assert entries["old-1"].action == "imported" and entries["old-1"].project == "deck-tool"
    meta = SessionRecord(repo, PROFILE, "old-1").meta()
    assert meta["started_at"] == "2026-09-01T09:00:00Z"
    assert meta["last_activity_at"] == "2026-09-01T09:01:00Z"  # real dates, not import time
    assert "imported_at" in meta
    assert (tmp_path / "transcripts" / PROFILE / "old-1" / "transcript.jsonl").is_file()
    assert validate(repo).ok, validate(repo).problems

    assert {e.action for e in adapter.backfill()} == {"unchanged"}  # idempotent


def test_backfill_since_days(adapter: ClaudeCodeAdapter):
    add_old_session(adapter, "ancient", "/x", "2020-01-01")
    add_old_session(adapter, "recent", "/x", datetime.now(UTC).strftime("%Y-%m-%d"))
    assert [e.session for e in adapter.backfill(since_days=7, dry_run=True)] == ["recent"]


def test_stop_pushes_every_turn(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    for args in (["init", "-q", "-b", "main"], ["remote", "add", "origin", str(remote)],
                 ["-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x"],
                 ["push", "-q", "-u", "origin", "main"]):
        subprocess.run(["git", *args], cwd=repo.root, check=True)
    transcript = write_transcript(tmp_path / "t.jsonl", 1, 1000)
    adapter.handle_hook(event("Stop", transcript, adapter.locations.project_dir))
    local = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo.root, capture_output=True, text=True)
    pushed = subprocess.run(["git", "rev-parse", "main"], cwd=remote, capture_output=True, text=True)
    assert local.stdout == pushed.stdout
    status = subprocess.run(["git", "status", "-sb"], cwd=repo.root, capture_output=True, text=True)
    assert "...origin/main" in status.stdout and "ahead" not in status.stdout


def test_connections_mirror_the_tool_per_profile(adapter: ClaudeCodeAdapter, repo: ContentRepo):
    from harness import yaml_io
    adapter.run_harvest()
    connections = yaml_io.load(repo.path("core", "connections.yaml").read_text())["connections"]
    monday = next(c for c in connections if c["id"] == "monday")
    assert monday["available_in"]["claude-code"]["profiles"] == [PROFILE]

    adapter.locations.user_config_file.write_text("{}")  # the MCP server was removed in the tool
    report = adapter.run_harvest()
    assert report.counts["removed"] == 1
    ids = [c["id"] for c in yaml_io.load(repo.path("core", "connections.yaml").read_text())["connections"]]
    assert "monday" not in ids and "my-plugin" in ids
    assert validate(repo).ok, validate(repo).problems


def test_sync_rebases_onto_another_machines_push(tmp_path: Path):
    from harness.config import GitSettings
    from harness.git_sync import GitSync

    def git(cwd, *args):
        subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a", *args], cwd=cwd,
                       check=True, capture_output=True)

    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    machines = []
    for name in ("cloud", "windows"):
        clone = tmp_path / name
        git(tmp_path, "clone", "-q", str(remote), str(clone))
        machines.append(clone)
    cloud, windows = machines
    (cloud / "a.txt").write_text("a")
    for args in (("add", "-A"), ("commit", "-q", "-m", "a"), ("push", "-q", "-u", "origin", "HEAD")):
        git(cloud, *args)
    (windows / "b.txt").write_text("b")  # windows has not seen cloud's commit
    settings = GitSettings(auto_commit=True, auto_push=True)
    result = GitSync(windows, settings).sync("b", push=True)
    assert result.pushed, result.message
    files = subprocess.run(["git", "ls-tree", "--name-only", "main"], cwd=remote,
                           capture_output=True, text=True)
    assert files.stdout.split() == ["a.txt", "b.txt"]
