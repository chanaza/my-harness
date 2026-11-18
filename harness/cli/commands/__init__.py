"""All built-in `harness` commands."""

from ..base import Command
from .capture import (
    BackfillCommand,
    HarvestCommand,
    HookCommand,
    InstallCommand,
    MemoryCommand,
    MondayCommand,
    ProfileCommand,
    SessionCommand,
    SetupCommand,
    SkillCommand,
    StatusCommand,
    UpdateCommand,
)
from .repository import ConfigCommand, InitCommand, MergeFileCommand, UpgradeCommand, ValidateCommand

#: Commands exposed by `harness`, in help order.
DEFAULT_COMMANDS: tuple[type[Command], ...] = (
    SetupCommand, StatusCommand, UpdateCommand,
    InitCommand, ValidateCommand, ConfigCommand, UpgradeCommand,
    ProfileCommand, InstallCommand, HarvestCommand, BackfillCommand, HookCommand,
    SessionCommand, MemoryCommand, SkillCommand, MondayCommand, MergeFileCommand,
)

__all__ = ["DEFAULT_COMMANDS"]
