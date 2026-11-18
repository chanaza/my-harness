from pathlib import Path

import pytest
import yaml

from harness.cli import main
from harness.config import ConfigError, load_config
from harness.layout import AREAS
from harness.scaffold import InitOptions, ScaffoldError, init_repo
from harness.schema_loader import schema_errors, schema_names
from harness.storage import FilesystemStorage, StorageError, open_storage
from harness.validate import validate_repo

PROVENANCE = {"source": {"tool": "chatgpt", "session": "20261118-1430-chatgpt-x",
                         "at": "2026-11-18T14:30:00Z"}}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    init_repo(tmp_path / "content", InitOptions(owner="Test", transcripts_path=str(tmp_path / "t")))
    return tmp_path / "content"


def test_all_schemas_load():
    for name in schema_names():
        schema_errors(name, {})  # must not raise


def test_init_creates_every_area(repo: Path):
    for area in AREAS:
        assert (repo / area.path).is_dir(), area.path
    assert (repo / "README.md").is_file()


def test_init_config_is_valid(repo: Path):
    config = load_config(repo)
    assert config.working_language == "en"
    assert config.live_log_threshold_percent == 80
    assert config.storage_settings("transcripts")["backend"] == "filesystem"


def test_fresh_repo_validates(repo: Path):
    report = validate_repo(repo)
    assert report.ok, report.problems


def test_init_refuses_non_empty(tmp_path: Path):
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(ScaffoldError):
        init_repo(tmp_path, InitOptions(owner="Test"))


def test_init_accepts_empty_git_clone(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    init_repo(tmp_path, InitOptions(owner="Test"))
    assert validate_repo(tmp_path).ok


def test_memory_requires_provenance(repo: Path):
    entry = repo / "memory" / "client.md"
    entry.write_text("---\nid: client\nkind: fact\nstatus: active\n---\nBody\n")
    report = validate_repo(repo)
    assert any("provenance" in p for p in report.problems)

    meta = {"id": "client", "kind": "fact", "status": "active", "provenance": PROVENANCE}
    entry.write_text(f"---\n{yaml.safe_dump(meta)}---\nBody\n")
    assert validate_repo(repo).ok


def test_invalid_skill_is_reported(repo: Path):
    skill = repo / "core" / "skills" / "bad" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text("no frontmatter here")
    report = validate_repo(repo)
    assert any("frontmatter" in p for p in report.problems)


def test_oversized_asset_is_reported(repo: Path):
    config = repo / "harness.config.yaml"
    config.write_text(config.read_text().replace("max_inline_size_mb: 10", "max_inline_size_mb: 0.001"))
    asset = repo / "assets" / "deck"
    asset.mkdir()
    (asset / "deck.pptx").write_bytes(b"0" * 5000)
    report = validate_repo(repo)
    assert any("exceeds the inline limit" in p for p in report.problems)


def test_missing_config(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_filesystem_storage_roundtrip(tmp_path: Path):
    store = open_storage({"backend": "filesystem", "path": str(tmp_path)})
    assert isinstance(store, FilesystemStorage)
    store.write_text("claude-code/s1/transcript.md", "hello\n")
    store.append_text("claude-code/s1/transcript.md", "world\n")
    assert store.read_text("claude-code/s1/transcript.md") == "hello\nworld\n"
    assert store.list_keys("claude-code/") == ["claude-code/s1/transcript.md"]
    store.delete("claude-code/s1/transcript.md")
    assert not store.exists("claude-code/s1/transcript.md")


def test_storage_rejects_escaping_keys(tmp_path: Path):
    store = FilesystemStorage(tmp_path)
    with pytest.raises(StorageError):
        store.write_text("../outside.txt", "x")


def test_unknown_backend():
    with pytest.raises(StorageError):
        open_storage({"backend": "nope"})


def test_cli_init_and_validate(tmp_path: Path, capsys):
    target = tmp_path / "c"
    assert main(["init", str(target), "--owner", "Test", "--tools", "claude-code", "chatgpt"]) == 0
    assert load_config(target).tools == ["claude-code", "chatgpt"]
    assert main(["validate", str(target)]) == 0
    assert "OK" in capsys.readouterr().out


def test_dates_are_checked():
    bad = {"source": {"tool": "chatgpt", "at": "yesterday"}}
    assert schema_errors("provenance", bad)
    assert not schema_errors("provenance", PROVENANCE)
