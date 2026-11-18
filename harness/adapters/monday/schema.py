"""``SchemaSelector``: build GraphQL selections from monday's own schema.

monday's AI parts (agents, workflows) live in the preview API and change often.
Instead of hard-coding every field, the adapter asks the schema which fields a
type has and selects all of them (to a depth), so new fields are captured too.
"""

from __future__ import annotations

from typing import Any

from .client import MondayClient

TYPE_QUERY = """
query ($name: String!) { __type(name: $name) { fields {
  name type { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } } }
} } }
"""


class SchemaSelector:
    def __init__(self, client: MondayClient, depth: int = 4) -> None:
        self.client = client
        self.depth = depth
        self._fields: dict[str, list[tuple[str, str | None, str | None]]] = {}

    def fields(self, type_name: str) -> list[tuple[str, str | None, str | None]]:
        """(field, type name, kind) of every field of ``type_name``."""
        if type_name not in self._fields:
            found = (self.client.query(TYPE_QUERY, {"name": type_name}).get("__type") or {}).get("fields")
            self._fields[type_name] = [(f["name"], *_named(f["type"])) for f in found or []]
        return self._fields[type_name]

    def selection(self, type_name: str, level: int = 0) -> str:
        parts = []
        for name, inner, kind in self.fields(type_name):
            if kind in ("SCALAR", "ENUM"):
                parts.append(name)
            elif kind == "OBJECT" and level < self.depth and inner:
                parts.append(f"{name} {{ {self.selection(inner, level + 1) or '__typename'} }}")
        return " ".join(parts)


def _named(type_ref: dict[str, Any]) -> tuple[str | None, str | None]:
    while type_ref and not type_ref.get("name"):
        type_ref = type_ref.get("ofType") or {}
    return type_ref.get("name"), type_ref.get("kind")
