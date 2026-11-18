"""``StructuredMerge``: merge the harness's YAML files by content, not by text lines.

Git calls this (as a merge driver) when two machines changed the same YAML file.
Changes to different keys are combined; lists are united (items removed on one side
stay removed); lists of records with an ``id`` (profiles, connections) are merged
record by record. Only the same value changed differently on both sides is a real
conflict; then the incoming change wins and the other is kept in Git history.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import yaml_io

MISSING: Any = object()


def merge_values(base: Any, ours: Any, theirs: Any) -> Any:
    """Three-way merge of plain YAML data. ``MISSING`` marks an absent key."""
    if _same(ours, theirs):
        return ours
    if _same(base, ours):
        return theirs
    if _same(base, theirs):
        return ours
    if all(isinstance(v, dict) for v in (ours, theirs)):
        return _merge_maps(base if isinstance(base, dict) else {}, ours, theirs)
    if all(isinstance(v, list) for v in (ours, theirs)):
        return _merge_lists(base if isinstance(base, list) else [], ours, theirs)
    return theirs  # both changed the same value: the incoming change wins


def _merge_maps(base: dict, ours: dict, theirs: dict) -> dict:
    merged: dict = {}
    for key in list(ours) + [k for k in theirs if k not in ours]:
        value = merge_values(base.get(key, MISSING), ours.get(key, MISSING), theirs.get(key, MISSING))
        if value is not MISSING:
            merged[key] = value
    return merged


def _merge_lists(base: list, ours: list, theirs: list) -> list:
    if all(isinstance(i, dict) and "id" in i for i in ours + theirs):
        by_id = {i["id"]: i for i in base if isinstance(i, dict)}
        mine, incoming = {i["id"]: i for i in ours}, {i["id"]: i for i in theirs}
        merged = merge_values(by_id, mine, incoming)
        order = [i["id"] for i in ours] + [i["id"] for i in theirs if i["id"] not in mine]
        return [merged[k] for k in order if k in merged]
    removed = [i for i in base if i not in ours or i not in theirs]
    united = ours + [i for i in theirs if i not in ours]
    return [i for i in united if i not in removed]


def _same(a: Any, b: Any) -> bool:
    return a is b or (a is not MISSING and b is not MISSING and a == b)


class StructuredMerge:
    """Merges one YAML file the way Git's merge drivers expect (result written to ``ours``)."""

    CONFIG = "harness.config.yaml"

    def merge_file(self, base: Path, ours: Path, theirs: Path, name: str = "") -> bool:
        try:
            data = [yaml_io.load(p.read_text("utf-8")) if p.is_file() and p.stat().st_size else None
                    for p in (base, ours, theirs)]
        except yaml_io.YAMLError:
            return False  # not YAML we can read: leave it to Git (a real conflict)
        merged = merge_values(data[0] if data[0] is not None else MISSING,
                              data[1] if data[1] is not None else MISSING,
                              data[2] if data[2] is not None else MISSING)
        header = _leading_comments(ours.read_text("utf-8") if ours.is_file() else "")
        ours.write_text(header + yaml_io.dump(merged), encoding="utf-8")
        if Path(name).name == self.CONFIG:
            self._restore_config_layout(ours)
        return True

    @staticmethod
    def _restore_config_layout(path: Path) -> None:
        """The settings file keeps its explanatory comments: re-render it from the template."""
        from .config import ConfigError, ConfigFile
        try:
            ConfigFile(path).upgrade()
        except ConfigError:
            pass  # still valid YAML with every value; comments come back on the next upgrade


def _leading_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines) + "\n" if lines else ""
