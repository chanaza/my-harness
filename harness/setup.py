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

from .adapters import Account, Adapter, adapters
from .git_sync import GitSync
from .local import LocalHome
from .profiles import Profile
from .repo import ContentRepo
from .scaffold import InitOptions, Scaffolder

CLOUD_ENV_FLAG = "CLAUDE_CODE_REMOTE"  # set to "true" in Claude Code cloud sessions


class SetupError(Exception):
    pass


class SetupSkipped(Exception):
    """The user chose not to connect this tool."""


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
    account: str | None = None         # "personal", or for several accounts "abcd1234=personal,..."
    environment: str | None = None     # "local" | "cloud" (detected when omitted)
    transcripts: str | None = None     # local transcript folder
    owner: str | None = None           # only when creating a new harness
    capture_now: bool | None = None    # None = ask


@dataclass
class SetupResult:
    profile: str
    repo: Path
    done: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    environment: str = "local"                         # of this machine
    next_steps: list[str] = field(default_factory=list)  # what the user still does by hand


class SetupWizard:
    def __init__(self, prompter: Prompter, local: LocalHome | None = None) -> None:
        self.prompter = prompter
        self.local = local or LocalHome()

    def run(self, options: SetupOptions) -> SetupResult:
        environment = options.environment or self._detect_environment()
        repo = self._content_repo(options)
        # Known from now on, so adapters read this harness's settings (e.g. where exports land).
        self.local.save_settings(content_repo=str(repo.root.resolve()))
        adapter = adapters.create(options.tool, self.local)
        chosen = self._choose_accounts(adapter.accounts(), options, adapter.account_question)

        result = SetupResult("", repo.root, environment=environment)
        storage_folder: str | None = None
        profile_environment = adapter.environment or environment  # e.g. claude.ai is always cloud
        for account, label in chosen:
            profile = Profile.make_id(options.tool, label, profile_environment)
            if environment == "local" and storage_folder is None:
                storage_folder = options.transcripts or self._ask_transcripts_folder()
            # Storage follows the machine doing the capture, not the service.
            repo.config_file.update(self._storage_for(profile, environment, storage_folder))
            result.done += adapter.install(profile, label, repo.root, hooks=True,
                                           environment=profile_environment, account_key=account.key)
            result.profiles.append(profile)
        result.profile = ", ".join(result.profiles)

        self._offer_capture(adapter, repo, options, result)
        result.next_steps = adapter.after_setup(result.profiles)
        GitSync(repo.root, repo.config.git).sync(f"{options.tool}: setup {result.profile}", push=True)
        return result

    def _choose_accounts(self, accounts: list[Account], options: SetupOptions,
                         adapter_question: str | None = None) -> list[tuple[Account, str]]:
        """Name each account. Accounts found on the machine are listed first; accounts the user
        typed (e.g. e-mail addresses) are simply named, one by one."""
        typed = False
        if not accounts and adapter_question:
            # Nothing captured yet (e.g. no export downloaded): the user names the accounts.
            answer = self.prompter.ask(adapter_question, "")
            accounts = [Account(key.strip(), key.strip()) for key in answer.split(",") if key.strip()]
            typed = True
            if not accounts:
                raise SetupSkipped(options.tool)
        if not accounts:
            raise SetupError(f"Nothing from {options.tool} was found on this machine.")
        if len(accounts) == 1 and not typed:
            plain = options.account if options.account and "=" not in options.account else None
            label = plain or self.prompter.ask(
                "Which account is this? (a short name, e.g. personal or work)", "personal")
            return [(accounts[0], label)]
        given = dict(part.split("=", 1) for part in (options.account or "").split(",") if "=" in part)
        if not typed:
            self.prompter.say(f"Found {len(accounts)} accounts:")
            for number, account in enumerate(accounts, 1):
                self.prompter.say(f"  {number}. {account.summary}")
        chosen = []
        for number, account in enumerate(accounts, 1):
            subject = account.key if typed else f"account {number}"
            label = next((v for k, v in given.items() if k in (account.key or "")), None) or \
                self.prompter.ask(f"Name for {subject} (e.g. personal or work; 'skip' leaves it out)")
            if label.strip().lower() != "skip":
                chosen.append((account, label.strip()))
            else:
                self.prompter.say(f"  {subject} left out")
        if not chosen:
            raise SetupError("No account was chosen.")
        return chosen

    # --- steps --------------------------------------------------------------------------

    def _detect_environment(self) -> str:
        if os.environ.get(CLOUD_ENV_FLAG, "").lower() == "true":
            return "cloud"
        answer = self.prompter.ask("Is this your own computer (local) or a cloud session (cloud)?", "local")
        if answer not in ("local", "cloud"):
            raise SetupError("Please answer local or cloud.")
        return answer

    def _content_repo(self, options: SetupOptions) -> ContentRepo:
        source = options.repo or self.local.settings().get("content_repo") or self._ask_repo()
        folder = self._clone(source) if _is_url(source) else Path(source).expanduser()
        if not folder.is_dir():
            raise SetupError(f"There is no folder {folder}.")
        repo = ContentRepo(folder)
        if not repo.config_file.path.is_file():
            if not self.prompter.confirm(f"{folder} has no harness yet. Create a new one there?"):
                raise SetupError("A harness repository is needed.")
            owner = options.owner or self.prompter.ask("Your name (shown in the repository)", "me")
            Scaffolder().create(folder, InitOptions(owner=owner))
        return ContentRepo(folder)

    def _ask_repo(self) -> str:
        """Ask until the answer is a GitHub address or an existing folder."""
        question = ("Paste the GitHub address of your harness repository\n"
                    "  (e.g. https://github.com/your-name/my-harness-content),\n"
                    "  or the full path of a folder that already holds it")
        while True:
            answer = self.prompter.ask(question).strip().strip('"')
            if _is_url(answer) or Path(answer).expanduser().is_dir():
                return answer
            self.prompter.say(f"'{answer}' is neither a GitHub address nor an existing folder. Try again.")

    def _clone(self, url: str) -> Path:
        target = Path.home() / url.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
        if not (target / ".git").is_dir():
            self.prompter.say(f"Downloading {url} to {target} ...")
            result = subprocess.run(["git", "clone", url, str(target)], capture_output=True, text=True)
            if result.returncode != 0:
                hint = ""
                if "not found" in result.stderr.lower():
                    hint = ("\n\nGitHub says 'not found' for a private repository when Git is not signed "
                            "in as an account that can see it. Sign in, then run setup again: run\n"
                            f"  git clone {url}\n"
                            "and log in with the GitHub account that owns the repository. If no login "
                            "window appears, Git is signed in as another account; remove that login "
                            "(Windows: cmdkey /delete:git:https://github.com) and try again.")
                raise SetupError(f"Could not download {url}: {result.stderr.strip()}{hint}")
        return target

    def _ask_transcripts_folder(self) -> str:
        return self.prompter.ask(
            "Folder for full conversation transcripts and files (a OneDrive/Drive folder keeps them "
            "in the cloud)", str(_default_transcripts_folder()))

    @staticmethod
    def _storage_for(profile: str, environment: str, folder: str | None) -> dict[str, object]:
        """Where this profile's transcripts go: a local folder, or (cloud) a Git branch."""
        prefix = f"storage_by_profile.{profile}.transcripts"
        if environment == "cloud":
            return {f"{prefix}.backend": "git", f"{prefix}.remote": "origin",
                    f"{prefix}.branch": "transcripts"}
        return {f"{prefix}.backend": "filesystem", f"{prefix}.path": folder}

    def _offer_capture(self, adapter: Adapter, repo: ContentRepo, options: SetupOptions,
                       result: SetupResult) -> None:
        lines = adapter.preview(repo.config.harvest_exclude)
        if not lines:
            return  # nothing to save yet (e.g. no export downloaded); it will be saved when it arrives
        self.prompter.say(f"Found in {options.tool}:")
        for line in lines:
            self.prompter.say(f"  {line}")
        wanted = options.capture_now if options.capture_now is not None else self.prompter.confirm(
            "Save them to your harness now? (you can exclude items first with "
            "`harness config set harvest.exclude ...`)")
        if wanted:
            GitSync(repo.root, repo.config.git).pull()
            result.done.append(f"captured: {adapter.capture()}")


def _is_url(source: str) -> bool:
    return source.startswith(("https://", "git@", "ssh://"))


def _default_transcripts_folder() -> Path:
    """A synced cloud folder when one exists (OneDrive on Windows), else the home folder."""
    for variable in ("OneDriveCommercial", "OneDrive"):
        if os.environ.get(variable):
            return Path(os.environ[variable]) / "harness-transcripts"
    return Path.home() / "harness-transcripts"
