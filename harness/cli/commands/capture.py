"""Commands that connect tools and capture from them."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from ...adapters import adapters
from ...adapters.claude_code import HarnessNotConfigured
from ...checkpoints import CheckpointRecorder
from ...git_sync import GitSync
from ...local import LocalHome
from ...memory import KINDS, MemoryStore
from ...profiles import ProfileError, ProfileRegistry
from ...provenance import Origin
from ...sessions import SessionRecord
from ..base import Command, ErrorExit
from .repository import open_repo, repo_argument


def _tool_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("tool", choices=adapters.names(), help="Tool to work with.")


def _read_stdin_text() -> str:
    text = sys.stdin.read().strip()
    if not text:
        raise ErrorExit("Expected the text on standard input (e.g. a <<'EOF' heredoc).")
    return text


# --- profiles ---------------------------------------------------------------------

class ProfileAddCommand(Command):
    name = "add"
    help = "Register a tool account, e.g. `harness profile add claude-code personal`."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("tool", help="Tool id, e.g. claude-code, chatgpt.")
        parser.add_argument("label", help="Which account, in your words (no e-mail).")
        parser.add_argument("--id", help="Profile id (default: <tool>-<label>).")
        parser.add_argument("--description")
        repo_argument(parser)

    def run(self, args: argparse.Namespace) -> int:
        try:
            profile = ProfileRegistry(open_repo(args)).add(args.tool, args.label, args.description, args.id)
        except ProfileError as exc:
            raise ErrorExit(str(exc)) from None
        print(f"Profile: {profile.id}")
        return 0


class ProfileListCommand(Command):
    name = "list"
    help = "List registered profiles."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        repo_argument(parser)

    def run(self, args: argparse.Namespace) -> int:
        for profile in ProfileRegistry(open_repo(args)).all():
            print(f"{profile.id:30} {profile.tool:14} {profile.label}")
        return 0


class ProfileCommand(Command):
    name = "profile"
    help = "Manage profiles (a tool + an account)."
    subcommands = (ProfileAddCommand, ProfileListCommand)

    def run(self, args: argparse.Namespace) -> int:  # pragma: no cover - dispatch only
        raise NotImplementedError


# --- tools --------------------------------------------------------------------------

class InstallCommand(Command):
    name = "install"
    help = "Connect a tool on this machine to the harness (hooks, skill, profile)."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        _tool_argument(parser)
        parser.add_argument("--profile", required=True, help="Profile id, e.g. claude-code-personal.")
        parser.add_argument("--label", help="Account label if the profile is new (default: from the id).")
        parser.add_argument("--repo", help="Content repository on this machine (remembered).")
        parser.add_argument("--no-hooks", action="store_true",
                            help="Only bind the profile (for manual `harness harvest`), no hooks or skill.")

    def run(self, args: argparse.Namespace) -> int:
        adapter = adapters.create(args.tool)
        label = args.label or args.profile.removeprefix(f"{args.tool}-")
        try:
            done = adapter.install(args.profile, label, Path(args.repo) if args.repo else None,
                                   hooks=not args.no_hooks)
        except (HarnessNotConfigured, ProfileError) as exc:
            raise ErrorExit(str(exc)) from None
        for line in done:
            print(f"  + {line}")
        return 0


class HarvestCommand(Command):
    name = "harvest"
    help = "Capture what was built in a tool (skills, agents, instructions, memory, connections)."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        _tool_argument(parser)
        parser.add_argument("--project", help="Also harvest this project folder's settings.")
        parser.add_argument("--dry-run", action="store_true", help="List what would be captured.")

    def run(self, args: argparse.Namespace) -> int:
        adapter = adapters.create(args.tool)
        if args.project:
            adapter.locations = adapter.locations.for_project(Path(args.project))
        try:
            if args.dry_run:
                repo = adapter.repo()
                for item in adapter.harvest(repo.config.harvest_exclude):
                    print(f"  {item.kind.value:12} {item.scope:24} {item.name}")
                return 0
            report = adapter.run_harvest()
            repo = adapter.repo()
        except HarnessNotConfigured as exc:
            raise ErrorExit(str(exc)) from None
        for problem in report.errors:
            print(f"  x {problem}")
        for path in report.conflicts:
            print(f"  ! conflict: {path.relative_to(repo.root)}")
        GitSync(repo.root, repo.config.git).sync(f"{adapter.profile_id()}: harvest ({report.summary()})",
                                                 push=True)
        print(f"Harvest: {report.summary()}")
        return 1 if report.errors else 0


class HookCommand(Command):
    name = "hook"
    help = "Entry point for tool hooks (reads the event as JSON on stdin). Never fails the tool."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        _tool_argument(parser)

    def run(self, args: argparse.Namespace) -> int:
        local = LocalHome()
        try:
            event = json.loads(sys.stdin.read() or "{}")
            response = adapters.create(args.tool, local).handle_hook(event)
            if response:
                print(json.dumps(response))
        except HarnessNotConfigured as exc:
            local.log(f"hook {args.tool}: not configured: {exc}")
        except Exception:  # capture must never break the tool
            local.log(f"hook {args.tool} failed:\n{traceback.format_exc()}")
        return 0


# --- content written by models ------------------------------------------------------------

def _profile_and_repo_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True, help="Profile id the content comes from.")
    parser.add_argument("--session", help="Session id (default: the profile's current session).")
    repo_argument(parser)


class SessionCheckpointCommand(Command):
    name = "checkpoint"
    help = "Replace the rolling session summary with the text on stdin."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        _profile_and_repo_arguments(parser)
        parser.add_argument("--reason", default="manual", help="Why this checkpoint was written.")

    def run(self, args: argparse.Namespace) -> int:
        local, repo = LocalHome(), open_repo(args)
        if args.session:
            recorder = CheckpointRecorder(local, repo, SessionRecord(repo, args.profile, args.session))
        else:
            recorder = CheckpointRecorder.current(local, repo, args.profile)
            if recorder is None:
                raise ErrorExit(f"No current session for {args.profile}; pass --session.")
        number = recorder.write(_read_stdin_text(), args.reason)
        GitSync(repo.root, repo.config.git).sync(
            f"{args.profile}: checkpoint {number} of {recorder.session.id}", push=True)
        print(f"Checkpoint {number} saved for {recorder.session.id}.")
        return 0


class SessionCommand(Command):
    name = "session"
    help = "Session records."
    subcommands = (SessionCheckpointCommand,)

    def run(self, args: argparse.Namespace) -> int:  # pragma: no cover - dispatch only
        raise NotImplementedError


class MemoryAddCommand(Command):
    name = "add"
    help = "Add or update a memory entry with the text on stdin."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        _profile_and_repo_arguments(parser)
        parser.add_argument("--id", required=True, help="Short slug naming the memory.")
        parser.add_argument("--kind", choices=KINDS, default="fact")
        parser.add_argument("--subject", help="What it is about (helps spot conflicts).")

    def run(self, args: argparse.Namespace) -> int:
        local, repo = LocalHome(), open_repo(args)
        session = args.session
        if not session:
            recorder = CheckpointRecorder.current(local, repo, args.profile)
            session = recorder.session.native_id if recorder else None
        result = MemoryStore(repo).put(args.id, _read_stdin_text(), Origin.now(args.profile, session),
                                       args.kind, args.subject)
        GitSync(repo.root, repo.config.git).sync(f"{args.profile}: memory {result.action} {args.id}")
        print(f"Memory {result.action}: {result.path.relative_to(repo.root)}")
        if result.action == "conflict":
            print("Another profile recorded something different; both versions are kept as 'disputed'.")
        return 0


class MemoryCommand(Command):
    name = "memory"
    help = "Memory entries."
    subcommands = (MemoryAddCommand,)

    def run(self, args: argparse.Namespace) -> int:  # pragma: no cover - dispatch only
        raise NotImplementedError
