"""Small HTTP helper with in-process caching for scholarly adapters."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, Optional

from citeguard.version import __version__

DEFAULT_HTTP_USER_AGENT = f"CiteGuard/{__version__}"


class HTTPClient:
    """A small wrapper around urllib with caching, short retries, and diagnostics."""

    RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        timeout: int = 15,
        user_agent: Optional[str] = None,
        retries: int = 1,
        retry_backoff: float = 0.2,
        retry_after_max: float = 2.0,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent or DEFAULT_HTTP_USER_AGENT
        self.retries = max(0, int(retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.retry_after_max = max(0.0, float(retry_after_max))
        self.sleep = sleep or time.sleep
        self.last_error = ""
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_status_code: Optional[int] = None
        self.last_url = ""
        self.last_cache_hit = False
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
            self._clear_error()
            self.last_status_code = None
            self.last_url = full_url
            self.last_cache_hit = True
            return self._cache[full_url]

        self._clear_error()
        self.last_status_code = None
        self.last_url = full_url
        self.last_cache_hit = False
        request_headers = {"User-Agent": self.user_agent}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(full_url, headers=request_headers)
        payload = ""
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:  # nosec B310
                    self.last_status_code = getattr(response, "status", None) or getattr(response, "code", None)
                    payload = response.read().decode("utf-8")
                    self._clear_error()
                    break
            except urllib.error.HTTPError as exc:
                self.last_status_code = exc.code
                self.last_error = f"http_{exc.code}"
                self.last_error_code = "source_unavailable"
                self.last_error_kind = "rate_limited" if exc.code == 429 else "http_error"
                if not self._should_retry_http_error(exc, attempt):
                    return ""
                self._sleep_before_retry(exc, attempt)
            except Exception as exc:
                self.last_error = exc.__class__.__name__
                self.last_error_code, self.last_error_kind = _classify_exception(exc)
                if attempt >= self.retries:
                    return ""
                self._sleep_before_retry(None, attempt)

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

    def _should_retry_http_error(self, exc: urllib.error.HTTPError, attempt: int) -> bool:
        return attempt < self.retries and exc.code in self.RETRY_STATUS_CODES

    def _sleep_before_retry(self, exc: Optional[urllib.error.HTTPError], attempt: int) -> None:
        delay = self.retry_backoff * (2 ** attempt)
        retry_after = _retry_after_seconds(exc) if exc is not None else None
        if retry_after is not None:
            delay = max(delay, min(retry_after, self.retry_after_max))
        if delay > 0:
            self.sleep(delay)

    def _clear_error(self) -> None:
        self.last_error = ""
        self.last_error_code = ""
        self.last_error_kind = ""


def _retry_after_seconds(exc: urllib.error.HTTPError) -> Optional[float]:
    raw = exc.headers.get("Retry-After") if exc.headers else None
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except ValueError:
        return None
    return value if value >= 0 else None


def _classify_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", "timeout"
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout", "timeout"
        return "source_unavailable", "network_error"
    return "source_unavailable", "network_error"
