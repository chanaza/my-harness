"""Small text helpers shared across the engine."""

from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Lower-case, dash-separated, safe for ids and file names."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "entry"
