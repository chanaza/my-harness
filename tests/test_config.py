from pathlib import Path

import pytest
from conftest import WINDOWS_PATH

from harness.config import ConfigError
from harness.repo import ContentRepo


def test_config_update_keeps_comments_and_handles_windows_paths(repo: ContentRepo):
    repo.config_file.update({"storage.transcripts.path": WINDOWS_PATH})
    assert repo.config.storage_settings("transcripts")["path"] == WINDOWS_PATH
    comment = "# Full transcripts (saved every turn) never go into the main branch."
    assert comment in repo.config_file.path.read_text()


def test_invalid_config_update_is_not_written(repo: ContentRepo):
    before = repo.config_file.path.read_text()
    with pytest.raises(ConfigError):
        repo.config_file.update({"checkpoints.force_at_context_percent": 150})
    assert repo.config_file.path.read_text() == before


def test_missing_config(tmp_path: Path):
    with pytest.raises(ConfigError):
        ContentRepo(tmp_path).config_file.load()


def test_settings_a_newer_engine_removed_do_not_stop_it(repo):
    """A computer whose harness copy is older than its engine keeps working."""
    path = repo.config_file.path
    path.write_text(path.read_text().replace("claude_ai:\n", "claude_ai:\n  inbox_folder: ~/old\n", 1))
    assert repo.config_file.load().claude_ai.skill_folder            # loads; the old setting is ignored
    assert "claude_ai.inbox_folder" in repo.config_file.obsolete_settings()
