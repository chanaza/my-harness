"""SecretGuard: secret values never reach the repository; the files they were in do."""

from __future__ import annotations

import json

from harness.secrets import MARKER, SecretGuard


def test_a_literal_secret_value_is_hidden_and_its_name_kept():
    text = "const API_KEY = 'abcd1234efgh5678';\nHMS_PASSWORD=abc12345678\nkey: ghp_abcdefghijklmnop1234"
    cleaned = SecretGuard().clean_text(text, "main.ts")
    assert "abcd1234efgh5678" not in cleaned.text and "abc12345678" not in cleaned.text
    assert "ghp_abcdefghijklmnop1234" not in cleaned.text
    assert "API_KEY" in cleaned.text and MARKER in cleaned.text
    assert {"API_KEY", "HMS_PASSWORD"} <= set(cleaned.hidden)


def test_code_that_names_or_reads_a_secret_is_not_a_secret():
    text = "const t = process.env.TOKEN;\nasync function f(token: string) {}\nconst x = envToken || '';"
    assert SecretGuard().clean_text(text, "main.ts").hidden == []


def test_settings_records_hide_the_value_of_a_secret_named_key():
    rows = [{"key": "outlook_bridge_token", "value": "zzzzzzzzzzzz"},
            {"key": "group_password", "value": "1234"},
            {"key": "owner_phone", "value": "0501234567"},
            {"name": "x", "api_key": "kkkkkkkkkkkk", "env": {"TOKEN": "${TOKEN}"}}]
    cleaned = SecretGuard().clean_text(json.dumps(rows), "data/ClientSetting.json")
    saved = json.loads(cleaned.text)
    assert saved[0]["value"] == MARKER and saved[1]["value"] == MARKER  # a short PIN too
    assert saved[2]["value"] == "0501234567"
    assert saved[3]["api_key"] == MARKER and saved[3]["env"]["TOKEN"] == "${TOKEN}"
    assert set(cleaned.hidden) == {"outlook_bridge_token", "group_password", "api_key"}
