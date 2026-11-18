from pathlib import Path

import pytest
from conftest import validate

from harness.layout import DEFAULT_LAYOUT
from harness.repo import ContentRepo
from harness.scaffold import InitOptions, Scaffolder, ScaffoldError


def test_init_creates_every_area(repo: ContentRepo):
    for area in DEFAULT_LAYOUT.areas:
        assert repo.path(area.path).is_dir(), area.path
    assert repo.path("README.md").is_file()


def test_init_applies_options(repo: ContentRepo):
    config = repo.config
    assert config.data["owner"] == "Test"
    assert config.working_language == "en"
    assert config.live_log_threshold_percent == 80
    assert config.storage_settings("transcripts")["path"].endswith("transcripts")


def test_fresh_repo_validates(repo: ContentRepo):
    report = validate(repo)
    assert report.ok, report.problems


def test_init_refuses_non_empty(tmp_path: Path):
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(ScaffoldError):
        Scaffolder().create(tmp_path, InitOptions(owner="Test"))


def test_init_accepts_empty_git_clone(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert validate(Scaffolder().create(tmp_path, InitOptions(owner="Test"))).ok
