"""The Claude Code adapter, run against a simulated Claude Code installation."""

import json
from pathlib import Path

import pytest
from conftest import validate

from harness.adapters.claude_code import (
    HOOK_EVENTS,
    ClaudeCodeAdapter,
    ClaudeCodeHarvester,
    ClaudeCodeLocations,
    ContextMeter,
    TranscriptReader,
)
from harness.harvest import Kind
from harness.local import LocalHome
from harness.repo import ContentRepo

PROFILE = "claude-code-personal"


@pytest.fixture
def claude(tmp_path: Path) -> ClaudeCodeLocations:
    """A fake ~/.claude with one of everything."""
    home = tmp_path / "claude-home"
    (home / "skills" / "synced" / "bucket" / "deck-review" / "references").mkdir(parents=True)
    (home / "skills" / "synced" / "bucket" / "deck-review" / "SKILL.md").write_text(
        "---\nname: deck-review\ndescription: Review decks\nallowed-tools: Read\n---\n"
        "# Deck review\nSteps.\n")
    (home / "skills" / "synced" / "bucket" / "deck-review" / "references" / "style.md").write_text("Style")
    (home / "commands").mkdir()
    (home / "commands" / "standup.md").write_text("Write my standup.\n")
    (home / "agents").mkdir()
    (home / "agents" / "researcher.md").write_text(
        "---\nname: researcher\ndescription: Finds sources\ntools: Read, WebSearch\nmodel: opus\n---\n"
        "You research.\n")
    (home / "CLAUDE.md").write_text("Always answer in Hebrew.\n")
    (home / "projects" / "-home-me-app" / "memory").mkdir(parents=True)
    (home / "projects" / "-home-me-app" / "memory" / "MEMORY.md").write_text("Uses Postgres.\n")
    (home / "settings.json").write_text(json.dumps({"model": "opus", "env": {"TOKEN": "secret"}}))
    (home / "plugins" / "synced" / "bucket" / "my-plugin").mkdir(parents=True)
    (home / "plugins" / "synced" / "bucket" / "manifest.json").write_text("{}")
    user_config = tmp_path / ".claude.json"
    user_config.write_text(json.dumps({"mcpServers": {"monday": {
        "type": "http", "url": "https://mcp.monday.com/sse", "headers": {"Authorization": "Bearer x"}}}}))
    project = tmp_path / "app"
    (project / ".claude").mkdir(parents=True)
    (project / "CLAUDE.md").write_text("Project rules.\n")
    return ClaudeCodeLocations(home, user_config, project)


@pytest.fixture
def adapter(repo: ContentRepo, claude: ClaudeCodeLocations, tmp_path: Path) -> ClaudeCodeAdapter:
    local = LocalHome(tmp_path / "harness-home")
    adapter = ClaudeCodeAdapter(local, claude)
    adapter.install(PROFILE, "personal", repo.root)
    return adapter


def write_transcript(path: Path, prompts: int, tokens: int, compact: str | None = None) -> Path:
    lines = []
    for i in range(prompts):
        lines.append({"type": "user", "message": {"role": "user", "content": f"question {i}"}})
        lines.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "ignored"}]}})
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": f"answer {i}"}], "usage": {
            "input_tokens": 1, "cache_read_input_tokens": tokens - 1, "cache_creation_input_tokens": 0}}})
    if compact:
        lines.append({"type": "user", "isCompactSummary": True,
                      "message": {"role": "user", "content": compact}})
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def event(name: str, transcript: Path, project: Path, **extra) -> dict:
    return {"hook_event_name": name, "session_id": "sess-1", "transcript_path": str(transcript),
            "cwd": str(project), **extra}


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

def test_hook_flow_checkpoints_and_live_log(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    repo.config_file.update({"checkpoints.every_user_messages": 3,
                             "storage.live_logs.path": str(tmp_path / "live")})
    project = adapter.locations.project_dir
    transcript = write_transcript(tmp_path / "t.jsonl", 3, 20_000)

    adapter.handle_hook(event("SessionStart", transcript, project, source="startup"))
    session = repo.path("sessions", PROFILE, "sess-1")
    assert (session / "meta.yaml").is_file()

    for _ in range(2):
        adapter.handle_hook(event("UserPromptSubmit", transcript, project))
    assert adapter.handle_hook(event("Stop", transcript, project)) is None

    adapter.handle_hook(event("UserPromptSubmit", transcript, project))
    response = adapter.handle_hook(event("Stop", transcript, project))
    assert response["decision"] == "block"
    assert "harness session checkpoint" in response["reason"]
    assert adapter.handle_hook(event("Stop", transcript, project, stop_hook_active=True)) is None

    # Over the live-log threshold: the exchange is logged to external storage.
    write_transcript(transcript, 3, 170_000)
    adapter.handle_hook(event("Stop", transcript, project))
    assert "question 2" in (tmp_path / "live" / PROFILE / "sess-1" / "live-log.md").read_text()


def test_compaction_is_saved(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    transcript = write_transcript(tmp_path / "t.jsonl", 1, 10_000, compact="What we did so far")
    adapter.handle_hook(event("SessionStart", transcript, adapter.locations.project_dir, source="compact"))
    saved = repo.path("sessions", PROFILE, "sess-1", "compactions", "001.md")
    assert "What we did so far" in saved.read_text()
    assert validate(repo).ok, validate(repo).problems


def test_transcript_copied_on_pre_compact(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    transcript = write_transcript(tmp_path / "t.jsonl", 1, 10_000)
    adapter.handle_hook(event("PreCompact", transcript, adapter.locations.project_dir))
    copied = tmp_path / "transcripts" / PROFILE / "sess-1" / "transcript.jsonl"
    assert copied.read_text() == transcript.read_text()


def test_hook_survives_unusable_storage(adapter: ClaudeCodeAdapter, repo: ContentRepo, tmp_path: Path):
    repo.config_file.update({"storage.live_logs.path": "relative/not/allowed",
                             "checkpoints.force_at_context_percent": 80})
    transcript = write_transcript(tmp_path / "t.jsonl", 1, 170_000)
    response = adapter.handle_hook(event("Stop", transcript, adapter.locations.project_dir))
    assert response["decision"] == "block"  # the checkpoint still happens
    assert "live log failed" in (adapter.local.root / "logs" / "harness.log").read_text()
