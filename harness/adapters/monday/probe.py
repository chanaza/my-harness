"""``MondayProbe``: find out what this account's API really lets us read.

Prints names and counts only, never content. Used to decide what the Monday
adapter can capture (agents, workflows, their knowledge, triggers, memory).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .client import MondayClient, MondayError

#: Words that mark the parts we care about first.
INTERESTING = ("agent", "workflow", "automation", "memory", "knowledge", "trigger", "skill", "recipe")

INTROSPECTION = """
query { __schema { queryType { fields {
  name args { name type { kind name ofType { kind name ofType { kind name } } } }
  type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
} } } }
"""

TYPE_FIELDS = """
query ($name: String!) { __type(name: $name) { name fields {
  name type { kind name ofType { kind name ofType { kind name } } }
} } }
"""


@dataclass
class ProbeReport:
    account: str = ""
    api_version: str = ""
    queries: list[str] = field(default_factory=list)          # interesting top-level queries
    types: dict[str, list[str]] = field(default_factory=dict)  # their result types' fields
    counts: dict[str, str] = field(default_factory=dict)       # how many items each returned
    notes: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"Account: {self.account}", f"API version: {self.api_version}",
               "Queries about agents / workflows / automations:"]
        out += [f"  {q}" for q in self.queries] or ["  (none)"]
        for name, fields in self.types.items():
            out.append(f"Fields of {name}: {', '.join(fields)}")
        out.append("What this account has:")
        out += [f"  {k}: {v}" for k, v in self.counts.items()] or ["  (nothing could be read)"]
        out += [f"Note: {n}" for n in self.notes]
        return out


def _unwrap(type_ref: dict[str, Any]) -> tuple[str | None, bool]:
    """(named type, is list) of a GraphQL type reference."""
    is_list = False
    while type_ref and not type_ref.get("name"):
        is_list = is_list or type_ref.get("kind") == "LIST"
        type_ref = type_ref.get("ofType") or {}
    return type_ref.get("name"), is_list


def _required_args(field_def: dict[str, Any]) -> list[str]:
    return [a["name"] for a in field_def.get("args") or [] if (a.get("type") or {}).get("kind") == "NON_NULL"]


class MondayProbe:
    def __init__(self, client: MondayClient) -> None:
        self.client = client

    def run(self) -> ProbeReport:
        report = ProbeReport(api_version=self.client.api_version)
        me = self.client.query("query { me { email account { name slug } } }").get("me") or {}
        report.account = f"{(me.get('account') or {}).get('name', '?')} ({me.get('email', '?')})"
        fields = self.client.query(INTROSPECTION)["__schema"]["queryType"]["fields"]
        interesting = [f for f in fields if any(word in f["name"].lower() for word in INTERESTING)]
        for f in sorted(interesting, key=lambda f: f["name"]):
            type_name, is_list = _unwrap(f["type"])
            required = _required_args(f)
            report.queries.append(f"{f['name']} -> {type_name}{'[]' if is_list else ''}"
                                  + (f" (needs: {', '.join(required)})" if required else ""))
            if type_name and type_name not in report.types:
                report.types[type_name] = self._fields_of(type_name)
            if is_list and not required:
                report.counts[f["name"]] = self._count(f["name"], type_name)
        return report

    def _fields_of(self, type_name: str) -> list[str]:
        try:
            found = self.client.query(TYPE_FIELDS, {"name": type_name}).get("__type") or {}
        except MondayError:
            return []
        return [f["name"] for f in found.get("fields") or []]

    def _count(self, query_name: str, type_name: str | None) -> str:
        fields = self._fields_of(type_name) if type_name else []
        pick = next((f for f in ("id", "name", "title") if f in fields), None)
        if not pick:
            return "could not count (no id field)"
        try:
            data = self.client.query(f"query {{ {query_name} {{ {pick} }} }}")
        except MondayError as exc:
            return f"not readable ({exc})"
        items = data.get(query_name) or []
        return str(len(items)) if isinstance(items, list) else "1"
