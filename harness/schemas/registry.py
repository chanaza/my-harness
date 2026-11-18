"""The schema registry: every JSON Schema the engine knows about.

Schemas reference each other by ``$id`` (e.g. every item type points to
provenance.schema.json), so they are resolved together.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib import resources

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


class SchemaRegistry:
    """Named JSON Schemas with cross-references resolved."""

    SUFFIX = ".schema.json"

    def __init__(self, schemas: Mapping[str, dict]) -> None:
        self._schemas = dict(schemas)
        self._resolver = Registry().with_resources(
            (s["$id"], Resource.from_contents(s)) for s in self._schemas.values()
        )
        self._validators: dict[str, Draft202012Validator] = {}

    @classmethod
    @lru_cache(maxsize=1)
    def bundled(cls) -> SchemaRegistry:
        """The schemas that ship with the engine (loaded once)."""
        schemas = {}
        for entry in resources.files(__package__).iterdir():
            if entry.name.endswith(cls.SUFFIX):
                schemas[entry.name[: -len(cls.SUFFIX)]] = json.loads(entry.read_text("utf-8"))
        return cls(schemas)

    def names(self) -> list[str]:
        return sorted(self._schemas)

    def validator(self, name: str) -> Draft202012Validator:
        if name not in self._schemas:
            raise KeyError(f"No schema named {name!r}. Known: {', '.join(self.names())}")
        if name not in self._validators:
            self._validators[name] = Draft202012Validator(
                self._schemas[name], registry=self._resolver, format_checker=FormatChecker()
            )
        return self._validators[name]

    def errors(self, name: str, data: object) -> list[str]:
        """Validate ``data`` against schema ``name``; return readable messages."""
        found = sorted(self.validator(name).iter_errors(data), key=lambda e: list(e.path))
        return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in found]
