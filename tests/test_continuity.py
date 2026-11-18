"""Continuity: profile rename/environment, git storage, structured checkpoints, workspace, upgrade."""

import subprocess
from pathlib import Path

import pytest
from conftest import PROFILE, event, validate, write_transcript

from harness.checkpoints import CheckpointRecorder
from harness.digest import SECTIONS, split_sections
from harness.local import LocalHome
from harness.memory import MemoryStore
from harness.profiles import ProfileError, ProfileRegistry
from harness.provenance import Origin
from harness.repo import ContentRepo
from harness.sessions import SessionRecord
from harness.storage import GitStorage, StorageError, backends
from harness.workspace import WorkspaceScanner, merge_workspace

SUMMARY = """## Goal
Build my-harness.

## Decisions
- Two repos.

## Current state
Phase 3.

## Open thread
Waiting for approval of the plan.

## Standing instructions
- Approve every design step with me.
- Never write content into the content repo by hand.

## Preferences learned
- Prefers Hebrew conversation.

## Connections in use
- gmail: read and draft e-mail
- google-drive: file revisions
"""


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    git("init", "-q", "--bare", str(bare), cwd=tmp_path)
    return bare


# --- profiles ---------------------------------------------------------------------

def test_profile_environment_and_rename(repo: ContentRepo, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    registry = ProfileRegistry(repo)
    profile = registry.add("claude-code", "personal", environment="cloud")
    assert profile.id == "claude-code-personal-cloud"
    with pytest.raises(ProfileError):
        registry.add("claude-code", "x", environment="moon")

    old = "claude-code-personal-cloud"
    MemoryStore(repo).put("fact", "x", Origin.now(old))
    SessionRecord(repo, old, "s1").write_summary("Summary", "test")
    LocalHome().save_settings(profiles={"claude-code": {"/home/.claude": old}})

    changes = registry.rename(old, "cc-cloud")
    LocalHome().rename_profile(old, "cc-cloud")
    assert "sessions/claude-code-personal-cloud -> sessions/cc-cloud" in changes
    assert "profile: cc-cloud" in repo.path("memory", "fact.md").read_text()
    assert registry.get("cc-cloud").environment == "cloud"
    assert LocalHome().settings()["profiles"]["claude-code"]["/home/.claude"] == "cc-cloud"
    assert validate(repo).ok, validate(repo).problems


# --- storage ----------------------------------------------------------------------

def test_git_storage_roundtrip(remote: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    store = backends.create({"backend": "git", "remote": str(remote), "branch": "transcripts"})
    assert isinstance(store, GitStorage)
    store.write_text("p/s1/transcript.jsonl", "line\n")
    store.append_text("p/s1/notes.md", "a\n")
    store.append_text("p/s1/notes.md", "b\n")
    assert git("ls-tree", "-r", "--name-only", "transcripts", cwd=remote).split() == [
        "p/s1/notes.md", "p/s1/transcript.jsonl"]

    fresh = GitStorage(str(remote), "transcripts", tmp_path / "other-checkout")
    assert fresh.read_text("p/s1/notes.md") == "a\nb\n"
    assert fresh.list_keys("p/") == ["p/s1/notes.md", "p/s1/transcript.jsonl"]


def test_git_storage_origin_needs_a_remote(repo: ContentRepo):
    with pytest.raises(StorageError):
        backends.create({"backend": "git", "remote": "origin", "content_repo": str(repo.root)})


def test_storage_by_profile_overrides_default(repo: ContentRepo, tmp_path: Path):
    repo.config_file.update({"storage_by_profile.cloudy.transcripts.backend": "filesystem",
                             "storage_by_profile.cloudy.transcripts.path": str(tmp_path / "cloud")})
    assert repo.config.storage_settings("transcripts", "cloudy")["path"] == str(tmp_path / "cloud")
    assert repo.config.storage_settings("transcripts", "other")["path"].endswith("transcripts")
    assert validate(repo).ok


# --- structured checkpoints -------------------------------------------------------------

def test_split_sections():
    sections = split_sections(SUMMARY)
    assert list(sections) == list(SECTIONS)
    assert sections["Open thread"] == "Waiting for approval of the plan."


def test_checkpoint_digests_harness_sections_out_of_the_summary(repo: ContentRepo, tmp_path: Path,
                                                                monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    ProfileRegistry(repo).add("claude-code", "personal", profile_id="cc")
    session = SessionRecord(repo, "cc", "s1")
    recorder = CheckpointRecorder(LocalHome(), repo, session)
    recorder.record_turn(12.0)

    result = recorder.write(SUMMARY, "test")
    assert result.number == 1
    standing = repo.path("core", "instructions", "cc", "standing-instructions.md").read_text()
    assert "Never write content into the content repo by hand" in standing
    assert "Prefers Hebrew" in repo.path("memory", "cc-preferences-s1.md").read_text()
    connections = repo.path("core", "connections.yaml").read_text()
    assert "gmail" in connections and "google-drive" in connections
    summary = session.summary().body
    assert "## Open thread" in summary and "Standing instructions" not in summary  # no duplication

    recorder.write(SUMMARY.replace("Never write", "Do not write"), "test")
    standing = repo.path("core", "instructions", "cc", "standing-instructions.md").read_text()
    assert standing.count("## Session s1") == 1 and "Do not write" in standing
    assert validate(repo).ok, validate(repo).problems


def test_empty_sections_are_not_digested(repo: ContentRepo, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    session = SessionRecord(repo, PROFILE, "s2")
    text = "## Goal\nX\n\n## Standing instructions\nNone\n\n## Connections in use\nNone\n"
    assert CheckpointRecorder(LocalHome(), repo, session).write(text, "t").digested == []


# --- hooks: workspace, request ----------------------------------------------------------

def test_stop_records_workspace_and_structured_request(adapter, repo: ContentRepo, tmp_path: Path):
    project = adapter.locations.project_dir
    git("init", "-q", cwd=project)
    git("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x", cwd=project)
    git("remote", "add", "origin", "https://user:token@github.com/me/app.git", cwd=project)
    repo.config_file.update({"checkpoints.every_user_messages": 1})
    transcript = write_transcript(tmp_path / "t.jsonl", 3, 20_000)
    adapter.handle_hook(event("UserPromptSubmit", transcript, project))
    adapter.handle_hook(event("Stop", transcript, project))
    response = adapter.handle_hook(event("UserPromptSubmit", transcript, project))

    meta = SessionRecord(repo, "claude-code-personal", "sess-1").meta()
    assert meta["workspace"][0]["remote"] == "https://github.com/me/app.git"  # credentials removed
    request = response["hookSpecificOutput"]["additionalContext"]
    assert all(f"## {s}" in request for s in SECTIONS)
    assert validate(repo).ok, validate(repo).problems


def test_workspace_accumulates_across_folders():
    first = [{"path": "a", "remote": "r-a"}, {"path": "b", "remote": "r-b"}]
    later = [{"path": ".", "remote": "r-a", "head": "2"}]
    merged = merge_workspace(first, later)
    assert [(r["path"], r.get("head")) for r in merged] == [("a", "2"), ("b", None)]


def test_upgrade_migrates_old_session_records(repo: ContentRepo, tmp_path: Path):
    from harness import yaml_io
    from harness.migrations import run_migrations
    session = SessionRecord(repo, PROFILE, "old")
    session.write_summary(SUMMARY, "old")  # an old summary with all seven sections
    meta = session.meta() | {"tail": f"{PROFILE}/old/tail.md"}
    session.meta_path.write_text(yaml_io.dump(meta))
    (session.folder / "compactions").mkdir()
    (session.folder / "compactions" / "001.md").write_text("x")

    changes = run_migrations(repo)["simplify-session-records"]
    assert any("compactions" in c for c in changes)
    assert "tail" not in session.meta()
    assert "Standing instructions" not in session.summary().body
    assert run_migrations(repo) == {}  # idempotent
    assert validate(repo).ok, validate(repo).problems


def test_workspace_scanner_finds_nested_repos(tmp_path: Path):
    (tmp_path / "a").mkdir()
    git("init", "-q", cwd=tmp_path / "a")
    (tmp_path / "plain").mkdir()
    assert [r.path for r in WorkspaceScanner(tmp_path).scan()] == ["a"]


def test_rename_moves_derived_names_and_finishes_partial_renames(repo: ContentRepo, tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    registry = ProfileRegistry(repo)
    registry.add("claude-code", "personal", environment="local")
    old, new = "claude-code-personal-local", "claude-code-work-local"
    MemoryStore(repo).put(f"{old}-projects-notes", "x", Origin.now(old))

    registry.rename(old, new)
    assert repo.path("memory", f"{new}-projects-notes.md").is_file()
    assert f"id: {new}-projects-notes" in repo.path("memory", f"{new}-projects-notes.md").read_text()
    assert registry.get(new).previous_ids == [old]

    # an older engine left a file with the old name behind: running rename again finishes it
    leftover = repo.path("memory", f"{old}-other.md")
    leftover.write_text(repo.path("memory", f"{new}-projects-notes.md").read_text()
                        .replace(f"{new}-projects-notes", f"{old}-other"))
    changes = registry.rename(old, new)
    assert any("-other.md" in c for c in changes) and not leftover.exists()
    assert validate(repo).ok, validate(repo).problems
