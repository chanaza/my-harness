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
    repo.config_file.update({"connector.summary_every_replies": 7,
                             "claude_ai.skill_folder": str(tmp_path / "skills-out")})
    assert main(["skill", "claude-ai"]) == 0          # one file per connected account
    target = tmp_path / "skills-out" / "harness-account-me-example-com.zip"
    with zipfile.ZipFile(target) as archive:
        text = archive.read("harness-account/SKILL.md").decode()
    assert "profile: claude-ai-personal-cloud" in text and "${" not in text
    assert "harness_instructions" in text and "Not for Claude Code" in text   # thin: fetches the rest
    from harness.inbox import write_connector_instructions
    assert "connector/instructions/claude-ai.md" in write_connector_instructions(repo)
    full = repo.path("connector", "instructions", "claude-ai.md").read_text()
    assert "every 7 replies" in full and "exchange mode" in full            # connector settings
    for section in ("## Goal", "## Open thread", "## Connections in use"):   # the one summary language
        assert section in full
    assert "${PROFILE}" in full and "${AFTER_EVERY_REPLY}" not in full      # profile: by the connector
    assert write_connector_instructions(repo) == []                         # unchanged: not rewritten
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
  - {name: /areas/consultancy.md, text: "Works at a consultancy."}
skills:
  - name: deck-review
    description: Review client decks
    origin: mine
    files:
      - path: SKILL.md
        content: |
          ---
          name: deck-review
          description: Review client decks
          ---
          Check sources.
      - {path: references/style.md, content: "Hebrew, right to left."}
  - {name: drafts, description: Old drafts, origin: mine, not_readable: "files not visible"}
  - {name: pdf, description: PDFs, origin: anthropic}
plugins:
  - {name: cowork-plugin-management, description: Plugins, origin: anthropic}
connections:
  - {name: Gmail, kind: connector, purpose: e-mail}
projects:
  - name: Client Decks
    description: Decks
    instructions: "Always Hebrew."
    knowledge: [{path: style.md, content: "Use the brand colours."}]
  - {name: פרוסיד CTO, description: מצגת, instructions: "עברית."}
workflows:
  - {name: Morning brief, schedule: every weekday 8:00, prompt: "Brief me."}
  - {name: Harness - describe account, schedule: every day, prompt: "Run the harness-account skill."}
apps:
  - name: Budget tracker
    description: A page
    link: https://claude.ai/artifact/x
    files: [{path: index.html, content: "<h1>Budget</h1>"}]
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
    assert any("'nobody' is not registered" in e for e in report.errors), report.errors
    rejected = repo.path("inbox", "rejected")
    assert (rejected / "describe-20261119-0601.yaml.problem.txt").is_file()
    processor = InboxProcessor(repo)
    assert "describe-20261119-0601.yaml" in processor.retry_rejected()        # e.g. after an engine fix
    processor.run()                                                          # still wrong: back again
    assert not any(inbox.iterdir())                                            # the inbox is emptied
    profile = "claude-ai-personal-cloud"
    assert "Check sources." in repo.path("core", "skills", "deck-review", "SKILL.md").read_text()
    assert repo.path("core", "skills", "deck-review", "references", "style.md").is_file()   # every file
    assert not repo.path("core", "skills", "pdf").exists()                    # not the user's
    assert not repo.path("core", "skills", "drafts").exists()                 # no empty copies
    knowledge = repo.path("core", "projects", "client-decks", "knowledge", "style.md")
    assert "brand colours" in knowledge.read_text()
    assert repo.path("apps", "budget-tracker", "index.html").is_file()
    assert repo.path("core", "projects", "פרוסיד-cto", "project.yaml").is_file()   # Hebrew names kept
    assert repo.path("memory", f"{profile}-consultancy.md").is_file() or \
        any("consultancy" in p.name for p in repo.path("memory").iterdir())  # named by topic
    assert not any("describe-account" in p.name for p in repo.path("core", "workflows").iterdir())
    assert "id: gmail" in repo.path("core", "connections.yaml").read_text()
    native = next(repo.path("native", profile).rglob("account.yaml")).read_text()
    assert "drafts" in native and "not_saved" in native and "available_skills" in native
    summary = repo.path("sessions", profile, "conversation-20261119-0700-planning", "summary.md")
    assert "Plan it." in summary.read_text()
    standing = repo.path("core", "instructions", profile, "standing-instructions.md").read_text()
    assert "Always answer in Hebrew." in standing                              # same digest as Claude Code
    (inbox / "describe-20261119-0700.yaml").write_text(DESCRIBE, encoding="utf-8")
    assert InboxProcessor(repo).run().counts["unchanged"] >= 1                 # its records are in the repo
    head, tail = DESCRIBE.split("connections:", 1)
    (inbox / "describe-20261120-0600-1of2.yaml").write_text(head + "part: 1/2\n", encoding="utf-8")
    assert not InboxProcessor(repo).run().counts                               # waits for part 2
    (inbox / "describe-20261120-0600-2of2.yaml").write_text(
        "schema: harness-describe/1\nprofile: claude-ai-personal-cloud\ntool: claude-ai\n"
        "captured_at: 2026-11-20T06:00:00Z\npart: 2/2\nconnections:" + tail, encoding="utf-8")
    InboxProcessor(repo).run()
    assert not any(inbox.iterdir())                                            # both parts saved together
    native_before = next(repo.path("native", "claude-ai-personal-cloud").rglob("account.yaml")).read_text()
    (inbox / "describe-20261121-0900-project-briefs.yaml").write_text(
        "schema: harness-describe/1\nprofile: claude-ai-personal-cloud\ntool: claude-ai\n"
        "captured_at: 2026-11-21T09:00:00Z\npartial: true\nprojects:\n"
        "  - name: Briefs\n    instructions: Short.\n    knowledge: [{path: tone.md, content: Warm.}]\n")
    InboxProcessor(repo).run()
    assert repo.path("core", "projects", "briefs", "knowledge", "tone.md").read_text() == "Warm."
    native_after = next(repo.path("native", "claude-ai-personal-cloud").rglob("account.yaml")).read_text()
    assert native_after == native_before
    assert "id: gmail" in repo.path("core", "connections.yaml").read_text()   # a project run removes nothing
    from conftest import validate
    report = validate(repo)
    assert report.ok, report.problems                                          # the repository stays valid


def test_descriptions_saved_before_full_content_are_cleaned(repo: ContentRepo):
    import json

    from harness.migrations import DescribeBeforeFullContent
    profile = "claude-ai-personal-cloud"
    numbered = repo.path("memory", f"{profile}-memory-1.md")
    numbered.write_text("x")
    project = repo.path("core", "projects", "cto")
    project.mkdir(parents=True)
    bare = repo.path("inbox", "conflicts", profile, "core", "skills", "deck", "SKILL.md")
    bare.parent.mkdir(parents=True)
    bare.write_text("---\nname: deck\n---\n")
    state = repo.path("inbox", ".state", f"{profile}-describe.json")
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"written": {
        "memory:global:memory-1": f"memory/{profile}-memory-1.md",
        "project:global:פרוסיד CTO": "core/projects/cto"}}))
    changes = DescribeBeforeFullContent().apply(repo)
    assert not numbered.exists() and not project.exists() and not bare.parent.exists()
    assert not state.exists() and changes
    assert DescribeBeforeFullContent().apply(repo) == []                   # once


def exchange(number: int, text: str) -> str:
    return ("---\nschema: harness-exchange/1\nprofile: claude-ai-personal-cloud\ntool: claude-ai\n"
            f"conversation: conversation-20261119-0700-plan\nnumber: {number}\n"
            f"at: 2026-11-19T07:{number:02d}:00Z\ntitle: Plan\n---\n"
            f"## User\n\nq{number}\n\n## Assistant\n\n{text}\n")


def test_exchanges_make_a_word_for_word_log(connected: ClaudeAiAdapter, repo: ContentRepo):
    """To continue anywhere: the latest summary plus every exchange after it, in reply order."""
    from harness.inbox import InboxProcessor
    inbox = repo.path("inbox", "connector")
    inbox.mkdir(parents=True)
    for number, text in ((2, "second"), (1, "first"), (10, "tenth"), (2, "second again")):
        (inbox / f"exchange-20261119-0700-plan-{number}.md").write_text(exchange(number, text))
        report = InboxProcessor(repo).run()
        assert not report.errors, report.errors
    folder = repo.path("sessions", "claude-ai-personal-cloud", "conversation-20261119-0700-plan")
    log = (folder / "log.md").read_text()
    assert log.index("first") < log.index("second again") < log.index("tenth")   # reply order, late ones too
    assert "Replies 3-9 were not received." in log                          # a gap is never silent
    assert log.count("Reply 2 ") == 1                                       # sent twice: kept once
    from conftest import validate
    assert validate(repo).ok, validate(repo).problems


def test_apps_are_copied_by_version_and_whole(connected: ClaudeAiAdapter, repo: ContentRepo, tmp_path: Path):
    from harness.inbox import InboxProcessor, write_connector_instructions
    head = ("schema: harness-describe/1\nprofile: claude-ai-personal-cloud\ntool: claude-ai\n"
            "captured_at: 2026-11-19T06:00:00Z\npartial: true\napps:\n")
    page = "<!doctype html><html><body>Map</body></html>"
    first = tmp_path / "describe-20261119-0600-apps.yaml"
    first.write_text(head + f"  - {{name: Map, link: https://claude.ai/artifact/a, version: v1, "
                     f"files: [{{path: index.html, content: '{page}'}}]}}\n"
                     "  - {name: Cut, link: https://claude.ai/artifact/b, version: v1, "
                     "files: [{path: index.html, content: '<html><body>Cu'}]}\n")
    InboxProcessor(repo).add(first)                     # checked like a connector file
    InboxProcessor(repo).run()
    descriptor = repo.path("apps", "map", "app.yaml").read_text()
    assert "version: v1" in descriptor and repo.path("apps", "map", "index.html").read_text() == page
    assert not repo.path("apps", "cut").exists()       # an incomplete copy is never saved
    write_connector_instructions(repo)
    served = repo.path("connector", "instructions", "claude-ai.md").read_text()
    assert "https://claude.ai/artifact/a version v1" in served           # not copied again
    again = tmp_path / "describe-20261120-0600.yaml"
    again.write_text(head.replace("partial: true\n", "") +
                     "  - {name: Map, link: https://claude.ai/artifact/a, version: v1}\n")
    InboxProcessor(repo).add(again)
    InboxProcessor(repo).run()
    native = next(repo.path("native", "claude-ai-personal-cloud").rglob("account.yaml")).read_text()
    assert "Map" not in native                          # unchanged: not reported as missing
    bad = tmp_path / "describe-20261121-0600.yaml"
    bad.write_text("schema: harness-describe/1\n")
    with pytest.raises(ValueError):
        InboxProcessor(repo).add(bad)


def test_everything_in_the_harness_can_be_found(connected: ClaudeAiAdapter, repo: ContentRepo):
    """Every file of the repository is in the index (nothing can be missed), and a conversation
    is found by what a person remembers of it, not by its id."""
    import json

    from harness.inbox import InboxProcessor, write_connector_instructions
    inbox = repo.path("inbox", "connector")
    inbox.mkdir(parents=True)
    (inbox / "describe-20261119-0600.yaml").write_text(DESCRIBE, encoding="utf-8")
    (inbox / "conversation-20261119-0700-plan.md").write_text(
        CONVERSATION.replace("Planning the harness", "Plan"), encoding="utf-8")
    (inbox / "exchange-20261119-0700-plan-1.md").write_text(exchange(1, "first"), encoding="utf-8")
    InboxProcessor(repo).run()
    write_connector_instructions(repo)
    index = json.loads(repo.path("connector", "index.json").read_text())
    listed = {e["path"] for e in index}
    for path in repo.root.rglob("*"):
        rel = path.relative_to(repo.root).as_posix()
        if path.is_file() and not rel.startswith((".git", "inbox/.state", "connector/")) \
                and not any(rel.startswith(e["path"] + "/") for e in index if e["kind"] == "conversation"):
            assert rel in listed, f"{rel} cannot be found"
    kinds = {e["kind"] for e in index}
    assert {"skill", "memory", "instruction", "project", "app", "workflow", "connection", "profile",
            "conversation", "file"} <= kinds
    talk = next(e for e in index if e["kind"] == "conversation" and e["name"] == "Plan")
    assert talk["date"] == "2026-11-19" and talk["tool"] == "claude-ai" and talk["account"] == "personal"
    assert "Plan it." in talk["description"] and talk["first_message"] == "q1"
    assert talk["log"].endswith("log.md") and talk["summary"].endswith("summary.md")
    assert any(e["kind"] == "connection" and e["name"] == "gmail" for e in index)
    assert any(e["kind"] == "file" and e["name"] == "style.md" for e in index)   # a single file


def test_genspark_saves_through_the_same_engine(repo: ContentRepo, tmp_path: Path):
    """A tool with no export or API: one adapter with only its own notes; the saving and
    reading instructions are the engine's, the same as for the Claude account."""
    from harness.inbox import InboxProcessor, write_connector_instructions
    result = SetupWizard(Answers("me@example.com", "work", str(tmp_path / "f")), LocalHome()).run(
        SetupOptions(tool="genspark", repo=str(repo.root), environment="local"))
    assert result.profiles == ["genspark-work-cloud"]
    skill_file = Path(result.next_steps[-1].split("Upload: ")[1])
    with zipfile.ZipFile(skill_file) as archive:
        skill = archive.read("harness-account/SKILL.md").decode()
    assert "`tool: genspark` and `profile: genspark-work-cloud`" in skill   # the same thin skill
    assert "Once per conversation" in skill and "Claude Code" not in skill
    write_connector_instructions(repo)
    served = repo.path("connector", "instructions", "genspark.md").read_text()
    claude = repo.path("connector", "instructions", "claude-ai.md").read_text()
    for shared in ("## Exchange mode", "## Save mode", "## Describe mode", "harness_find", "## Goal"):
        assert shared in served and shared in claude                      # one engine, every tool
    assert "Hub" in served and "Cowork" not in served and "Cowork" in claude
    inbox = repo.path("inbox", "connector")
    inbox.mkdir(parents=True)
    (inbox / "exchange-20261119-0900-ideas-1.md").write_text(
        exchange(1, "an idea").replace("claude-ai-personal-cloud", "genspark-work-cloud")
        .replace("tool: claude-ai", "tool: genspark").replace("conversation-20261119-0700-plan",
                                                               "conversation-20261119-0900-ideas"))
    InboxProcessor(repo).run()
    log = repo.path("sessions", "genspark-work-cloud", "conversation-20261119-0900-ideas", "log.md")
    assert "an idea" in log.read_text()
