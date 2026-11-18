import json
from pathlib import Path

import pytest

from harness.adapters.claude_code import ClaudeCodeAdapter, ClaudeCodeLocations
from harness.local import LocalHome
from harness.profiles import ProfileRegistry
from harness.repo import ContentRepo
from harness.scaffold import InitOptions, Scaffolder
from harness.validation import Report, RepoValidator

PROFILE = "chatgpt-work"
PROVENANCE = {"source": {"profile": PROFILE, "session": "20261118-1430-chatgpt-x",
                         "at": "2026-11-18T14:30:00Z"}}
WINDOWS_PATH = r"C:\Users\someone\OneDrive - example.com\Documents\Sessions\transcripts"


def validate(repo: ContentRepo) -> Report:
    return RepoValidator.default(repo.layout).validate(repo)


@pytest.fixture(autouse=True)
def isolated_harness_home(tmp_path_factory, monkeypatch) -> None:
    """Tests never touch the real ~/.my-harness, desktop or browser of the machine.
    (Kept outside tmp_path, which some tests need empty.)"""
    isolated = tmp_path_factory.mktemp("isolated")
    monkeypatch.setenv("HARNESS_HOME", str(isolated / "harness-home"))
    desktop = isolated / "desktop"
    desktop.mkdir()
    monkeypatch.setattr("harness.adapters.claude_ai.adapter._visible_folder", lambda: desktop)
    monkeypatch.setattr("webbrowser.open", lambda url: True)


@pytest.fixture
def repo(tmp_path: Path) -> ContentRepo:
    options = InitOptions(owner="Test", storage_paths={"transcripts": str(tmp_path / "transcripts")})
    repo = Scaffolder().create(tmp_path / "content", options)
    ProfileRegistry(repo).add("chatgpt", "work")
    return repo


# --- Claude Code: a simulated installation ------------------------------------------

CC_PROFILE = "claude-code-personal"


@pytest.fixture
def claude(tmp_path: Path) -> ClaudeCodeLocations:
    """A fake ~/.claude with one of everything."""
    home = tmp_path / "claude-home"
    (home / "skills" / "synced" / "bucket" / "deck-review" / "references").mkdir(parents=True)
    (home / "skills" / "synced" / "bucket" / "deck-review" / "SKILL.md").write_text(
        "---\nname: deck-review\ndescription: Review decks\nallowed-tools: Read\n---\n"
        "# Deck review\nSteps.\n")
    (home / "skills" / "synced" / "bucket" / "deck-review" / "references" / "style.md").write_text("Style")
    (home / "skills" / ".trash" / "123-x" / "old-skill").mkdir(parents=True)  # deleted skill
    (home / "skills" / ".trash" / "123-x" / "old-skill" / "SKILL.md").write_text(
        "---\nname: old-skill\ndescription: deleted\n---\nGone.\n")
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
    (home / "plugins" / "synced" / "bucket" / "my-plugin" / "skills" / "report").mkdir(parents=True)
    (home / "plugins" / "synced" / "bucket" / "my-plugin" / "skills" / "report" / "SKILL.md").write_text(
        "---\nname: report\ndescription: Weekly report\n---\nSteps.\n")
    (home / "plugins" / "synced" / "bucket" / ".staging").mkdir()  # internal folders, not plugins
    (home / "plugins" / "synced" / "bucket" / "data").mkdir()
    (home / "plugins" / "synced" / "bucket" / "manifest.json").write_text(
        json.dumps({"plugins": [{"name": "my-plugin", "pluginId": "p1",
                                 "description": "Does useful things"}]}))
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
    adapter.install(CC_PROFILE, "personal", repo.root)
    adapter.defer = lambda e: adapter.handle_hook(e, deferred=True)  # background work inline
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
