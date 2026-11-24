"""A computer behind the shared repository, and accounts missing the always-on line, are noticed
instead of silently not saving."""

from harness.adapters import adapters
from harness.freshness import EngineFreshness
from harness.local import LocalHome
from harness.profiles import ProfileRegistry


def _written_by(repo, version):
    repo.path("README.md").write_text(
        f"# AI harness\n\n_Written by the [my-harness](https://github.com/chanaza/my-harness) engine "
        f"(v{version}) from this repository._\n", encoding="utf-8")


def test_an_older_engine_notices_and_updates_once_a_day(repo):
    _written_by(repo, "0.36.0")
    local = LocalHome()
    old = EngineFreshness(local, installed="0.30.1")
    assert old.behind(repo) == "0.36.0"
    assert "python -m harness update" in old.message(repo)
    started = []
    assert old.update_if_behind(repo, lambda args, text: started.append(args))
    assert not old.update_if_behind(repo, lambda args, text: started.append(args))  # not again today
    assert started == [["update"]]
    assert EngineFreshness(local, installed="0.36.0").message(repo) is None
    assert EngineFreshness(local, installed="0.40.0").behind(repo) is None


def test_an_account_without_the_always_on_line_is_named(repo):
    ProfileRegistry(repo).add("claude-ai", "personal", profile_id="claude-ai-personal-cloud",
                              environment="cloud")
    folder = repo.path("core", "instructions", "claude-ai-personal-cloud")
    folder.mkdir(parents=True)
    prefs = folder / "global-personal-preferences.md"
    prefs.write_text("---\norigin: describe-20261123-0225.yaml\n---\n\nAnswer in Hebrew.\n", "utf-8")
    adapter = adapters.create("claude-ai")
    assert adapter.always_on_missing(repo) == ["claude-ai-personal-cloud"]
    assert "Action needed" in adapter.connector_instructions(repo)
    assert adapter.always_on_line() in adapter.connector_instructions(repo)

    prefs.write_text(prefs.read_text("utf-8") + adapter.always_on_line() + "\n", "utf-8")
    assert adapter.always_on_missing(repo) == []
    assert "Action needed" not in adapter.connector_instructions(repo)
