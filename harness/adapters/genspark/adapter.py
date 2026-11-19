"""``GensparkAdapter``: only what is particular to Genspark; everything else is the engine's
``ConnectorAdapter``. Genspark has Skills (uploaded as a file) and custom instructions
(Settings > Personalization, and per Hub); its Hubs are what the harness calls projects,
its GenTeam agents are agents."""

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
        "SCOPE": "this Genspark account",
        "SETUP": ("Nothing to set up: what you build is saved when it is built (built mode); describe "
                  "mode runs when the user asks, and once a day if this account can schedule a task."),
        "PROJECT_NAME": "Hub (a Genspark project)",
        "APPS_NAME": "pages, slides, sheets and other things the user made",
        "APPS_HOW": ("Copy each one's content exactly as text (e.g. a page's HTML as `index.html`); a "
                     "file you cannot read as text: list it with `not_readable` instead."),
        "SURFACE": "genspark",
        "SURFACES": "genspark",
    }

    SKILLS_PAGE = "https://www.genspark.ai/"

    ALWAYS_ON = "Settings > Personalization"

    def setup_steps(self, account: str, profile: str) -> list[str]:
        target = self.deliver_skill(account=account)
        return [f"In Genspark ({account}): add an MCP server (Streamable HTTP) with your connector's "
                f"address; then Skills > + New Skill > Upload: {target}",
                f"Required, once: add to {self.ALWAYS_ON}: {self.always_on_line()}"]
