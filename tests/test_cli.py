from pathlib import Path

from conftest import WINDOWS_PATH

from harness.cli import main
from harness.repo import ContentRepo


def test_cli_end_to_end(tmp_path: Path, capsys):
    target = tmp_path / "c"
    assert main(["init", str(target), "--owner", "Test", "--tools", "claude-code", "chatgpt"]) == 0
    assert ContentRepo(target).config.tools == ["claude-code", "chatgpt"]

    assert main(["config", "set", "storage.transcripts.path", WINDOWS_PATH, "--repo", str(target)]) == 0
    assert main(["config", "set", "checkpoints.every_user_messages", "15", "--repo", str(target)]) == 0
    assert ContentRepo(target).config.checkpoints.every_user_messages == 15

    capsys.readouterr()
    assert main(["config", "get", "storage.transcripts.path", "--repo", str(target)]) == 0
    assert capsys.readouterr().out.strip() == WINDOWS_PATH

    assert main(["validate", "--repo", str(target)]) == 0


def test_cli_reports_invalid_setting(repo: ContentRepo, capsys):
    args = ["config", "set", "checkpoints.force_at_context_percent", "150", "--repo", str(repo.root)]
    assert main(args) == 1
    assert "error:" in capsys.readouterr().err


def test_cli_upgrade_adds_new_removes_obsolete_keeps_values(repo, capsys):
    from harness import yaml_io
    config = repo.config_file.path
    data = yaml_io.load(config.read_text())
    data.pop("checkpoints")
    data["capture"]["context_window_tokens"] = 1_000_000
    data["capture"]["tail_exchanges"] = 10  # an obsolete setting
    data["storage"]["live_logs"] = {"backend": "filesystem", "path": "/x"}
    config.write_text(yaml_io.dump(data))
    repo.path("core", "profiles.yaml").unlink()

    assert main(["upgrade", "--repo", str(repo.root)]) == 0
    out = capsys.readouterr().out
    assert "checkpoints.every_user_messages" in out and "profiles.yaml" in out
    assert "capture.tail_exchanges" in out and "storage.live_logs.path" in out
    assert repo.config.capture.context_window_tokens == 1_000_000
    assert "# A checkpoint refreshes the rolling session summary" in config.read_text()
    assert "tail_exchanges" not in config.read_text()


def test_cli_profile_session_and_memory(repo, monkeypatch, tmp_path, capsys):
    import io
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    root = str(repo.root)
    assert main(["profile", "add", "claude-code", "work", "--repo", root]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("We designed the harness."))
    assert main(["session", "checkpoint", "--profile", "claude-code-work", "--session", "s1",
                 "--repo", root]) == 0
    assert "We designed" in repo.path("sessions", "claude-code-work", "s1", "summary.md").read_text()
    monkeypatch.setattr("sys.stdin", io.StringIO("Works on Windows."))
    assert main(["memory", "add", "--profile", "claude-code-work", "--id", "os", "--repo", root]) == 0
    assert repo.path("memory", "os.md").is_file()
    assert main(["validate", "--repo", root]) == 0


def test_cli_hook_never_fails(monkeypatch, tmp_path):
    import io
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("HARNESS_REPO", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"hook_event_name": "Stop"}'))
    assert main(["hook", "claude-code"]) == 0
    assert "not configured" in (tmp_path / "home" / "logs" / "harness.log").read_text()
