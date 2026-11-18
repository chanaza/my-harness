"""Tool adapters. Importing this package registers every built-in adapter."""

from .base import Adapter, AdapterRegistry, adapters
from .claude_code import ClaudeCodeAdapter

__all__ = ["Adapter", "AdapterRegistry", "ClaudeCodeAdapter", "adapters"]
