"""`harness setup` and `harness status`."""

import json
import subprocess
from pathlib import Path

import pytest

from harness.adapters.claude_code import ClaudeCodeLocations
from harness.cli import main
from harness.local import LocalHome
from harness.profiles import ProfileRegistry
from harness.repo import ContentRepo
from harness.setup import DefaultsPrompter, Prompter, SetupError, SetupOptions, SetupWizard


class ScriptedPrompter(Prompter):
    """Answers questions from a list, in order; records what was said."""

    def __init__(self, *answers: str | bool) -> None:
        self.answers = list(answers)
        self.questions: list[str] = []
        self.said: list[str] = []

    def ask(self, question: str, default: str | None = None) -> str:
        self.questions.append(question)
        return self.answers.pop(0) or default

    def confirm(self, question: str, default: bool = True) -> bool:
        self.questions.append(question)
        return self.answers.pop(0)

    def say(self, text: str) -> None:
        self.said.append(text)


@pytest.fixture
def machine(tmp_path: Path, monkeypatch, claude: ClaudeCodeLocations):
    """HOME with a Claude Code installation and an empty clone of a harness repository."""
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "harness-home"))
    LocalHome().save_settings(machine="local")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude.config_dir))
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    clone = tmp_path / "my-content"
    clone.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=clone, check=True)
    return clone


def test_interactive_setup_creates_harness_and_captures(machine: Path, tmp_path: Path):
    prompter = ScriptedPrompter(
        "local",                      # environment
        str(machine),                 # where is the repository
        True,                         # create a new harness there
        "Dana",                       # owner
        "work",                       # account
        str(tmp_path / "onedrive"),   # transcripts folder
        True,                         # capture now
    )
    result = SetupWizard(prompter, LocalHome()).run(SetupOptions())
    repo = ContentRepo(machine)
    assert result.profile == "claude-code-work-local"
    assert ProfileRegistry(repo).get("claude-code-work-local").environment == "local"
    settings = repo.config.storage_settings("transcripts", "claude-code-work-local")
    assert settings == {"backend": "filesystem", "path": str(tmp_path / "onedrive")}
    assert repo.path("core", "skills", "deck-review", "SKILL.md").is_file()  # captured
    assert any("captured:" in line for line in result.done)
    hooks = json.loads((Path(ClaudeCodeLocations.detect().settings_file)).read_text())["hooks"]
    assert "Stop" in hooks
    # capture only: nothing from the harness was written into Claude Code's instructions
    assert (ClaudeCodeLocations.detect().config_dir / "CLAUDE.md").read_text() == "Always answer in Hebrew.\n"


def test_unattended_cloud_setup(machine: Path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    main(["init", str(machine), "--owner", "Dana"])
    subprocess.run(["git", "remote", "add", "origin", "https://example.com/x.git"], cwd=machine, check=True)
    result = SetupWizard(DefaultsPrompter(), LocalHome()).run(
        SetupOptions(repo=str(machine), account="personal", capture_now=False))
    assert result.profile == "claude-code-personal-cloud"
    repo = ContentRepo(machine)
    assert repo.config.storage_settings("transcripts", result.profile)["backend"] == "git"
    assert not repo.path("core", "skills", "deck-review").exists()  # capture_now=False


def test_unattended_setup_needs_a_repository(machine: Path):
    with pytest.raises(SetupError):
        SetupWizard(DefaultsPrompter(), LocalHome()).run(SetupOptions(environment="local"))


def test_status_reports_connection_and_problems(machine: Path, capsys):
    main(["setup", "--repo", str(machine), "--account", "personal", "--environment", "local",
          "--owner", "Dana", "--transcripts", str(machine.parent / "t"), "--yes", "--no-capture"])
    LocalHome().log("claude-code x transcript failed: boom")
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "claude-code-personal-local" in out and "Repository check: OK" in out
    assert "transcript failed: boom" in out


def test_repository_question_repeats_until_valid(machine: Path, tmp_path: Path):
    prompter = ScriptedPrompter("local", "folder", str(machine), True, "Dana", "work",
                                str(tmp_path / "t"), False)
    SetupWizard(prompter, LocalHome()).run(SetupOptions())
    assert any("neither a GitHub address nor an existing folder" in s for s in prompter.said)


def test_missing_folder_option_is_an_error(machine: Path, tmp_path: Path):
    with pytest.raises(SetupError):
        SetupWizard(DefaultsPrompter(), LocalHome()).run(
            SetupOptions(repo=str(tmp_path / "nope"), environment="local"))


def test_update_runs_every_step_with_fresh_processes(machine: Path, tmp_path: Path):
    import subprocess as sp

    from harness.update import Updater
    main(["setup", "--repo", str(machine), "--account", "personal", "--environment", "local",
          "--owner", "Dana", "--transcripts", str(tmp_path / "t"), "--yes", "--no-capture"])
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command[1:])
        return sp.CompletedProcess(command, 0, "", "")

    report = Updater(run=fake_run).update(engine=False)
    assert not report.problems
    assert [c[2] for c in calls] == ["upgrade", "install", "harvest"]
    assert "claude-code-personal-local" in calls[1]


def test_setup_on_a_connected_machine_updates_instead_of_asking(machine: Path, tmp_path: Path,
                                                               monkeypatch, capsys):
    from harness.update import Updater, UpdateReport
    main(["setup", "--repo", str(machine), "--account", "personal", "--environment", "local",
          "--owner", "Dana", "--transcripts", str(tmp_path / "t"), "--yes", "--no-capture"])
    called = {}

    def fake_update(self, engine: bool = True) -> UpdateReport:
        called["engine"] = engine
        return UpdateReport()

    monkeypatch.setattr(Updater, "update", fake_update)
    capsys.readouterr()
    assert main(["setup"]) == 0
    assert "already connected" in capsys.readouterr().out
    assert called == {"engine": False}


def test_naming_a_computer_renames_its_local_profiles(tmp_path, monkeypatch, capsys):
    from harness.cli.app import main
    from harness.profiles import ProfileRegistry
    from harness.repo import ContentRepo
    from harness.scaffold import InitOptions, Scaffolder
    repo = Scaffolder().create(tmp_path / "content", InitOptions(owner="T"))
    ProfileRegistry(repo).add("claude-code", "work", environment="local")
    ProfileRegistry(repo).add("claude-code", "personal", environment="cloud")
    local = LocalHome()
    local.save_settings(content_repo=str(repo.root),
                        profiles={"claude-code": {"/c": "claude-code-work-local"}})
    assert main(["machine", "name", "Office", "--repo", str(repo.root)]) == 0
    ids = ProfileRegistry(ContentRepo(repo.root)).ids()
    assert ids == {"claude-code-work-office", "claude-code-personal-cloud"}
    assert LocalHome().machine() == "office"
    assert LocalHome().settings()["profiles"]["claude-code"]["/c"] == "claude-code-work-office"
    assert main(["sources"]) == 0
    assert "claude-code  push" in capsys.readouterr().out
