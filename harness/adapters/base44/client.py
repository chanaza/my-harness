"""``Base44Client``: GET requests to Base44's API with a personal access token (Bearer)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class Base44Error(Exception):
    pass


class Base44Client:
    def __init__(self, token: str, base: str = "https://app.base44.com", timeout: float = 90) -> None:
        self.token = token
        self.base = base.rstrip("/")
        self.timeout = timeout

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{self.base}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "User-Agent": "my-harness",
            },  # Python's default is refused by Base44's Cloudflare
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise Base44Error(f"Base44 answered {exc.code} for {path}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise Base44Error(f"Could not reach Base44: {exc}") from None
