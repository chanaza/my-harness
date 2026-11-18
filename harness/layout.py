"""The content-repository layout: the single source of truth for paths.

Every other component receives a ``RepoLayout`` instead of hard-coding
folder names. Renaming or adding an area is a change here only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Area:
    """A top-level area (folder) of the content repository."""

    path: str
    purpose: str


@dataclass(frozen=True)
class RepoLayout:
    """Where everything lives inside a content repository."""

    areas: tuple[Area, ...]
    config_file: str = "harness.config.yaml"
    connections_file: str = "core/connections.yaml"
    assets_dir: str = "assets"

    def area(self, path: str) -> Area:
        for area in self.areas:
            if area.path == path:
                return area
        raise KeyError(f"No area {path!r} in this layout")


DEFAULT_LAYOUT = RepoLayout(
    areas=(
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
)
