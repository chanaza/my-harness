"""``SetupWizard``: `harness setup` - connect a tool on this machine to a harness in one go.

It installs CAPTURE only (hooks + the save skill). Nothing from the harness is
loaded into the tool: loading is a separate, explicit step.

Questions are asked through a ``Prompter``, so the same wizard runs
interactively (``ConsolePrompter``) or unattended (``DefaultsPrompter``,
e.g. from a cloud environment's setup script with --yes).
"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import Adapter, adapters
from .git_sync import GitSync
from .local import LocalHome
from .profiles import Profile
from .repo import ContentRepo
from .scaffold import InitOptions, Scaffolder

CLOUD_ENV_FLAG = "CLAUDE_CODE_REMOTE"  # set to "true" in Claude Code cloud sessions


class SetupError(Exception):
    pass


# --- asking questions -----------------------------------------------------------------

class Prompter(ABC):
    @abstractmethod
    def ask(self, question: str, default: str | None = None) -> str: ...

    @abstractmethod
    def confirm(self, question: str, default: bool = True) -> bool: ...

    def say(self, text: str) -> None:
        print(text)


class ConsolePrompter(Prompter):
    def ask(self, question: str, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            answer = input(f"{question}{suffix}: ").strip()
            if answer or default:
                return answer or default or ""

    def confirm(self, question: str, default: bool = True) -> bool:
        answer = input(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        return default if not answer else answer.startswith("y")


class DefaultsPrompter(Prompter):
    """Answers every question with its default (for --yes). A question without one is an error."""

    def ask(self, question: str, default: str | None = None) -> str:
        if default is None:
            raise SetupError(f"No answer for: {question} (pass it as an option)")
        return default

    def confirm(self, question: str, default: bool = True) -> bool:
        return True


# --- the wizard ----------------------------------------------------------------------------

@dataclass
class SetupOptions:
    tool: str = "claude-code"
    repo: str | None = None            # a local folder or a Git URL
    account: str | None = None         # e.g. "personal", "work"
    environment: str | None = None     # "local" | "cloud" (detected when omitted)
    transcripts: str | None = None     # local transcript folder
    owner: str | None = None           # only when creating a new harness
    capture_now: bool | None = None    # None = ask


@dataclass
class SetupResult:
    profile: str
    repo: Path
    done: list[str] = field(default_factory=list)


class SetupWizard:
    def __init__(self, prompter: Prompter, local: LocalHome | None = None) -> None:
        self.prompter = prompter
        self.local = local or LocalHome()

    def run(self, options: SetupOptions) -> SetupResult:
        environment = options.environment or self._detect_environment()
        repo = self._content_repo(options)
        account = options.account or self.prompter.ask(
            "Which account is this? (a short name, e.g. personal or work)", "personal")
        profile = Profile.make_id(options.tool, account, environment)

        repo.config_file.update(self._storage_for(profile, environment, options))
        adapter = adapters.create(options.tool, self.local)
        done = adapter.install(profile, account, repo.root, hooks=True, environment=environment)
        result = SetupResult(profile, repo.root, done)

        self._offer_capture(adapter, repo, options, result)
        GitSync(repo.root, repo.config.git).sync(f"{profile}: setup", push=True)
        return result

    # --- steps --------------------------------------------------------------------------

    def _detect_environment(self) -> str:
        if os.environ.get(CLOUD_ENV_FLAG, "").lower() == "true":
            return "cloud"
        answer = self.prompter.ask("Is this your own computer (local) or a cloud session (cloud)?", "local")
        if answer not in ("local", "cloud"):
            raise SetupError("Please answer local or cloud.")
        return answer

    def _content_repo(self, options: SetupOptions) -> ContentRepo:
        source = options.repo or self.local.settings().get("content_repo") or self.prompter.ask(
            "Where is your harness repository? (a folder, or its GitHub address)")
        folder = self._clone(source) if _is_url(source) else Path(source).expanduser()
        repo = ContentRepo(folder)
        if not repo.config_file.path.is_file():
            if not self.prompter.confirm(f"{folder} has no harness yet. Create a new one there?"):
                raise SetupError("A harness repository is needed.")
            owner = options.owner or self.prompter.ask("Your name (shown in the repository)", "me")
            Scaffolder().create(folder, InitOptions(owner=owner))
        return ContentRepo(folder)

    def _clone(self, url: str) -> Path:
        target = Path.home() / url.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
        if not (target / ".git").is_dir():
            self.prompter.say(f"Downloading {url} to {target} ...")
            result = subprocess.run(["git", "clone", url, str(target)], capture_output=True, text=True)
            if result.returncode != 0:
                raise SetupError(f"Could not download {url}: {result.stderr.strip()}")
        return target

    def _storage_for(self, profile: str, environment: str, options: SetupOptions) -> dict[str, object]:
        """Where this profile's transcripts go: a local folder, or (cloud) a Git branch."""
        prefix = f"storage_by_profile.{profile}.transcripts"
        if environment == "cloud":
            return {f"{prefix}.backend": "git", f"{prefix}.remote": "origin",
                    f"{prefix}.branch": "transcripts"}
        folder = options.transcripts or self.prompter.ask(
            "Folder for full conversation transcripts (a OneDrive/Drive folder keeps them in the cloud)",
            str(_default_transcripts_folder()))
        return {f"{prefix}.backend": "filesystem", f"{prefix}.path": folder}

    def _offer_capture(self, adapter: Adapter, repo: ContentRepo, options: SetupOptions,
                       result: SetupResult) -> None:
        items = adapter.harvest(repo.config.harvest_exclude)
        sessions = adapter.backfill(dry_run=True)
        self.prompter.say(f"Found {len(items)} things built in {options.tool} "
                          f"and {len(sessions)} past conversations.")
        for item in items:
            self.prompter.say(f"  {item.kind.value:11} {item.name}")
        wanted = options.capture_now if options.capture_now is not None else self.prompter.confirm(
            "Save them to your harness now? (you can exclude items first with "
            "`harness config set harvest.exclude ...`)")
        if wanted:
            report = adapter.run_harvest()
            imported = adapter.backfill()
            result.done.append(f"captured: {report.summary()}; conversations: {len(imported)}")


def _is_url(source: str) -> bool:
    return source.startswith(("https://", "git@", "ssh://"))


def _default_transcripts_folder() -> Path:
    """A synced cloud folder when one exists (OneDrive on Windows), else the home folder."""
    for variable in ("OneDriveCommercial", "OneDrive"):
        if os.environ.get(variable):
            return Path(os.environ[variable]) / "harness-transcripts"
    return Path.home() / "harness-transcripts"
