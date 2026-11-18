"""``CredentialStore``: API tokens live in the operating system's password store, never in Git.

Windows Credential Manager, macOS Keychain or the Linux secret service (through
``keyring``). An environment variable can be used instead (e.g. on servers).
"""

from __future__ import annotations

import os

SERVICE = "my-harness"


class CredentialError(Exception):
    pass


class CredentialStore:
    def __init__(self, service: str = SERVICE) -> None:
        self.service = service

    @staticmethod
    def env_name(name: str) -> str:
        """e.g. 'monday:default' -> HARNESS_MONDAY_DEFAULT_TOKEN."""
        return "HARNESS_" + "".join(c if c.isalnum() else "_" for c in name).upper() + "_TOKEN"

    def get(self, name: str) -> str | None:
        """The secret for ``name`` (e.g. 'monday:proceed'), from its variable or the password store."""
        from_env = os.environ.get(self.env_name(name))
        if from_env:
            return from_env
        try:
            import keyring
            return keyring.get_password(self.service, name)
        except Exception:  # no usable password store on this machine
            return None

    def set(self, name: str, secret: str) -> None:
        try:
            import keyring
            keyring.set_password(self.service, name, secret)
        except Exception as exc:
            raise CredentialError(f"Could not save the token in this machine's password store ({exc}). "
                                  f"Set the environment variable {self.env_name(name)} instead.") from None
