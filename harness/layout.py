"""The content-repository layout: the single source of truth for paths.

Every other module asks this one where things live. Renaming a folder in
the content repository means changing it here and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = "harness.config.yaml"


@dataclass(frozen=True)
class Area:
    """A top-level area of the content repository."""

    path: str
    purpose: str


# Ordered as they appear in the content repository's README.
AREAS: tuple[Area, ...] = (
    Area("core/profile", "Who you are: background, preferences, style."),
    Area("core/instructions", "How agents should behave. Changes need your approval."),
    Area("core/skills", "Reusable skills, one folder per skill with a SKILL.md."),
    Area("core/agents", "Agent definitions, one YAML file per agent."),
    Area("core/workflows", "Multi-step workflows, one YAML file per workflow."),
    Area("memory", "What is known: facts, decisions, project state. Updated by agents; "
         "every entry records which tool and session it came from."),
    Area("apps", "Specs of apps built inside tools: app.yaml, table schemas, workflows."),
    Area("assets", "Reference files (examples, decks, designs), one folder per asset."),
    Area("sessions", "Per-conversation records: sessions/<tool>/<session-id>/."),
    Area("inbox", "Raw drops from tools that cannot write here directly."),
)

CONNECTIONS_FILE = "core/connections.yaml"


def content_path(root: Path, area: str) -> Path:
    """Return the absolute path of an area inside a content repository."""
    return root / area
