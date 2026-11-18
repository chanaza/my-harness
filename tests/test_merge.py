"""Merging the harness's YAML files by content when two machines changed them."""

import subprocess
from pathlib import Path

from harness.config import GitSettings
from harness.git_sync import GitSync
from harness.merge import MISSING, merge_values
from harness.repo import ContentRepo
from harness.scaffold import InitOptions, Scaffolder


def test_changes_to_different_keys_are_combined():
    base = {"a": 1, "b": {"x": 1}}
    assert merge_values(base, {"a": 2, "b": {"x": 1}}, {"a": 1, "b": {"x": 1, "y": 5}}) == \
        {"a": 2, "b": {"x": 1, "y": 5}}


def test_lists_are_united_and_removals_kept():
    assert merge_values(["a", "b"], ["a", "b", "c"], ["a", "d"]) == ["a", "c", "d"]


def test_records_with_ids_merge_record_by_record():
    base = [{"id": "p1", "label": "x"}]
    ours = [{"id": "p1", "label": "y"}]
    theirs = [{"id": "p1", "label": "x"}, {"id": "p2", "label": "new"}]
    assert merge_values(base, ours, theirs) == [{"id": "p1", "label": "y"}, {"id": "p2", "label": "new"}]


def test_deleted_key_stays_deleted():
    assert merge_values({"a": 1, "b": 2}, {"a": 1}, {"a": 1, "b": 2}) == {"a": 1}
    assert merge_values(MISSING, {"new": 1}, MISSING) == {"new": 1}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout


def test_two_machines_change_the_settings_file_at_once(tmp_path: Path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    first = tmp_path / "cloud"
    git(tmp_path, "clone", "-q", str(remote), str(first))
    Scaffolder().create(first, InitOptions(owner="Dana"))
    for args in (("add", "-A"), ("commit", "-q", "-m", "init"), ("push", "-q", "-u", "origin", "HEAD")):
        git(first, *args)
    second = tmp_path / "windows"
    git(tmp_path, "clone", "-q", str(remote), str(second))

    ContentRepo(first).config_file.update({"harvest.exclude": ["skill:pdf"]})
    git(first, "commit", "-qam", "exclude")
    git(first, "push", "-q")
    ContentRepo(second).config_file.update({"checkpoints.every_user_messages": 15,
                                            "harvest.exclude": ["skill:docx"]})
    settings = GitSettings(auto_commit=True, auto_push=True)
    result = GitSync(second, settings, log=lambda m: None).sync("windows change", push=True)
    assert result.pushed, result.message

    merged = ContentRepo(second).config
    assert merged.checkpoints.every_user_messages == 15
    assert merged.harvest_exclude == ["skill:pdf", "skill:docx"] or \
        sorted(merged.harvest_exclude) == ["skill:docx", "skill:pdf"]
    assert "# A checkpoint refreshes" in (second / "harness.config.yaml").read_text()  # comments kept


def test_merge_driver_command_survives_a_posix_shell(tmp_path: Path, monkeypatch):
    """Windows paths must keep their separators when Git runs the driver through sh."""
    import sys

    monkeypatch.setattr(sys, "executable", r"C:\Users\me\AppData\Python312\python.exe")
    git(tmp_path, "init", "-q")
    GitSync(tmp_path, GitSettings(True, True), log=lambda m: None)._register_merge_driver()
    driver = git(tmp_path, "config", "merge.harness.driver").strip()
    assert driver.startswith("C:/Users/me/AppData/Python312/python.exe -m harness merge-file")
    assert "\\" not in driver
