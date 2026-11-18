"""Commands that connect tools and capture from them."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter
from pathlib import Path

from ...adapters import adapters
from ...adapters.claude_code import HarnessNotConfigured
from ...checkpoints import CheckpointRecorder
from ...git_sync import GitSync
from ...local import LocalHome
from ...memory import KINDS, MemoryStore
from ...profiles import ENVIRONMENTS, ProfileError, ProfileRegistry
from ...provenance import Origin
from ...repo import ContentRepo
from ...sessions import SessionRecord
from ...setup import ConsolePrompter, DefaultsPrompter, SetupError, SetupOptions, SetupWizard
from ...storage import StorageError
from ...update import Updater
from ...validation import RepoValidator
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
        parser.add_argument("--environment", choices=ENVIRONMENTS, help="local or cloud.")
        parser.add_argument("--id", help="Profile id (default: <tool>-<label>[-<environment>]).")
        parser.add_argument("--description")
        repo_argument(parser)

    def run(self, args: argparse.Namespace) -> int:
        try:
            profile = ProfileRegistry(open_repo(args)).add(args.tool, args.label, args.description,
                                                           args.id, args.environment)
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
            print(f"{profile.id:34} {profile.tool:14} {profile.environment or '-':7} {profile.label}")
        return 0


class ProfileSetCommand(Command):
    name = "set"
    help = "Change a profile's label, environment or description."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("profile")
        parser.add_argument("--label")
        parser.add_argument("--environment", choices=ENVIRONMENTS)
        parser.add_argument("--description")
        repo_argument(parser)

    def run(self, args: argparse.Namespace) -> int:
        try:
            profile = ProfileRegistry(open_repo(args)).update(
                args.profile, label=args.label, environment=args.environment, description=args.description)
        except ProfileError as exc:
            raise ErrorExit(str(exc)) from None
        print(f"Profile {profile.id}: {profile.tool}, {profile.environment or '-'}, {profile.label}")
        return 0


class ProfileRenameCommand(Command):
    name = "rename"
    help = "Rename a profile everywhere (registry, folders, references, this machine's binding)."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("old")
        parser.add_argument("new")
        repo_argument(parser)

    def run(self, args: argparse.Namespace) -> int:
        repo = open_repo(args)
        try:
            changes = ProfileRegistry(repo).rename(args.old, args.new)
        except ProfileError as exc:
            raise ErrorExit(str(exc)) from None
        LocalHome().rename_profile(args.old, args.new)
        for change in changes:
            print(f"  ~ {change}")
        GitSync(repo.root, repo.config.git).sync(f"rename profile {args.old} -> {args.new}", push=True)
        print(f"Renamed {args.old} -> {args.new}")
        return 0


class ProfileCommand(Command):
    name = "profile"
    help = "Manage profiles (a tool + an account)."
    subcommands = (ProfileAddCommand, ProfileListCommand, ProfileSetCommand, ProfileRenameCommand)

    def run(self, args: argparse.Namespace) -> int:  # pragma: no cover - dispatch only
        raise NotImplementedError


# --- tools --------------------------------------------------------------------------

class SetupCommand(Command):
    name = "setup"
    help = "Guided setup: connect a tool on this machine to your harness (capture only, nothing is loaded)."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("tool", nargs="?", default="claude-code", choices=adapters.names())
        parser.add_argument("--repo", help="Your harness repository: a folder or a GitHub address.")
        parser.add_argument("--account", help="Which account this is, e.g. personal or work.")
        parser.add_argument("--environment", choices=ENVIRONMENTS, help="local or cloud (detected).")
        parser.add_argument("--transcripts", help="Folder for transcripts (local only).")
        parser.add_argument("--owner", help="Your name, when a new harness is created.")
        parser.add_argument("--yes", action="store_true", help="Use defaults; ask nothing (scripts).")
        parser.add_argument("--no-capture", action="store_true", help="Install only; capture later.")

    def run(self, args: argparse.Namespace) -> int:
        prompter = DefaultsPrompter() if args.yes else ConsolePrompter()
        options = SetupOptions(tool=args.tool, repo=args.repo, account=args.account,
                               environment=args.environment, transcripts=args.transcripts,
                               owner=args.owner, capture_now=False if args.no_capture else None)
        try:
            result = SetupWizard(prompter).run(options)
        except (SetupError, HarnessNotConfigured, ProfileError, StorageError) as exc:
            raise ErrorExit(str(exc)) from None
        print(f"Ready. This {args.tool} account is profile '{result.profile}', saving to {result.repo}.")
        for line in result.done:
            print(f"  + {line}")
        print("From now on conversations are saved automatically, in the background.")
        return 0


class StatusCommand(Command):
    name = "status"
    help = "Show what is connected on this machine and any recent capture problems."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--problems", type=int, default=10, help="How many recent problems to show.")

    def run(self, args: argparse.Namespace) -> int:
        local = LocalHome()
        repo_path = local.content_repo()
        print(f"Harness repository: {repo_path or 'not configured (run `harness setup`)'}")
        for tool, bindings in (local.settings().get("profiles") or {}).items():
            for folder, profile in bindings.items():
                current = local.state("profiles", profile).get("current_session") or "-"
                print(f"  {tool}: {folder} -> {profile} (latest session: {current})")
        if repo_path:
            repo = ContentRepo(repo_path)
            report = RepoValidator.default(repo.layout).validate(repo)
            print(f"Repository check: {'OK' if report.ok else f'{len(report.problems)} problem(s)'}")
            for problem in report.problems[:args.problems]:
                print(f"  x {problem}")
        problems = local.recent_problems(args.problems)
        print(f"Recent capture problems: {len(problems) or 'none'}")
        for line in problems:
            print(f"  ! {line}")
        return 0


class UpdateCommand(Command):
    name = "update"
    help = "Update everything on this machine: engine, harness repository, tool connections."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--no-engine", action="store_true", help="Keep the installed engine code.")

    def run(self, args: argparse.Namespace) -> int:
        report = Updater().update(engine=not args.no_engine)
        for step in report.steps:
            print(f"  + {step}")
        for problem in report.problems:
            print(f"  x {problem}")
        print("Up to date." if not report.problems else "Some steps failed (see above).")
        return 1 if report.problems else 0


class InstallCommand(Command):
    name = "install"
    help = "Connect a tool on this machine to the harness (hooks, skill, profile)."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        _tool_argument(parser)
        parser.add_argument("--profile", required=True, help="Profile id, e.g. claude-code-personal.")
        parser.add_argument("--label", help="Account label if the profile is new (default: from the id).")
        parser.add_argument("--repo", help="Content repository on this machine (remembered).")
        parser.add_argument("--environment", choices=ENVIRONMENTS,
                            help="Where this account's tool runs (recorded on a new profile).")
        parser.add_argument("--no-hooks", action="store_true",
                            help="Only bind the profile (for manual `harness harvest`), no hooks or skill.")

    def run(self, args: argparse.Namespace) -> int:
        adapter = adapters.create(args.tool)
        label = args.label or args.profile.removeprefix(f"{args.tool}-")
        try:
            done = adapter.install(args.profile, label, Path(args.repo) if args.repo else None,
                                   hooks=not args.no_hooks, environment=args.environment)
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
        parser.add_argument("--prune", action="store_true",
                            help="Also remove items harvested earlier that are now excluded.")

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
            for removed in adapter.prune_harvest() if args.prune else []:
                print(f"  - removed {removed}")
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


class BackfillCommand(Command):
    name = "backfill"
    help = "Import sessions from before the harness was installed (session records + transcripts)."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        _tool_argument(parser)
        parser.add_argument("--since-days", type=int, help="Only sessions active in the last N days.")
        parser.add_argument("--dry-run", action="store_true", help="List the sessions without importing.")

    def run(self, args: argparse.Namespace) -> int:
        adapter = adapters.create(args.tool)
        try:
            entries = adapter.backfill(args.since_days, args.dry_run)
            repo = adapter.repo()
        except (HarnessNotConfigured, StorageError) as exc:
            raise ErrorExit(str(exc)) from None
        for e in entries:
            print(f"  {e.action:9} {e.started_at or '?':20} {e.user_messages:4} msgs  "
                  f"{e.project or '-':20} {e.session}")
        if not args.dry_run:
            counts = Counter(e.action for e in entries)
            summary = ", ".join(f"{n} {a}" for a, n in sorted(counts.items())) or "nothing found"
            GitSync(repo.root, repo.config.git).sync(f"{adapter.profile_id()}: backfill ({summary})",
                                                     push=True)
            print(f"Backfill: {summary}")
        return 0


class HookCommand(Command):
    name = "hook"
    help = "Entry point for tool hooks (reads the event as JSON on stdin). Never fails the tool."

    def configure(self, parser: argparse.ArgumentParser) -> None:
        _tool_argument(parser)
        parser.add_argument("--deferred", action="store_true", help=argparse.SUPPRESS)

    def run(self, args: argparse.Namespace) -> int:
        local = LocalHome()
        try:
            event = json.loads(sys.stdin.read() or "{}")
            response = adapters.create(args.tool, local).handle_hook(event, deferred=args.deferred)
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
        parser.add_argument("--quiet", action="store_true", help="Print nothing (used by hooks).")

    def run(self, args: argparse.Namespace) -> int:
        local, repo = LocalHome(), open_repo(args)
        if args.session:
            recorder = CheckpointRecorder(local, repo, SessionRecord(repo, args.profile, args.session))
        else:
            recorder = CheckpointRecorder.current(local, repo, args.profile)
            if recorder is None:
                raise ErrorExit(f"No current session for {args.profile}; pass --session.")
        result = recorder.write(_read_stdin_text(), args.reason)
        GitSync(repo.root, repo.config.git).sync(
            f"{args.profile}: checkpoint {result.number} of {recorder.session.id}", push=True)
        if not args.quiet:
            print(f"Checkpoint {result.number} saved for {recorder.session.id}.")
            for path in result.digested:
                print(f"  + {path}")
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
