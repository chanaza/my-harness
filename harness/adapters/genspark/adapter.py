"""``GensparkAdapter``: only what is particular to Genspark; everything else is the engine's
``ConnectorAdapter``. Genspark keeps its custom instructions in Settings > Personalization
(and per Hub); its Hubs are what the harness calls projects, its GenTeam agents are agents."""

from __future__ import annotations

from ..base import adapters
from ..connector import ConnectorAdapter


@adapters.register
class GensparkAdapter(ConnectorAdapter):
    tool = "genspark"
    account_question = ("The e-mail address of your Genspark account (several: separate them with "
                        "commas). If you don't use Genspark, just press Enter")
    TOOL_NOTES = {
        "TOOL_TITLE": "Genspark",
        "SETUP": ("Nothing to set up: describe mode runs when the user asks (\"describe my Genspark "
                  "to the harness\"), and once a day if this account can schedule a task."),
        "PROJECT_NAME": "Hub (a Genspark project)",
        "APPS_NAME": "pages, slides, sheets and other things the user made",
        "APPS_HOW": ("Copy each one's content exactly as text (e.g. a page's HTML as `index.html`); a "
                     "file you cannot read as text: list it with `not_readable` instead."),
        "SURFACE": "genspark",
        "SURFACES": "genspark",
    }

    def setup_steps(self, account: str, profile: str) -> list[str]:
        return [f"In Genspark ({account}): add an MCP server (Streamable HTTP) with your connector's "
                f"address, then in Settings > Personalization add: {self.instruction_line(profile)}"]
