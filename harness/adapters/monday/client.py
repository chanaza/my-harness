"""``MondayClient``: a small GraphQL client for monday.com's platform API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class MondayError(Exception):
    pass


class MondayClient:
    def __init__(self, token: str, endpoint: str, api_version: str, timeout: float = 60) -> None:
        self.token = token
        self.endpoint = endpoint
        self.api_version = api_version
        self.timeout = timeout

    def query(self, text: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps({"query": text, "variables": variables or {}}).encode("utf-8")
        request = urllib.request.Request(self.endpoint, data=body, method="POST", headers={
            "Authorization": self.token, "API-Version": self.api_version,
            "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise MondayError(f"monday.com answered {exc.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise MondayError(f"Could not reach monday.com: {exc}") from None
        if payload.get("errors"):
            messages = "; ".join(str(e.get("message", e)) for e in payload["errors"])
            raise MondayError(messages)
        return payload.get("data") or {}
