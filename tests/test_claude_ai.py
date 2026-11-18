"""The claude.ai adapter, against a synthetic data export in the official format."""

import json
import zipfile
from pathlib import Path

import pytest
from conftest import validate

from harness import yaml_io
from harness.adapters.claude_ai import ClaudeAiAdapter
from harness.local import LocalHome
from harness.profiles import ProfileRegistry
from harness.repo import ContentRepo
from harness.sessions import SessionRecord
from harness.setup import Prompter, SetupOptions, SetupWizard

EMAIL = "me@example.com"


def make_export(folder: Path, name: str = "data-2026-11-18.zip", email: str = EMAIL,
                updated: str = "2026-11-02T09:30:00.123456Z") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    conversations = [{
        "uuid": "c-1", "name": "Budget 2027", "created_at": "2026-11-01T08:00:00.000000Z",
        "updated_at": updated,
        "chat_messages": [
            {"uuid": "m1", "sender": "human", "text": "Help with the budget",
             "attachments": [{"file_name": "notes.txt", "extracted_content": "Q1 numbers"}]},
            {"uuid": "m2", "sender": "assistant", "text": "Sure"}]}]
    projects = [
        {"uuid": "p-1", "name": "Client Decks", "description": "Hebrew client presentations",
         "prompt_template": "Always write in Hebrew.", "created_at": "2026-10-01T00:00:00Z",
         "docs": [{"filename": "style.md", "content": "Use the brand colours."}]},
        {"uuid": "p-0", "name": "How to use Claude", "is_starter_project": True, "docs": []}]
    path = folder / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("conversations.json", json.dumps(conversations))
        archive.writestr("projects.json", json.dumps(projects))
        archive.writestr("users.json", json.dumps([{"uuid": "u", "email_address": email}]))
        archive.writestr("memories.json", json.dumps([{"content": "Works at a consultancy."}]))
    return path


class Answers(Prompter):
    def __init__(self, *answers):
        self.answers = list(answers)

    def ask(self, question, default=None):
        return self.answers.pop(0) or default

    def confirm(self, question, default=True):
        return self.answers.pop(0)

    def say(self, text):
        pass


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    make_export(tmp_path / "Downloads")
    return tmp_path / "Downloads"


@pytest.fixture
def connected(repo: ContentRepo, downloads: Path, tmp_path: Path, monkeypatch) -> ClaudeAiAdapter:
    class FakeScheduler:
        def install(self, name, args, minutes):
            return f"scheduled {name}"

    monkeypatch.setattr("harness.scheduler.system_scheduler", FakeScheduler)
    repo.config_file.update({"claude_ai.watch_folder": str(downloads)})
    SetupWizard(Answers("personal", str(tmp_path / "files"), False), LocalHome()).run(
        SetupOptions(tool="claude-ai", repo=str(repo.root), environment="local"))
    return ClaudeAiAdapter(LocalHome())


def test_export_is_found_and_described(repo: ContentRepo, downloads: Path):
    LocalHome().save_settings(content_repo=str(repo.root))
    repo.config_file.update({"claude_ai.watch_folder": str(downloads)})
    accounts = ClaudeAiAdapter(LocalHome()).accounts()
    assert [a.key for a in accounts] == [EMAIL]
    assert "1 conversations, 1 projects" in accounts[0].summary   # starter project ignored


def test_setup_makes_a_cloud_profile_with_local_storage(connected: ClaudeAiAdapter, repo: ContentRepo,
                                                         tmp_path: Path):
    profile = ProfileRegistry(repo).get("claude-ai-personal-cloud")
    assert profile.environment == "cloud"
    storage = repo.config.storage_settings("transcripts", profile.id)
    assert storage == {"backend": "filesystem", "path": str(tmp_path / "files")}


def test_import_everything(connected: ClaudeAiAdapter, repo: ContentRepo, tmp_path: Path):
    report = connected.run_harvest()
    assert not report.errors, report.errors
    assert report.counts["conversations imported"] == 1
    project = repo.path("core", "projects", "client-decks")
    descriptor = yaml_io.load((project / "project.yaml").read_text())
    assert descriptor["instructions"] == "Always write in Hebrew."
    assert (project / "knowledge" / "style.md").read_text() == "Use the brand colours."
    assert not repo.path("core", "projects", "how-to-use-claude").exists()
    assert any("Works at a consultancy" in p.read_text() for p in repo.path("memory").glob("*.md"))

    session = SessionRecord(repo, "claude-ai-personal-cloud", "c-1")
    meta = session.meta()
    assert meta["topic"] == "Budget 2027" and meta["started_at"] == "2026-11-01T08:00:00Z"
    assert meta["last_activity_at"] == "2026-11-02T09:30:00Z"
    stored = tmp_path / "files" / "claude-ai-personal-cloud"
    assert json.loads((stored / "c-1" / "conversation.json").read_text())["name"] == "Budget 2027"
    assert (stored / "c-1" / "files" / "attachments" / "notes.txt").read_text() == "Q1 numbers"
    assert (stored / "exports" / "data-2026-11-18.zip").is_file()
    assert validate(repo).ok, validate(repo).problems

    assert not connected.run_harvest().counts  # same export again: nothing to do


def test_a_newer_export_updates_changed_conversations(connected: ClaudeAiAdapter, downloads: Path):
    connected.run_harvest()
    make_export(downloads, "data-2026-11-25.zip", updated="2026-11-20T10:00:00Z")
    assert connected.run_harvest().counts["conversations updated"] == 1


def test_export_of_an_unconnected_account_is_reported(connected: ClaudeAiAdapter, downloads: Path):
    make_export(downloads, "data-work.zip", email="work@example.com")
    report = connected.run_harvest()
    assert any("work@example.com is not connected" in e for e in report.errors)


def test_export_skill_is_built_from_settings(connected: ClaudeAiAdapter, repo: ContentRepo, tmp_path: Path,
                                             capsys):
    from harness.cli import main
    repo.config_file.update({"claude_ai.export_every_days": 14})
    target = tmp_path / "skill.zip"
    assert main(["skill", "claude-ai", "--output", str(target)]) == 0
    with zipfile.ZipFile(target) as archive:
        text = archive.read("harness-claude-ai-export/SKILL.md").decode()
    assert "every 14 days" in text and str(tmp_path / "Downloads") in text
    assert "3 hours later" in text and "${" not in text
    out = capsys.readouterr().out
    assert "in request mode" in out and "in download mode" in out


def test_accounts_can_be_named_before_the_first_export(repo: ContentRepo, tmp_path: Path, monkeypatch):
    class FakeScheduler:
        def install(self, name, args, minutes):
            return "scheduled"

    monkeypatch.setattr("harness.scheduler.system_scheduler", FakeScheduler)
    repo.config_file.update({"claude_ai.watch_folder": str(tmp_path / "empty")})
    answers = Answers("me@example.com, work@example.com", "personal", "work", str(tmp_path / "f"), False)
    SetupWizard(answers, LocalHome()).run(SetupOptions(tool="claude-ai", repo=str(repo.root),
                                                       environment="local"))
    adapter = ClaudeAiAdapter(LocalHome())
    assert adapter.bindings() == {"me@example.com": "claude-ai-personal-cloud",
                                  "work@example.com": "claude-ai-work-cloud"}
    make_export(tmp_path / "empty", email="work@example.com")
    assert adapter.run_harvest().counts["conversations imported"] == 1   # picked up by itself


def test_setup_prepares_the_skill_and_says_what_is_left(repo: ContentRepo, tmp_path: Path, monkeypatch):
    class FakeScheduler:
        def install(self, name, args, minutes):
            return "scheduled"

    monkeypatch.setattr("harness.scheduler.system_scheduler", FakeScheduler)
    repo.config_file.update({"claude_ai.watch_folder": str(tmp_path / "empty")})
    result = SetupWizard(Answers("me@example.com", "personal", str(tmp_path / "f"), False), LocalHome()).run(
        SetupOptions(tool="claude-ai", repo=str(repo.root), environment="local"))
    from harness.adapters.claude_ai import adapter as module
    assert (module._visible_folder() / "harness-claude-ai-export.zip").is_file()
    assert "Set up my harness export" in result.next_steps[-1]


def test_claude_ai_can_be_skipped_and_is_not_asked_again(repo: ContentRepo, tmp_path: Path):
    from harness.setup import SetupSkipped
    with pytest.raises(SetupSkipped):
        SetupWizard(Answers(""), LocalHome()).run(
            SetupOptions(tool="claude-ai", repo=str(repo.root), environment="local"))
