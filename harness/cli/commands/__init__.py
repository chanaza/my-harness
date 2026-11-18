"""All built-in `harness` commands."""

from ..base import Command
from .capture import (
    BackfillCommand,
    HarvestCommand,
    HookCommand,
    InstallCommand,
    MemoryCommand,
    ProfileCommand,
    SessionCommand,
    SetupCommand,
    StatusCommand,
)
from .repository import ConfigCommand, InitCommand, UpgradeCommand, ValidateCommand

#: Commands exposed by `harness`, in help order.
DEFAULT_COMMANDS: tuple[type[Command], ...] = (
    SetupCommand, StatusCommand,
    InitCommand, ValidateCommand, ConfigCommand, UpgradeCommand,
    ProfileCommand, InstallCommand, HarvestCommand, BackfillCommand, HookCommand,
    SessionCommand, MemoryCommand,
)

__all__ = ["DEFAULT_COMMANDS"]
