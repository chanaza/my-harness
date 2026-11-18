"""The Claude Code adapter, run against a simulated Claude Code installation."""

import json
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
