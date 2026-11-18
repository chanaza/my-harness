"""``HarnessCLI``: assembles commands into the `harness` program."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .. import __version__
from .base import Command, ErrorExit
from .commands import DEFAULT_COMMANDS


class HarnessCLI:
    def __init__(self, commands: Sequence[type[Command]] = DEFAULT_COMMANDS) -> None:
        self.commands = list(commands)

    def build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="harness", description="Manage a portable AI harness.")
        parser.add_argument("--version", action="version", version=f"my-harness {__version__}")
        subparsers = parser.add_subparsers(dest="command", required=True)
        for command in self.commands:
            command().attach(subparsers)
        return parser

    def main(self, argv: Sequence[str] | None = None) -> int:
        args = self.build_parser().parse_args(argv)
        try:
            return args.handler.run(args)
        except ErrorExit as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1


def main(argv: Sequence[str] | None = None) -> int:
    return HarnessCLI().main(argv)
