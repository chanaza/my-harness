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
