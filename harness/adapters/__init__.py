"""Tool adapters. Importing this package registers every built-in adapter."""

from .base import Account, AccountBoundAdapter, Adapter, AdapterRegistry, HarnessNotConfigured, adapters
from .claude_ai import ClaudeAiAdapter
from .claude_code import ClaudeCodeAdapter
from .cowork import CoworkAdapter
from .monday import MondayAdapter

__all__ = [
    "Account", "AccountBoundAdapter", "Adapter", "AdapterRegistry", "ClaudeAiAdapter",
    "ClaudeCodeAdapter", "CoworkAdapter", "HarnessNotConfigured", "MondayAdapter", "adapters",
]
