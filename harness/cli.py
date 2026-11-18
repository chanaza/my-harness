"""Command-line interface: `harness <command>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .scaffold import DEFAULT_TOOLS, InitOptions, ScaffoldError, init_repo
from .validate import validate_repo


def _cmd_init(args: argparse.Namespace) -> int:
    options = InitOptions(owner=args.owner, language=args.language,
                          tools=args.tools or list(DEFAULT_TOOLS))
    if args.transcripts_path:
        options.transcripts_path = args.transcripts_path
    if args.live_logs_path:
        options.live_logs_path = args.live_logs_path
    try:
        written = init_repo(Path(args.path), options)
    except ScaffoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Created a harness content repository in {args.path} ({len(written)} files).")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    report = validate_repo(Path(args.path))
    for problem in report.problems:
        print(f"  x {problem}")
    if report.ok:
        print(f"OK: {report.checked} files checked, no problems.")
        return 0
    print(f"{len(report.problems)} problem(s) in {report.checked} files checked.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="Manage a portable AI harness.")
    parser.add_argument("--version", action="version", version=f"my-harness {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Create a new content repository.")
    p.add_argument("path", help="Empty folder (an empty git clone is fine).")
    p.add_argument("--owner", required=True, help="Display name of the harness owner.")
    p.add_argument("--language", default="en", help="Working language code (default: en).")
    p.add_argument("--tools", nargs="+", help="Tool ids in use (default: all supported).")
    p.add_argument("--transcripts-path", help="Folder for transcripts (e.g. a Google Drive folder).")
    p.add_argument("--live-logs-path", help="Folder for live logs.")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("validate", help="Check a content repository against the schemas.")
    p.add_argument("path", nargs="?", default=".", help="Content repository (default: current folder).")
    p.set_defaults(func=_cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
