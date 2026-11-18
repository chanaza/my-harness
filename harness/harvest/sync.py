"""``HarvestSync``: writes captured items, skipping what has not changed."""

from __future__ import annotations

import shutil
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..documents import MarkdownDocument
from ..local import StateFile
from ..provenance import Origin, Provenance
from ..repo import ContentRepo
from .item import Captured, Kind
from .writers import DEFAULT_WRITERS, ItemWriter


@dataclass
class HarvestReport:
    counts: Counter = field(default_factory=Counter)
    conflicts: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(self.counts[k] for k in ("created", "updated", "conflict", "removed"))

    def summary(self) -> str:
        parts = [f"{n} {action}" for action, n in sorted(self.counts.items()) if n]
        return ", ".join(parts) or "nothing captured"


class HarvestSync:
    """Writes items through per-kind writers.

    Fingerprints of what was last written are kept in a local state file,
    so an unchanged item costs one hash comparison and no disk writes.
    """

    STATE_KEY = "fingerprints"
    WRITTEN_KEY = "written"
    #: Kinds whose written path can be removed on its own (connections share one file).
    PRUNABLE = (Kind.SKILL, Kind.AGENT, Kind.INSTRUCTION, Kind.NATIVE, Kind.MEMORY)
    #: Kinds that mirror the tool: when the tool no longer has the item, neither does the harness.
    #: (Knowledge such as skills and memory is never deleted just because the tool dropped it.)
    MIRRORED = (Kind.NATIVE,)

    def __init__(self, repo: ContentRepo, state: StateFile,
                 writers: Sequence[type[ItemWriter]] = DEFAULT_WRITERS) -> None:
        self.repo = repo
        self.state = state
        self.writers: dict[Kind, ItemWriter] = {w.kind: w(repo) for w in writers}

    def run(self, items: Iterable[Captured], origin: Origin) -> HarvestReport:
        report = HarvestReport()
        seen: dict[str, str] = dict(self.state.get(self.STATE_KEY, {}))
        written: dict[str, str] = dict(self.state.get(self.WRITTEN_KEY, {}))
        items_list = list(items)
        for item in items_list:
            fingerprint = item.fingerprint
            if seen.get(item.key) == fingerprint:
                report.counts["unchanged"] += 1
                continue
            writer = self.writers.get(item.kind)
            if writer is None:
                report.errors.append(f"{item.key}: no writer for kind {item.kind.value}")
                continue
            try:
                result = writer.write(item, origin)
            except Exception as exc:  # one bad item must not stop the harvest
                report.errors.append(f"{item.origin}: {exc}")
                continue
            report.counts[result.action] += 1
            if result.action == "conflict":
                report.conflicts.append(result.path)
            else:
                written[item.key] = self._owned_path(item.kind, result.path)
            seen[item.key] = fingerprint
        current = {item.key for item in items_list}
        scopes = {item.scope for item in items_list} | {"global"}
        for key in sorted(set(seen) - current):
            kind, scope, name = key.split(":", 2)
            if Kind(kind) in self.MIRRORED and scope in scopes:
                target = self.repo.path(written[key]) if key in written else \
                    self.writers[Kind(kind)].location(name, scope, origin.profile)
                if target is not None and target.exists():
                    shutil.rmtree(target) if target.is_dir() else target.unlink()
                    report.counts["removed"] += 1
                seen.pop(key, None)
                written.pop(key, None)
        self.state.set(self.STATE_KEY, seen)
        self.state.set(self.WRITTEN_KEY, written)
        self.state.save()
        return report

    def prune(self, excluded: Callable[[str, str], bool], profile: str) -> list[str]:
        """Delete what this profile harvested earlier for items that are now ``excluded``.

        Only files whose provenance still shows ``profile`` as the last editor are
        removed, so content changed since by another profile is never deleted.
        """
        written: dict[str, str] = dict(self.state.get(self.WRITTEN_KEY, {}))
        seen: dict[str, str] = dict(self.state.get(self.STATE_KEY, {}))
        removed = []
        for key in sorted(set(written) | set(seen)):
            kind, scope, name = key.split(":", 2)
            if Kind(kind) not in self.PRUNABLE or not excluded(kind, name):
                continue
            if key in written:
                target = self.repo.path(written[key])
            else:  # harvested before paths were recorded: use the writer's convention
                target = self.writers[Kind(kind)].location(name, scope, profile)
                if target is None:
                    continue
            relative = target.relative_to(self.repo.root).as_posix()
            if target.exists() and self._last_profile(target) in (None, profile):
                shutil.rmtree(target) if target.is_dir() else target.unlink()
                removed.append(relative)
            written.pop(key, None)
            seen.pop(key, None)
        self.state.set(self.WRITTEN_KEY, written)
        self.state.set(self.STATE_KEY, seen)
        self.state.save()
        return removed

    def _owned_path(self, kind: Kind, path: Path) -> str:
        """The file or folder an item occupies (a skill owns its whole folder; a native item
        its entry, as reported by the writer)."""
        target = path.parent if kind is Kind.SKILL else path
        return target.relative_to(self.repo.root).as_posix()

    @staticmethod
    def _last_profile(target: Path) -> str | None:
        main = target / "SKILL.md" if target.is_dir() else target
        if not main.is_file() or main.suffix != ".md":
            return None
        return Provenance.last_profile(MarkdownDocument.read(main).meta.get("provenance"))
