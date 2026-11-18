"""``RepoValidator``: runs a configurable list of checks over a content repository."""

from __future__ import annotations

from collections.abc import Sequence

from ..config import ConfigError
from ..layout import RepoLayout
from ..repo import ContentRepo
from .checks import AssetSizeCheck, Check, ProfileReferenceCheck, SchemaCheck
from .readers import FrontmatterReader
from .report import Report


class RepoValidator:
    def __init__(self, checks: Sequence[Check]) -> None:
        self.checks = list(checks)

    @classmethod
    def default(cls, layout: RepoLayout) -> RepoValidator:
        """The standard checks: which files follow which schema, plus asset sizes."""
        frontmatter = FrontmatterReader()
        return cls([
            SchemaCheck(layout.connections_file, "connections"),
            SchemaCheck(layout.profiles_file, "profiles"),
            SchemaCheck("core/instructions/**/*.md", "instruction", frontmatter),
            SchemaCheck("core/skills/*/SKILL.md", "skill", frontmatter),
            SchemaCheck("core/agents/*.yaml", "agent"),
            SchemaCheck("core/workflows/*.yaml", "workflow"),
            SchemaCheck("core/plugins/*/plugin.yaml", "plugin"),
            SchemaCheck("memory/**/*.md", "memory", frontmatter),
            SchemaCheck("apps/*/app.yaml", "app"),
            SchemaCheck("apps/*/schema/*.yaml", "table"),
            SchemaCheck("apps/*/workflows/*.yaml", "workflow"),
            SchemaCheck("apps/*/data.yaml", "data_pointer"),
            SchemaCheck(f"{layout.assets_dir}/*/asset.yaml", "asset"),
            SchemaCheck("sessions/*/*/meta.yaml", "session_meta"),
            SchemaCheck("sessions/*/*/summary.md", "summary", frontmatter),
            AssetSizeCheck(),
            ProfileReferenceCheck(),
        ])

    def validate(self, repo: ContentRepo) -> Report:
        report = Report()
        try:
            repo.config_file.load()  # every other check depends on a valid configuration
        except ConfigError as exc:
            report.add(repo.layout.config_file, str(exc))
            return report
        report.checked += 1
        for check in self.checks:
            check.run(repo, report)
        return report
