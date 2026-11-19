"""``ConnectorAdapter``: a tool that saves itself through the harness connector (engine).

For tools the harness cannot read from outside (no files on a computer, no API): the tool's
own model sends what it built and its conversations through the connector, following the
instructions the connector serves (one engine template, ``templates/connector/save.md``, plus
the reading instructions). A subclass only says what is particular to its tool, in
``TOOL_NOTES``, and how the user puts the one-line instruction into the tool.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

from ..harvest import Captured, HarvestReport
from ..profiles import ProfileRegistry
from ..repo import ContentRepo
from .base import AccountBoundAdapter, HarnessNotConfigured

#: connector.transcript -> what the tool sends after every reply (said to its model).
AFTER_EVERY_REPLY = {
    "exchange": ("after EVERY reply you give, as its last step, send that exchange (exchange mode); "
                 "and every ${EVERY} replies, a summary of the whole conversation (save mode)"),
    "off": "every ${EVERY} replies, a summary of the whole conversation (save mode)",
}


class ConnectorAdapter(AccountBoundAdapter):
    environment = "cloud"
    capture_modes = ("push",)
    capture_reason = ("the tool's own model sends through the harness connector; the inbox is "
                      "processed in GitHub (Actions)")
    offered_everywhere = True
    #: What is particular to this tool, filled into the engine's save instructions.
    TOOL_NOTES: dict[str, str] = {}

    # --- what the connector serves ------------------------------------------------------------

    def connector_instructions(self, repo: ContentRepo) -> str:
        from .. import __version__
        from ..digest import summary_request
        from ..inbox import saved_apps
        config = repo.config
        saved = "\n".join(f"- {a['url']} version {a['version']}" for a in saved_apps(repo).values()
                          if a.get("url") and a.get("version")) or "- (none yet)"
        notes = {"TOOL_TITLE": self.tool, "NOT_HERE": "", "SETUP": "Nothing to set up.",
                 "WHERE_SKILLS": "", "APPS_NAME": "apps", "PROJECT_NAME": "project",
                 "SURFACE": self.tool, "SURFACES": self.tool,
                 "APPS_HOW": "Copy each app's files exactly, with this tool's own means."} | self.TOOL_NOTES
        templates = resources.files("harness.templates").joinpath("connector")
        text = templates.joinpath("save.md").read_text("utf-8") + "\n\n---\n\n" + \
            templates.joinpath("reader.md").read_text("utf-8")
        return Template(text).safe_substitute(
            notes, VERSION=__version__, TOOL=self.tool, SAVED_APPS=saved,
            AFTER_EVERY_REPLY=Template(AFTER_EVERY_REPLY[config.connector.transcript]).substitute(
                EVERY=config.connector.summary_every_replies),
            SUMMARY_REQUEST=summary_request(config.checkpoints.summary_max_words, config.working_language))

    def instruction_line(self, profile: str) -> str:
        """The one line the user puts into the tool (its custom instructions)."""
        return (f"Before anything about my work, call the harness connector's harness_instructions "
                f"with tool: {self.tool} and profile: {profile}, and follow what it returns.")

    # --- nothing is pulled: the tool sends -------------------------------------------------------

    def harvest(self, exclude: list[str] | None = None) -> list[Captured]:
        return []

    def run_harvest(self, session: str | None = None) -> HarvestReport:
        return HarvestReport()   # what the tool sent is saved by `harness inbox`

    def preview(self, exclude: list[str]) -> list[str]:
        return []

    def accounts(self) -> list:
        return []

    def is_connected(self) -> bool:
        return bool(self.bindings())

    def install(self, profile_id: str, label: str, repo_root: Path | None = None, hooks: bool = True,
                environment: str | None = None, account_key: str | None = None) -> list[str]:
        if repo_root:
            self.local.save_settings(content_repo=str(Path(repo_root).resolve()))
        if not account_key:
            raise HarnessNotConfigured(f"Which {self.tool} account? (its e-mail address)")
        profile = ProfileRegistry(self.repo()).add(self.tool, label, profile_id=profile_id,
                                                   environment=environment or self.environment)
        self.bind(account_key, profile.id)
        return [f"{self.tool} {account_key} -> {profile.id}"]

    def after_setup(self, profiles: list[str]) -> list[str]:
        steps = ["Once for all tools: the harness connector (docs/connector.md)."]
        for email, profile in self.bindings().items():
            if profile in profiles:
                steps += self.setup_steps(email, profile)
        return steps

    def setup_steps(self, account: str, profile: str) -> list[str]:
        return [f"In {self.tool} ({account}): add the harness connector as an MCP server, and add to "
                f"its custom instructions: {self.instruction_line(profile)}"]

    def handle_hook(self, event: dict[str, Any], deferred: bool = False) -> dict[str, Any] | None:
        return None
