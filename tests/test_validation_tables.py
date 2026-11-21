"""TablesCheck: an app's table list and its table files agree, whatever tool it came from."""

from __future__ import annotations

from harness.repo import ContentRepo
from harness.validation import RepoValidator


def test_a_table_listed_without_its_file_is_reported(repo: ContentRepo):
    app = repo.path("apps", "crm")
    (app / "entities").mkdir(parents=True)
    (app / "entities.json").write_text('{"Customers": {}, "Orders": {}}')
    (app / "entities" / "Customers.json").write_text("{}")
    report = RepoValidator.default(repo.layout).validate(repo)
    assert any("'Orders' has no file" in p for p in report.problems)
