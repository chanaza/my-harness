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


def test_account_skill_is_built_from_settings(connected: ClaudeAiAdapter, repo: ContentRepo, tmp_path: Path,
                                              capsys):
    from harness.cli import main
    repo.config_file.update({"connector.save_every": "meaningful",
                             "claude_ai.skill_folder": str(tmp_path / "skills-out")})
    assert main(["skill", "claude-ai"]) == 0          # one file per connected account
    target = tmp_path / "skills-out" / "harness-account-me-example-com.zip"
    with zipfile.ZipFile(target) as archive:
        text = archive.read("harness-account/SKILL.md").decode()
    assert "profile: claude-ai-personal-cloud" in text and "${" not in text
    assert "a decision, a result, or a wrap-up" in text                     # connector.save_every
    for section in ("## Goal", "## Open thread", "## Connections in use"):   # the one summary language
        assert section in text
    assert "Set up harness-account" in capsys.readouterr().out


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
    assert "harness connector" in result.next_steps[0]
    target = result.next_steps[1].split(": upload ")[1].split(" on https")[0]
    assert Path(target).is_file() and target.endswith("harness-account-me-example-com.zip")
    assert "as me@example.com" in result.next_steps[1]
    assert "Set up harness-account" in result.next_steps[2]


def test_claude_ai_can_be_skipped_and_is_not_asked_again(repo: ContentRepo, tmp_path: Path):
    from harness.setup import SetupSkipped
    with pytest.raises(SetupSkipped):
        SetupWizard(Answers(""), LocalHome()).run(
            SetupOptions(tool="claude-ai", repo=str(repo.root), environment="local"))


def test_skill_name_avoids_reserved_words(connected: ClaudeAiAdapter):
    name, files = connected.skill_package()
    front = files[f"{name}/SKILL.md"].decode().split("---")[1]
    skill_name = next(line for line in front.splitlines() if line.startswith("name:")).split(":", 1)[1]
    assert "claude" not in skill_name.lower() and "anthropic" not in skill_name.lower()


def test_typed_accounts_are_named_by_their_e_mail_without_a_found_list(repo: ContentRepo, tmp_path: Path,
                                                                       monkeypatch):
    class FakeScheduler:
        def install(self, name, args, minutes):
            return "scheduled"

    class Recording(Answers):
        def __init__(self, *answers):
            super().__init__(*answers)
            self.questions, self.said = [], []

        def ask(self, question, default=None):
            self.questions.append(question)
            return super().ask(question, default)

        def say(self, text):
            self.said.append(text)

    monkeypatch.setattr("harness.scheduler.system_scheduler", FakeScheduler)
    repo.config_file.update({"claude_ai.watch_folder": str(tmp_path / "empty")})
    prompter = Recording("me@example.com, work@example.com", "personal", "work", str(tmp_path / "f"), False)
    SetupWizard(prompter, LocalHome()).run(SetupOptions(tool="claude-ai", repo=str(repo.root),
                                                        environment="local"))
    assert not any(s.startswith("Found") for s in prompter.said)
    assert any("Name for me@example.com" in q for q in prompter.questions)


def test_named_accounts_count_as_connected_before_any_export(repo: ContentRepo, tmp_path: Path, monkeypatch):
    class FakeScheduler:
        def install(self, name, args, minutes):
            return "scheduled"

    monkeypatch.setattr("harness.scheduler.system_scheduler", FakeScheduler)
    repo.config_file.update({"claude_ai.watch_folder": str(tmp_path / "empty")})
    adapter = ClaudeAiAdapter(LocalHome())
    assert not adapter.is_connected()
    SetupWizard(Answers("me@example.com", "personal", str(tmp_path / "f"), False), LocalHome()).run(
        SetupOptions(tool="claude-ai", repo=str(repo.root), environment="local"))
    assert ClaudeAiAdapter(LocalHome()).is_connected()   # the next installer run only updates


def test_steps_are_listed_for_every_account(repo: ContentRepo, tmp_path: Path, monkeypatch):
    class FakeScheduler:
        def install(self, name, args, minutes):
            return "scheduled"

    monkeypatch.setattr("harness.scheduler.system_scheduler", FakeScheduler)
    repo.config_file.update({"claude_ai.watch_folder": str(tmp_path / "empty")})
    answers = Answers("a@example.com, b@example.com", "personal", "work", str(tmp_path / "f"), False)
    options = SetupOptions(tool="claude-ai", repo=str(repo.root), environment="local")
    result = SetupWizard(answers, LocalHome()).run(options)
    uploads = [s for s in result.next_steps if ": upload " in s]
    assert len(uploads) == 2, result.next_steps
    steps = " ".join(result.next_steps)
    assert steps.count("Set up harness-account") == 2
    assert "a@example.com" in steps and "b@example.com" in steps


DESCRIBE = """schema: harness-describe/1
profile: claude-ai-personal-cloud
tool: claude-ai
captured_at: 2026-11-19T06:00:00Z
surface: cowork
user_profile: {text: "Consultant, writes in Hebrew."}
instructions:
  - {name: personal-preferences, text: "Answer in Hebrew."}
memory:
  - {text: "Works at a consultancy."}
skills:
  - {name: deck-review, description: Review client decks, origin: mine}
  - {name: pdf, description: PDFs, origin: anthropic}
connections:
  - {name: Gmail, kind: connector, purpose: e-mail}
projects:
  - {name: Client Decks, description: Decks, instructions: "Always Hebrew.", files: [style.md]}
workflows:
  - {name: Morning brief, schedule: every weekday 8:00, prompt: "Brief me."}
apps:
  - {name: Budget tracker, description: A page, link: https://claude.ai/artifact/x}
cannot_see: [agents, plugins]
"""

CONVERSATION = """---
schema: harness-conversation/1
profile: claude-ai-personal-cloud
tool: claude-ai
surface: claude-ai
title: Planning the harness
project: ""
saved_at: 2026-11-19T07:00:00Z
---
## Goal
Plan it.
## Decisions
Drive.
## Current state
Planned.
## Open thread
None
## Standing instructions
Always answer in Hebrew.
## Preferences learned
None
## Connections in use
- Google Drive: files
"""


def test_connector_inbox_is_saved_in_the_harness_form(connected: ClaudeAiAdapter, repo: ContentRepo):
    from harness.inbox import InboxProcessor
    inbox = repo.path("inbox", "connector")
    inbox.mkdir(parents=True)
    (inbox / "describe-20261119-0600.yaml").write_text(DESCRIBE, encoding="utf-8")
    (inbox / "conversation-20261119-0700-planning.md").write_text(CONVERSATION, encoding="utf-8")
    (inbox / "describe-20261119-0601.yaml").write_text("schema: harness-describe/1\nfree: text\n")
    (inbox / "describe-20261119-0602.yaml").write_text(DESCRIBE.replace("claude-ai-personal-cloud", "nobody"))
    report = InboxProcessor(repo).run()
    assert any("describe-20261119-0601.yaml: does not match the form" in e for e in report.errors)
    assert any("'nobody' is not registered" in e for e in report.errors)
    rejected = repo.path("inbox", "rejected")
    assert (rejected / "describe-20261119-0601.yaml.problem.txt").is_file()
    assert not any(inbox.iterdir())                                            # the inbox is emptied
    profile = "claude-ai-personal-cloud"
    assert repo.path("core", "skills", "deck-review", "SKILL.md").is_file()
    assert not repo.path("core", "skills", "pdf").exists()                    # not the user's
    assert repo.path("core", "projects", "client-decks").is_dir()
    assert "id: gmail" in repo.path("core", "connections.yaml").read_text()
    native = next(repo.path("native", profile).rglob("account.yaml"))
    assert "Budget tracker" in native.read_text()
    summary = repo.path("sessions", profile, "conversation-20261119-0700-planning", "summary.md")
    assert "Plan it." in summary.read_text()
    standing = repo.path("core", "instructions", profile, "standing-instructions.md").read_text()
    assert "Always answer in Hebrew." in standing                              # same digest as Claude Code
    (inbox / "describe-20261119-0700.yaml").write_text(DESCRIBE, encoding="utf-8")
    assert InboxProcessor(repo).run().counts["unchanged"] >= 1                 # its records are in the repo
