from conftest import PROVENANCE

from harness.schemas import SchemaRegistry


def test_all_bundled_schemas_compile():
    registry = SchemaRegistry.bundled()
    for name in registry.names():
        registry.errors(name, {})  # must not raise (all $refs resolve)


def test_dates_are_checked():
    registry = SchemaRegistry.bundled()
    assert registry.errors("provenance", {"source": {"profile": "chatgpt-work", "at": "yesterday"}})
    assert not registry.errors("provenance", PROVENANCE)
