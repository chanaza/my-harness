from pathlib import Path

import pytest

from harness.profiles import ProfileRegistry
from harness.repo import ContentRepo
from harness.scaffold import InitOptions, Scaffolder
from harness.validation import Report, RepoValidator

PROFILE = "chatgpt-work"
PROVENANCE = {"source": {"profile": PROFILE, "session": "20261118-1430-chatgpt-x",
                         "at": "2026-11-18T14:30:00Z"}}
WINDOWS_PATH = r"C:\Users\someone\OneDrive - example.com\Documents\Sessions\transcripts"


def validate(repo: ContentRepo) -> Report:
    return RepoValidator.default(repo.layout).validate(repo)


@pytest.fixture
def repo(tmp_path: Path) -> ContentRepo:
    options = InitOptions(owner="Test", storage_paths={"transcripts": str(tmp_path / "transcripts")})
    repo = Scaffolder().create(tmp_path / "content", options)
    ProfileRegistry(repo).add("chatgpt", "work")
    return repo
