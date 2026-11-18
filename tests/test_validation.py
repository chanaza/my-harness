from conftest import PROVENANCE, validate

from harness import yaml_io
from harness.repo import ContentRepo
from harness.validation import Check, Report, RepoValidator


def test_memory_requires_provenance(repo: ContentRepo):
    entry = repo.path("memory", "client.md")
    entry.write_text("---\nid: client\nkind: fact\nstatus: active\n---\nBody\n")
    assert any("provenance" in p for p in validate(repo).problems)

    meta = {"id": "client", "kind": "fact", "status": "active", "provenance": PROVENANCE}
    entry.write_text(f"---\n{yaml_io.dump(meta)}---\nBody\n")
    assert validate(repo).ok


def test_skill_without_frontmatter_is_reported(repo: ContentRepo):
    skill = repo.path("core", "skills", "bad", "SKILL.md")
    skill.parent.mkdir()
    skill.write_text("no frontmatter here")
    assert any("frontmatter" in p for p in validate(repo).problems)


def test_oversized_asset_is_reported(repo: ContentRepo):
    repo.config_file.update({"assets.max_inline_size_mb": 0.001})
    asset = repo.path("assets", "deck")
    asset.mkdir()
    (asset / "deck.pptx").write_bytes(b"0" * 5000)
    assert any("exceeds the inline limit" in p for p in validate(repo).problems)


def test_custom_checks_can_be_plugged_in(repo: ContentRepo):
    class AlwaysFails(Check):
        def run(self, repo: ContentRepo, report: Report) -> None:
            report.add("x", "custom problem")

    assert RepoValidator([AlwaysFails()]).validate(repo).problems == ["x: custom problem"]
