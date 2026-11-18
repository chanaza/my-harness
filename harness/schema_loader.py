"""Load the JSON Schemas that ship with the engine.

Schemas reference each other by ``$id`` (e.g. every item type points to
provenance.schema.json), so they are loaded together into one registry.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

_SUFFIX = ".schema.json"


@lru_cache(maxsize=1)
def _load_all() -> tuple[dict[str, dict], Registry]:
    schemas: dict[str, dict] = {}
    registry = Registry()
    for entry in resources.files("harness.schemas").iterdir():
        if entry.name.endswith(_SUFFIX):
            schema = json.loads(entry.read_text("utf-8"))
            schemas[entry.name[: -len(_SUFFIX)]] = schema
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return schemas, registry


def schema_names() -> list[str]:
    """Names of all bundled schemas."""
    return sorted(_load_all()[0])


@lru_cache(maxsize=None)
def get_validator(name: str) -> Draft202012Validator:
    """Return a validator for ``harness/schemas/<name>.schema.json``."""
    schemas, registry = _load_all()
    if name not in schemas:
        raise KeyError(f"No schema named {name!r}. Known: {', '.join(sorted(schemas))}")
    return Draft202012Validator(schemas[name], registry=registry, format_checker=FormatChecker())


def schema_errors(name: str, data: object) -> list[str]:
    """Validate ``data`` against a schema and return readable error messages."""
    errors = sorted(get_validator(name).iter_errors(data), key=lambda e: list(e.path))
    messages = []
    for error in errors:
        where = "/".join(str(p) for p in error.path) or "(root)"
        messages.append(f"{where}: {error.message}")
    return messages
