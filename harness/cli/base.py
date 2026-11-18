"""The ``Command`` interface every CLI command implements."""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod


class Command(ABC):
    """One `harness <name>` command.

    Subclasses declare ``name`` and ``help``, add their arguments in
    ``configure`` and do their work in ``run`` (returning an exit code).
    Commands with sub-commands (e.g. `harness config set`) list them in
    ``subcommands``.
    """

    name: str = ""
    help: str = ""
    subcommands: tuple[type[Command], ...] = ()

    def configure(self, parser: argparse.ArgumentParser) -> None:  # noqa: B027 - optional hook
        """Add this command's arguments (optional: commands without arguments skip it)."""

    @abstractmethod
    def run(self, args: argparse.Namespace) -> int:
        """Execute the command; return the process exit code."""

    def attach(self, subparsers: argparse._SubParsersAction) -> None:
        """Register this command (and its sub-commands) on an argparse tree."""
        parser = subparsers.add_parser(self.name, help=self.help, description=self.help)
        self.configure(parser)
        if self.subcommands:
            nested = parser.add_subparsers(dest=f"{self.name}_command", required=True)
            for sub in self.subcommands:
                sub().attach(nested)
        else:
            parser.set_defaults(handler=self)


class ErrorExit(Exception):
    """Raised by a command to stop with a message and a non-zero exit code."""
