"""The Cowork adapter, against a simulated Claude desktop app data folder."""

import json
from pathlib import Path

import pytest
from conftest import validate

from harness.adapters.cowork import CoworkAdapter, CoworkLocations
from harness.local import LocalHome
from harness.profiles import ProfileRegistry
from harness.repo import ContentRepo
from harness.sessions import SessionRecord
from harness.setup import Prompter, SetupOptions, SetupWizard

PERSONAL = ("aaaa1111-personal", "bbbb2222-org")
WORK = ("cccc3333-work", "dddd4444-org")


def transcript(path: Path, prompt: str, day: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "timestamp": f"{day}T10:00:00.000Z",
              "message": {"role": "user", "content": prompt}},
             {"type": "assistant", "timestamp": f"{day}T10:05:00.000Z",
              "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}}]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")


def skill(folder: Path, name: str) -> None:
    (folder / name).mkdir(parents=True)
    (folder / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name}\n---\nSteps.\n")


@pytest.fixture
def app(tmp_path: Path) -> CoworkLocations:
    """Two accounts laid out like the Claude desktop app keeps them."""
    sessions = tmp_path / "Claude" / "local-agent-mode-sessions"
    personal = sessions / PERSONAL[0] / PERSONAL[1]
    agent = personal / "agent" / "local_ditto_x"
    (agent).mkdir(parents=True)
    (agent / "audit.jsonl").write_text('{"action": "x"}\n')
    transcript(agent / ".claude" / "projects" / "p" / "a1.jsonl", "agent question", "2026-10-01")
    (personal / "agent" / "memory").mkdir()
    (personal / "agent" / "memory" / "clients.md").write_text("Client A prefers mornings.\n")
    plugin = personal / "rpm" / "plugin_123"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "my-tools", "description": "Mine"}))
    skill(plugin / "skills", "weekly-report")

    work = sessions / WORK[0] / WORK[1]
    conversation = work / "0074eb19"
    transcript(conversation / ".claude" / "projects" / "p" / "c1.jsonl", "build the deck", "2026-11-10")
    (conversation / "audit.jsonl").write_text('{"action": "y"}\n')
    (conversation / "uploads").mkdir()
    (conversation / "uploads" / "brief.pdf").write_bytes(b"%PDF-1.4 brief")
    (conversation / "outputs").mkdir()
    (conversation / "outputs" / "deck.pptx").write_bytes(b"PK\x03\x04 deck")
    (conversation / "host-cwd").mkdir()
    (conversation / "host-cwd" / "private.txt").write_text("not Cowork content")

    (work / "scheduled-tasks.json").write_text(json.dumps({"scheduledTasks": [
        {"id": "t1", "name": "Weekly export", "prompt": "Export my claude.ai data", "schedule": "weekly"}],
        "recordedSkips": []}))
    code = tmp_path / "Claude" / "claude-code-sessions" / WORK[0] / WORK[1]
    code.mkdir(parents=True)
    (code / "scheduled-tasks.json").write_text(json.dumps({"scheduledTasks": [], "recordedSkips": []}))
    skill(sessions / "skills-plugin" / PERSONAL[1] / PERSONAL[0] / "skills", "chana-deck-review")
    skill(sessions / "skills-plugin" / WORK[1] / WORK[0] / "skills", "pdf")
    return CoworkLocations(tmp_path / "Claude")


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
def connected(app: CoworkLocations, repo: ContentRepo, tmp_path: Path, monkeypatch) -> CoworkAdapter:
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    LocalHome().save_settings(machine="local")
    monkeypatch.setenv("CLAUDE_APP_DATA_DIR", str(app.root))
    scheduled = []

    class FakeScheduler:
        def install(self, name, args, minutes):
            scheduled.append((name, args, minutes))
            return f"scheduled {name}"

    monkeypatch.setattr("harness.scheduler.system_scheduler", FakeScheduler)
    repo.config_file.update({"harvest.exclude": ["skill:pdf"]})
    SetupWizard(Answers("personal", "work", str(tmp_path / "files"), False), LocalHome()).run(
        SetupOptions(tool="cowork", repo=str(repo.root), environment="local"))
    adapter = CoworkAdapter(LocalHome(), app)
    adapter.scheduled = scheduled
    return adapter


def test_accounts_are_discovered(app: CoworkLocations):
    accounts = CoworkAdapter(LocalHome(), app).accounts()
    assert len(accounts) == 2
    assert "1 conversations" in accounts[0].summary and "chana-deck-review" in accounts[0].summary


def test_setup_names_each_account_and_schedules_capture(connected: CoworkAdapter, repo: ContentRepo):
    profiles = {p.id: p for p in ProfileRegistry(repo).all()}
    assert {"cowork-personal-local", "cowork-work-local"} <= set(profiles)
    assert profiles["cowork-work-local"].environment == "local"
    assert connected.scheduled == [("capture-cowork", ["harvest", "cowork"], 30)]


def test_capture_everything(connected: CoworkAdapter, repo: ContentRepo, tmp_path: Path):
    report = connected.run_harvest()
    assert not report.errors, report.errors
    assert report.counts["conversations imported"] == 2
    assert repo.path("core", "skills", "chana-deck-review", "SKILL.md").is_file()
    assert not repo.path("core", "skills", "pdf").exists()                      # excluded
    assert repo.path("core", "plugins", "my-tools", "skills", "weekly-report", "SKILL.md").is_file()
    assert any(p.name.endswith("clients.md") for p in repo.path("memory").iterdir())

    work = SessionRecord(repo, "cowork-work-local", "0074eb19")
    meta = work.meta()
    assert meta["started_at"] == "2026-11-10T10:00:00Z"
    assert {f["path"] for f in meta["files"]} == {"uploads/brief.pdf", "outputs/deck.pptx"}
    stored = tmp_path / "files" / "cowork-work-local" / "0074eb19"
    assert (stored / "files" / "outputs" / "deck.pptx").read_bytes() == b"PK\x03\x04 deck"
    assert (stored / "audit.jsonl").is_file() and (stored / "transcript.jsonl").is_file()
    assert not list(stored.rglob("private.txt"))                                 # host folder not copied
    assert SessionRecord(repo, "cowork-personal-local", "agent-local_ditto_x").meta()
    assert validate(repo).ok, validate(repo).problems

    assert connected.run_harvest().counts["conversations imported"] == 0          # nothing changed


def test_changed_conversation_is_updated(connected: CoworkAdapter, app: CoworkLocations):
    connected.run_harvest()
    conversation = app.sessions_root / WORK[0] / WORK[1] / "0074eb19"
    (conversation / "outputs" / "summary.docx").write_bytes(b"new")
    assert connected.run_harvest().counts["conversations updated"] == 1


def test_same_skill_from_two_profiles_is_not_a_conflict(connected: CoworkAdapter, repo: ContentRepo):
    from harness.harvest import Captured, HarvestSync, Kind
    from harness.provenance import Origin
    connected.run_harvest()
    ProfileRegistry(repo).add("claude-code", "personal", environment="cloud")
    main = repo.path("core", "skills", "chana-deck-review", "SKILL.md")
    body = main.read_text().split("---", 2)[2]
    item = Captured(Kind.SKILL, "chana-deck-review", "cloud",
                    {"SKILL.md": f"---\nname: chana-deck-review\ndescription: x\n---{body}".encode()})
    report = HarvestSync(repo, LocalHome().state("harvest", "cloud")).run(
        [item], Origin.now("claude-code-personal-cloud"))
    assert report.counts["conflict"] == 0 and report.counts["updated"] == 1


def test_setup_without_a_tool_connects_every_tool_found(app, claude, repo, tmp_path, monkeypatch):
    from harness.cli import main
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home2"))
    LocalHome().save_settings(machine="local")
    monkeypatch.setenv("CLAUDE_APP_DATA_DIR", str(app.root))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude.config_dir))

    class FakeScheduler:
        def install(self, name, args, minutes):
            return "scheduled"

    monkeypatch.setattr("harness.scheduler.system_scheduler", FakeScheduler)
    args = ["setup", "--repo", str(repo.root), "--environment", "local", "--transcripts", str(tmp_path / "f"),
            "--account", "aaaa1111=personal,cccc3333=work", "--yes", "--no-capture"]
    assert main(args) == 0
    ids = ProfileRegistry(repo).ids()
    assert {"cowork-personal-local", "cowork-work-local"} <= ids
    assert "claude-code-personal-local" in ids  # one account: the default name, not the list


def test_scheduled_tasks_become_workflows(connected: CoworkAdapter, repo: ContentRepo):
    from harness import yaml_io
    connected.run_harvest()
    workflow = yaml_io.load(repo.path("core", "workflows", "weekly-export.yaml").read_text())
    assert workflow["trigger"] == "weekly"
    assert workflow["steps"][0]["description"] == "Export my claude.ai data"
    assert workflow["native"]["cowork-work-local"]["id"] == "t1"
    assert validate(repo).ok, validate(repo).problems
