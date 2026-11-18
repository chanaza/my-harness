"""Small text helpers shared across the engine."""

from __future__ import annotations

import re
import unicodedata


def slugify(text: str) -> str:
    """Lower-case, dash-separated, safe for ids and file names. Letters of every language are
    kept (a Hebrew name stays Hebrew), so different names never collapse into one."""
    text = unicodedata.normalize("NFC", text).lower()
    slug = re.sub(r"[\W_]+", "-", text).strip("-")
    return slug or "entry"
