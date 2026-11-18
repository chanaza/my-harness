"""Commands that create, check and configure a content repository."""

from __future__ import annotations

import argparse
from pathlib import Path

from ... import yaml_io
from ...config import ConfigError
from ...local import LocalHome
from ...repo import ContentRepo
from ...scaffold import SUPPORTED_TOOLS, InitOptions, Scaffolder, ScaffoldError
from ...validation import RepoValidator
from ..base import Command, ErrorExit


def repo_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", help="Content repository (default: the one configured on this "
                                       "machine, else the current folder).")


def open_repo(args: argparse.Namespace) -> ContentRepo:
    """--repo, else the machine's configured content repository, else the current folder."""
    if args.repo:
        return ContentRepo(Path(args.repo))
    return ContentRepo(LocalHome().content_repo() or Path("."))


class InitCommand(Command):
    name = "init"
    help = "Create a new content repository."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("path", help="Empty folder (an empty git clone is fine).")
        parser.add_argument("--owner", required=True, help="Display name of the harness owner.")
        parser.add_argument("--language", default="en", help="Working language code (default: en).")
        parser.add_argument("--tools", nargs="+", default=list(SUPPORTED_TOOLS),
                            help="Tool ids in use (default: all supported).")
        parser.add_argument("--transcripts-path", help="Folder for transcripts (e.g. a OneDrive folder).")
        parser.add_argument("--live-logs-path", help="Folder for live logs.")

    def run(self, args: argparse.Namespace) -> int:
        storage = {"transcripts": args.transcripts_path, "live_logs": args.live_logs_path}
        options = InitOptions(
            owner=args.owner, language=args.language, tools=args.tools,
            storage_paths={area: path for area, path in storage.items() if path},
        )
        try:
            repo = Scaffolder().create(Path(args.path), options)
        except (ScaffoldError, ConfigError) as exc:
            raise ErrorExit(str(exc)) from None
        print(f"Created a harness content repository in {repo.root}.")
        return 0


class ValidateCommand(Command):
    name = "validate"
    help = "Check a content repository against the schemas."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        repo_argument(parser)

    def run(self, args: argparse.Namespace) -> int:
        repo = open_repo(args)
        report = RepoValidator.default(repo.layout).validate(repo)
        for problem in report.problems:
            print(f"  x {problem}")
        if report.ok:
            print(f"OK: {report.checked} files checked, no problems.")
            return 0
        print(f"{len(report.problems)} problem(s) in {report.checked} files checked.")
        return 1


class ConfigGetCommand(Command):
    name = "get"
    help = "Print a setting, e.g. `harness config get storage.transcripts.path`."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("key", help="Dotted setting name.")
        repo_argument(parser)

    def run(self, args: argparse.Namespace) -> int:
        try:
            value = open_repo(args).config_file.get(args.key)
        except ConfigError as exc:
            raise ErrorExit(str(exc)) from None
        print(yaml_io.dump(_plain(value)).strip() if isinstance(value, (dict, list)) else value)
        return 0


class ConfigSetCommand(Command):
    name = "set"
    help = "Change a setting; the file is validated before it is written."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("key", help="Dotted setting name, e.g. capture.live_log_threshold_percent.")
        parser.add_argument("value", nargs="+", help="New value. Several values make a list.")
        parser.add_argument("--string", action="store_true",
                            help="Keep the value as text (no conversion to number/true/false).")
        repo_argument(parser)

    def run(self, args: argparse.Namespace) -> int:
        values = [v if args.string else self._parse(v) for v in args.value]
        value = values[0] if len(values) == 1 else values
        try:
            open_repo(args).config_file.update({args.key: value})
        except ConfigError as exc:
            raise ErrorExit(str(exc)) from None
        print(f"{args.key} = {value}")
        return 0

    @staticmethod
    def _parse(text: str) -> object:
        """'80' -> 80, 'true' -> True; anything else (paths included) stays text."""
        try:
            parsed = yaml_io.load(text)
        except yaml_io.YAMLError:
            return text
        return parsed if isinstance(parsed, (bool, int, float)) else text


class ConfigCommand(Command):
    name = "config"
    help = "Read or change harness.config.yaml."
    subcommands = (ConfigGetCommand, ConfigSetCommand)

    def run(self, args: argparse.Namespace) -> int:  # pragma: no cover - dispatch only
        raise NotImplementedError


def _plain(value: object) -> object:
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class UpgradeCommand(Command):
    name = "upgrade"
    help = "Bring the configuration up to the current engine: add new settings, keep your values."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        repo_argument(parser)

    def run(self, args: argparse.Namespace) -> int:
        repo = open_repo(args)
        try:
            added = repo.config_file.upgrade()
        except ConfigError as exc:
            raise ErrorExit(str(exc)) from None
        created = Scaffolder(repo.layout).ensure_structure(repo)
        print(f"Added settings: {', '.join(added) or 'none'}")
        print(f"Added files/folders: {', '.join(str(p.relative_to(repo.root)) for p in created) or 'none'}")
        return 0
