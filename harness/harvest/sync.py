"""``HarvestSync``: writes captured items, skipping what has not changed."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..local import StateFile
from ..provenance import Origin
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
        return any(self.counts[k] for k in ("created", "updated", "conflict"))

    def summary(self) -> str:
        parts = [f"{n} {action}" for action, n in sorted(self.counts.items()) if n]
        return ", ".join(parts) or "nothing captured"


class HarvestSync:
    """Writes items through per-kind writers.

    Fingerprints of what was last written are kept in a local state file,
    so an unchanged item costs one hash comparison and no disk writes.
    """

    STATE_KEY = "fingerprints"

    def __init__(self, repo: ContentRepo, state: StateFile,
                 writers: Sequence[type[ItemWriter]] = DEFAULT_WRITERS) -> None:
        self.repo = repo
        self.state = state
        self.writers: dict[Kind, ItemWriter] = {w.kind: w(repo) for w in writers}

    def run(self, items: Iterable[Captured], origin: Origin) -> HarvestReport:
        report = HarvestReport()
        seen: dict[str, str] = dict(self.state.get(self.STATE_KEY, {}))
        for item in items:
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
            seen[item.key] = fingerprint
        self.state.set(self.STATE_KEY, seen)
        self.state.save()
        return report
