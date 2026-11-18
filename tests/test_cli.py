from pathlib import Path

from conftest import WINDOWS_PATH

from harness.cli import main
from harness.repo import ContentRepo


def test_cli_end_to_end(tmp_path: Path, capsys):
    target = tmp_path / "c"
    assert main(["init", str(target), "--owner", "Test", "--tools", "claude-code", "chatgpt"]) == 0
    assert ContentRepo(target).config.tools == ["claude-code", "chatgpt"]

    assert main(["config", "set", "storage.transcripts.path", WINDOWS_PATH, "--repo", str(target)]) == 0
    assert main(["config", "set", "capture.live_log_threshold_percent", "75", "--repo", str(target)]) == 0
    assert ContentRepo(target).config.live_log_threshold_percent == 75

    capsys.readouterr()
    assert main(["config", "get", "storage.transcripts.path", "--repo", str(target)]) == 0
    assert capsys.readouterr().out.strip() == WINDOWS_PATH

    assert main(["validate", "--repo", str(target)]) == 0


def test_cli_reports_invalid_setting(repo: ContentRepo, capsys):
    assert main(["config", "set", "capture.live_log_threshold_percent", "150", "--repo", str(repo.root)]) == 1
    assert "error:" in capsys.readouterr().err
