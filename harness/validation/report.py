from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Report:
    """The outcome of validating a content repository."""

    checked: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def add(self, where: str, message: str) -> None:
        self.problems.append(f"{where}: {message}")
