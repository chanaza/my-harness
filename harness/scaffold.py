"""`harness init`: create a new content repository from the bundled template.

The content repository is only ever created and changed through the engine,
so everything it contains on day one comes from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from string import Template

from . import __version__
from .layout import AREAS

DEFAULT_TOOLS: tuple[str, ...] = (
    "claude-code", "claude", "chatgpt", "cursor", "genspark", "base44", "monday",
)

# Files whose ${placeholders} are filled in at init time.
_TEMPLATED = {"harness.config.yaml"}


class ScaffoldError(Exception):
    """The target cannot be initialised."""


@dataclass
class InitOptions:
    owner: str
    language: str = "en"
    transcripts_path: str = "~/Google Drive/My Drive/harness-storage/transcripts"
    live_logs_path: str = "~/Google Drive/My Drive/harness-storage/live-logs"
    tools: list[str] = field(default_factory=lambda: list(DEFAULT_TOOLS))


def init_repo(target: Path, options: InitOptions) -> list[Path]:
    """Create the content-repository layout in ``target``. Returns files written."""
    target = Path(target)
    if target.exists() and any(p.name != ".git" for p in target.iterdir()):
        raise ScaffoldError(f"{target} is not empty. `harness init` only runs on an empty folder.")
    target.mkdir(parents=True, exist_ok=True)

    values = {
        "owner": options.owner,
        "language": options.language,
        "transcripts_path": options.transcripts_path,
        "live_logs_path": options.live_logs_path,
        "tools": "\n".join(f"  - {t}" for t in options.tools),
    }
    written = _copy_template(resources.files("harness.templates").joinpath("content_repo"), target, values)

    for area in AREAS:
        folder = target / area.path
        folder.mkdir(parents=True, exist_ok=True)
        if not any(folder.iterdir()):
            keep = folder / ".gitkeep"
            keep.touch()
            written.append(keep)

    readme = target / "README.md"
    readme.write_text(_render_readme(options.owner), encoding="utf-8")
    written.append(readme)
    return sorted(written)


def _copy_template(source: Traversable, target: Path, values: dict[str, str]) -> list[Path]:
    written: list[Path] = []
    for entry in source.iterdir():
        dest = target / entry.name
        if entry.is_dir():
            dest.mkdir(exist_ok=True)
            written += _copy_template(entry, dest, values)
            continue
        text = entry.read_text("utf-8")
        if entry.name in _TEMPLATED:
            text = Template(text).substitute(values)
        dest.write_text(text, encoding="utf-8")
        written.append(dest)
    return written


def _render_readme(owner: str) -> str:
    rows = "\n".join(f"| `{a.path}/` | {a.purpose} |" for a in AREAS)
    return f"""# {owner}'s harness

This repository holds a personal AI harness: instructions, skills, agents,
memory, app specs and session records, kept outside any single AI tool so
they can move between tools.

It is **managed by [my-harness](https://github.com/chanaza/my-harness)**
(engine v{__version__}). Do not restructure it by hand: create and change
content through the engine and its tool adapters, then run
`harness validate` to check it.

| Folder | Purpose |
|---|---|
{rows}

Transcripts and live logs are not stored here. Their location is set in
`harness.config.yaml` under `storage`.
"""
