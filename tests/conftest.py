from pathlib import Path

import pytest

from harness.repo import ContentRepo
from harness.scaffold import InitOptions, Scaffolder
from harness.validation import Report, RepoValidator

PROVENANCE = {"source": {"tool": "chatgpt", "session": "20261118-1430-chatgpt-x",
                         "at": "2026-11-18T14:30:00Z"}}
WINDOWS_PATH = r"C:\Users\someone\OneDrive - example.com\Documents\Sessions\transcripts"


def validate(repo: ContentRepo) -> Report:
    return RepoValidator.default(repo.layout).validate(repo)


@pytest.fixture
def repo(tmp_path: Path) -> ContentRepo:
    options = InitOptions(owner="Test", storage_paths={"transcripts": str(tmp_path / "transcripts")})
    return Scaffolder().create(tmp_path / "content", options)
