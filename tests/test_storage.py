from pathlib import Path

import pytest

from harness.repo import ContentRepo
from harness.storage import FilesystemStorage, Storage, StorageError, backends


def test_repo_opens_configured_storage(repo: ContentRepo):
    store = repo.storage("transcripts")
    assert isinstance(store, FilesystemStorage)
    store.write_text("claude-code/s1/transcript.md", "hello\n")
    store.append_text("claude-code/s1/transcript.md", "world\n")
    assert store.read_text("claude-code/s1/transcript.md") == "hello\nworld\n"
    assert store.list_keys("claude-code/") == ["claude-code/s1/transcript.md"]
    store.delete("claude-code/s1/transcript.md")
    assert not store.exists("claude-code/s1/transcript.md")


def test_storage_rejects_escaping_keys(tmp_path: Path):
    with pytest.raises(StorageError):
        FilesystemStorage(tmp_path).write_text("../outside.txt", "x")


def test_unknown_backend():
    with pytest.raises(StorageError):
        backends.create({"backend": "nope"})


def test_backend_registry_rejects_unnamed_backend():
    class Unnamed(Storage):  # type: ignore[abstract]
        pass

    with pytest.raises(ValueError):
        backends.register(Unnamed)


def test_filesystem_rejects_paths_not_absolute_here():
    with pytest.raises(StorageError):
        backends.create({"backend": "filesystem", "path": "relative/folder"})
