"""Small HTTP helper with in-process caching for scholarly adapters."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Dict, Optional


class HTTPClient:
    """A small wrapper around urllib with simple response caching."""

    def __init__(self, timeout: int = 15, user_agent: Optional[str] = None) -> None:
        self.timeout = timeout
        self.user_agent = user_agent or "CiteGuard/0.1 (+https://example.invalid)"
        self._cache: Dict[str, str] = {}

    def get_text(
        self,
        url: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        use_cache: bool = True,
        timeout: Optional[int] = None,
    ) -> str:
        full_url = self._build_url(url, params)
        if use_cache and full_url in self._cache:
            return self._cache[full_url]

        request_headers = {"User-Agent": self.user_agent}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(full_url, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:  # nosec B310
                payload = response.read().decode("utf-8")
        except Exception:
            return ""

        if use_cache:
            self._cache[full_url] = payload
        return payload

    def get_json(
        self,
        url: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        use_cache: bool = True,
        timeout: Optional[int] = None,
    ) -> dict:
        payload = self.get_text(
            url=url,
            params=params,
            headers=headers,
            use_cache=use_cache,
            timeout=timeout,
        )
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {}

    def _build_url(self, url: str, params: Optional[dict] = None) -> str:
        if not params:
            return url
        query = urllib.parse.urlencode(params)
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{query}"
