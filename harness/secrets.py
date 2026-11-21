"""The one place that keeps secrets out of the harness.

Everything that enters the content repository from a tool passes through ``SecretGuard``
(HarvestSync, for every adapter; the inbox, for every tool that saves through the connector).
A secret *value* is replaced by a marker that keeps its name, so a file stays whole and
whoever rebuilds it knows what to set up again; nothing else about the file changes.

What counts as a secret value:
  - a known token shape (GitHub, Anthropic, Slack, AWS, Base44 keys...);
  - a literal given to a secret-named key in text (``password: "..."``, ``TOKEN='...'``,
    ``API_KEY=...`` on its own line);
  - in JSON, a string under a secret-named field, or the value of a record whose
    ``key`` / ``name`` is secret-named (settings tables: ``{"key": "x_token", "value": "..."}``).
Code that names, reads or types a secret (``process.env.TOKEN``, ``token: string``) is not one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

MARKER = "<secret: not saved - set it again where it is used>"

TOKEN = re.compile(r"(ghp_|github_pat_|sk-ant-|sk-[A-Za-z0-9]{20}|xox[bp]-|AKIA|b44k_)[A-Za-z0-9_-]{8,}")
SECRET_NAME = re.compile(r"password|passwd|secret|token|api_?key|credential|private_?key|\bpin\b|guid",
                         re.IGNORECASE)
_NAMED = r"(?P<name>[\w.-]*(?:password|passwd|secret|token|api_?key|credential)[\w.-]*)"
QUOTED = re.compile(_NAMED + r"(?P<sep>[\"']?\s*[:=]\s*)(?P<q>[\"'`])(?P<value>[^\s\"'`${}]{8,})(?P=q)",
                    re.IGNORECASE)
ENV_LINE = re.compile(r"^(?P<lead>\s*)(?P<name>[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_?KEY)[A-Z0-9_]*)"
                      r"(?P<sep>\s*=\s*)(?P<value>[^\s\"'`${}]{8,})\s*$", re.MULTILINE | re.IGNORECASE)
RECORD_NAME_FIELDS = ("key", "name", "id", "setting")
RECORD_VALUE_FIELDS = ("value", "val", "secret", "data")


@dataclass
class Cleaned:
    text: str
    hidden: list[str] = field(default_factory=list)  # names of the values that were hidden


class SecretGuard:
    def clean_text(self, text: str, path: str = "") -> Cleaned:
        if path.lower().endswith(".json"):
            cleaned = self._clean_json(text)
            if cleaned is not None:
                return cleaned
        hidden: list[str] = []

        def quoted(m: re.Match[str]) -> str:
            hidden.append(m.group("name"))
            return f"{m.group('name')}{m.group('sep')}{m.group('q')}{MARKER}{m.group('q')}"

        def env_line(m: re.Match[str]) -> str:
            hidden.append(m.group("name"))
            return f"{m.group('lead')}{m.group('name')}{m.group('sep')}{MARKER}"

        def token(m: re.Match[str]) -> str:
            hidden.append(m.group(1).rstrip("_-") + "...")
            return MARKER

        text = QUOTED.sub(quoted, text)
        text = ENV_LINE.sub(env_line, text)
        text = TOKEN.sub(token, text)
        return Cleaned(text, hidden)

    def clean_value(self, value: Any) -> tuple[Any, list[str]]:
        """A parsed structure (an item's meta), cleaned the same way as JSON."""
        hidden: list[str] = []
        return self._walk(value, hidden, ""), hidden

    # --- JSON ------------------------------------------------------------------------------

    def _clean_json(self, text: str) -> Cleaned | None:
        try:
            data = json.loads(text)
        except ValueError:
            return None
        hidden: list[str] = []
        cleaned = self._walk(data, hidden, "")
        if not hidden:
            return Cleaned(text, [])
        return Cleaned(json.dumps(cleaned, ensure_ascii=False, indent=1), hidden)

    def _walk(self, value: Any, hidden: list[str], name: str) -> Any:
        if isinstance(value, dict):
            record = next((str(value[k]) for k in RECORD_NAME_FIELDS if isinstance(value.get(k), str)), "")
            out = {}
            for key, item in value.items():
                secret_here = isinstance(item, str) and item and item != MARKER and (
                    (SECRET_NAME.search(key) and not _is_reference(item))
                    or (key in RECORD_VALUE_FIELDS and SECRET_NAME.search(record) and not _is_reference(item))
                    or TOKEN.search(item))
                if secret_here:
                    hidden.append(record if key in RECORD_VALUE_FIELDS and record else key)
                    out[key] = MARKER
                else:
                    out[key] = self._walk(item, hidden, key)
            return out
        if isinstance(value, list):
            return [self._walk(v, hidden, name) for v in value]
        if isinstance(value, str) and TOKEN.search(value):
            hidden.append(name or "a token")
            return TOKEN.sub(MARKER, value)
        return value


def _is_reference(value: str) -> bool:
    """A placeholder or reference to a secret, not the secret itself (``${TOKEN}``, ``<set in X>``,
    a boolean or a short word such as ``true``)."""
    stripped = value.strip()
    return (len(stripped) < 6 or stripped.startswith(("${", "$", "<", "{{"))
            or stripped.lower() in ("true", "false", "null"))
