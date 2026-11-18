"""Profiles, provenance, memory, sessions and checkpoint policy."""

import pytest
from conftest import PROFILE, validate

from harness.checkpoints import CheckpointPolicy, CheckpointProgress
from harness.config import CheckpointSettings
from harness.memory import MemoryStore
from harness.profiles import ProfileError, ProfileRegistry
from harness.provenance import Origin, Provenance
from harness.repo import ContentRepo
from harness.sessions import SessionRecord


def settings(**overrides) -> CheckpointSettings:
    values = dict(enabled=True, every_user_messages=10, every_context_percent=20,
                  force_at_context_percent=80, on_compaction=True, summary_max_words=400)
    return CheckpointSettings(**{**values, **overrides})


# --- profiles ---------------------------------------------------------------------

def test_profiles_are_registered_once(repo: ContentRepo):
    registry = ProfileRegistry(repo)
    first = registry.add("claude-code", "personal")
    assert first.id == "claude-code-personal"
    assert registry.add("claude-code", "personal") == first
    assert {"claude-code-personal", PROFILE} == registry.ids()


def test_profile_id_cannot_switch_tool(repo: ContentRepo):
    with pytest.raises(ProfileError):
        ProfileRegistry(repo).add("cursor", "work", profile_id=PROFILE)


def test_unregistered_profile_is_reported(repo: ContentRepo):
    SessionRecord(repo, "ghost-profile", "s1").touch()
    assert any("unknown profile 'ghost-profile'" in p for p in validate(repo).problems)


# --- provenance and memory ------------------------------------------------------------

def test_provenance_tracks_updates():
    block = Provenance.new(Origin.now("a"))
    block = Provenance.updated(block, Origin.now("b", "s2"))
    assert Provenance.last_profile(block) == "b"
    assert block["updates"][0]["session"] == "s2"


def test_memory_same_profile_updates_in_place(repo: ContentRepo):
    store = MemoryStore(repo)
    assert store.put("client", "Prefers mornings", Origin.now(PROFILE)).action == "created"
    assert store.put("client", "Prefers mornings", Origin.now(PROFILE)).action == "unchanged"
    assert store.put("client", "Prefers evenings", Origin.now(PROFILE)).action == "updated"
    assert validate(repo).ok


def test_memory_conflict_between_profiles_keeps_both(repo: ContentRepo):
    ProfileRegistry(repo).add("claude-code", "personal")
    store = MemoryStore(repo)
    store.put("client", "Prefers mornings", Origin.now(PROFILE))
    result = store.put("client", "Prefers evenings", Origin.now("claude-code-personal"))
    assert result.action == "conflict"
    original = repo.path("memory", "client.md").read_text()
    assert "status: disputed" in original and "client--claude-code-personal" in original
    assert "Prefers evenings" in result.path.read_text()
    assert validate(repo).ok


# --- sessions ----------------------------------------------------------------------------

def test_session_summary_and_compactions(repo: ContentRepo):
    session = SessionRecord(repo, PROFILE, "abc:123")
    assert session.id == "abc-123"
    assert session.write_summary("First", "test") == 1
    assert session.write_summary("Second", "test", 42.0, 7) == 2
    assert session.summary().body.strip() == "Second"
    assert session.add_compaction("Compacted").name == "001.md"
    assert session.add_compaction("Again").name == "002.md"
    assert session.meta()["native_id"] == "abc:123"
    assert validate(repo).ok


# --- checkpoint policy --------------------------------------------------------------------

@pytest.mark.parametrize("progress, percent, expected", [
    (CheckpointProgress(user_messages_since=10), None, "messages"),
    (CheckpointProgress(user_messages_since=3), 15.0, None),
    (CheckpointProgress(percent_at_last=10.0), 31.0, "grew"),
    (CheckpointProgress(percent_at_last=70.0), 81.0, "reached"),
    (CheckpointProgress(percent_at_last=81.0, forced_done=True), 85.0, None),
])
def test_checkpoint_triggers(progress, percent, expected):
    reason = CheckpointPolicy(settings()).due(progress, percent)
    assert (reason is None) if expected is None else (expected in reason)


def test_checkpoint_triggers_can_be_turned_off():
    policy = CheckpointPolicy(settings(every_user_messages=0, every_context_percent=0,
                                       force_at_context_percent=0))
    assert policy.due(CheckpointProgress(user_messages_since=99), 99.0) is None
    disabled = CheckpointPolicy(settings(enabled=False))
    assert disabled.due(CheckpointProgress(user_messages_since=99), None) is None


def test_checkpoint_reset_marks_forced():
    policy = CheckpointPolicy(settings())
    after = policy.reset(CheckpointProgress(user_messages_since=4), 82.0)
    assert after == CheckpointProgress(user_messages_since=0, percent_at_last=82.0, forced_done=True)
