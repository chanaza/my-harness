"""The connector refuses at the door what the engine would reject later: the same fields."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_connector_requires_what_the_engine_schemas_require():
    worker = (ROOT / "connector" / "worker.js").read_text()
    block = re.search(r"const REQUIRED = \{(.*?)\};", worker, re.S).group(1)
    pairs = re.findall(r"(\w+): \[([^\]]*)\]", block)
    door = {kind: re.findall(r'"([a-z_]+)"', fields) for kind, fields in pairs}
    for kind in ("describe", "conversation", "exchange"):
        schema = json.loads((ROOT / "harness" / "schemas" / f"harness-{kind}.schema.json").read_text())
        assert set(door[kind]) == set(schema["required"]) - {"schema"}, kind


def test_an_exchange_sent_with_header_lines_and_no_numbers_is_still_read():
    from harness.inbox import _document, _from_name

    text = "schema: harness-exchange/1\nprofile: genspark-personal-cloud\ntool: genspark\n\n## User\nq\n"
    document = _document(text)
    assert document.meta["tool"] == "genspark" and document.body.startswith("## User")
    assert _from_name("exchange-2026-11-22-base44-recap-1.md") == {
        "conversation": "conversation-2026-11-22-base44-recap", "number": 1}
