"""Small HTTP helper with in-process caching for scholarly adapters."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Dict, Optional

from citeguard.version import __version__

DEFAULT_HTTP_USER_AGENT = f"CiteGuard/{__version__}"


#: Per-request diagnostics that callers read back immediately after a call
#: (``resolve._identifier_authority``, ``multi_source._source_failure_detail``,
#: ``support_reporting``, ``runtime_health``). They describe *one* request, so
#: they are stored per thread: batch verification shares one client across
#: worker threads, and process-wide diagnostics would attribute one citation's
#: outage to another. Shared-by-design state (the response cache, the
#: polite-pool rate limiter) deliberately stays shared.
_REQUEST_DIAGNOSTIC_DEFAULTS = {
    "last_error": "",
    "last_error_code": "",
    "last_error_kind": "",
    "last_status_code": None,
    "last_url": "",
    "last_final_url": "",
    "last_redirected": False,
    "last_cache_hit": False,
    "last_attempt_count": 0,
    "last_retry_count": 0,
    "last_retry_after_seconds": None,
    "last_retry_delay_seconds": None,
}


def _diagnostic_property(name: str):
    default = _REQUEST_DIAGNOSTIC_DEFAULTS[name]

    def getter(self):
        return getattr(self._diagnostics, name, default)

    def setter(self, value):
        setattr(self._diagnostics, name, value)

    return property(getter, setter)


class HTTPClient:
    """A small wrapper around urllib with caching, short retries, and diagnostics.

    Thread-safety: an instance may be shared across threads. The response cache
    and rate limiter are shared on purpose; per-request diagnostics
    (``last_error_code`` and friends) are thread-local so concurrent callers
    never read each other's failure provenance.
    """

    RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

    last_error = _diagnostic_property("last_error")
    last_error_code = _diagnostic_property("last_error_code")
    last_error_kind = _diagnostic_property("last_error_kind")
    last_status_code = _diagnostic_property("last_status_code")
    last_url = _diagnostic_property("last_url")
    last_final_url = _diagnostic_property("last_final_url")
    last_redirected = _diagnostic_property("last_redirected")
    last_cache_hit = _diagnostic_property("last_cache_hit")
    last_attempt_count = _diagnostic_property("last_attempt_count")
    last_retry_count = _diagnostic_property("last_retry_count")
    last_retry_after_seconds = _diagnostic_property("last_retry_after_seconds")
    last_retry_delay_seconds = _diagnostic_property("last_retry_delay_seconds")

    def _record_failure(self, code: str, kind: str, error: str) -> None:
        """Record failure diagnostics for the calling thread."""

        self.last_error_code = code
        self.last_error_kind = kind
        self.last_error = error

    def __init__(
        self,
        timeout: int = 15,
        user_agent: Optional[str] = None,
        retries: int = 1,
        retry_backoff: float = 0.2,
        retry_after_max: float = 2.0,
        min_interval: float = 0.0,
        sleep: Optional[Callable[[float], None]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent or DEFAULT_HTTP_USER_AGENT
        self.retries = max(0, int(retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.retry_after_max = max(0.0, float(retry_after_max))
        self.min_interval = max(0.0, float(min_interval))
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        # Per-thread request diagnostics; see _REQUEST_DIAGNOSTIC_DEFAULTS.
        self._diagnostics = threading.local()
        # Shared on purpose: the response cache and the polite-pool interval
        # must apply across every caller of this client.
        self._rate_limit_lock = threading.Lock()
        self._last_request_monotonic: Optional[float] = None
        self._cache: Dict[str, str] = {}

    def get_text(
        self,
        url: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        use_cache: bool = True,
        timeout: Optional[int] = None,
        url_validator: Optional[Callable[[str], bool]] = None,
    ) -> str:
        full_url = self._build_url(url, params)
        if url_validator is not None and not url_validator(full_url):
            self._set_blocked_url(full_url)
            return ""
        if use_cache and full_url in self._cache:
            self._clear_error()
            self.last_status_code = None
            self.last_url = full_url
            self.last_final_url = full_url
            self.last_redirected = False
            self.last_cache_hit = True
            self.last_attempt_count = 0
            self.last_retry_count = 0
            self.last_retry_after_seconds = None
            self.last_retry_delay_seconds = None
            return self._cache[full_url]

        self._clear_error()
        self.last_status_code = None
        self.last_url = full_url
        self.last_final_url = full_url
        self.last_redirected = False
        self.last_cache_hit = False
        self.last_attempt_count = 0
        self.last_retry_count = 0
        self.last_retry_after_seconds = None
        self.last_retry_delay_seconds = None
        request_headers = {"User-Agent": self.user_agent}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(full_url, headers=request_headers)
        payload = ""
        for attempt in range(self.retries + 1):
            self.last_attempt_count = attempt + 1
            self.last_retry_count = attempt
            try:
                self._sleep_for_min_interval()
                if url_validator is None:
                    response_context = urllib.request.urlopen(request, timeout=timeout or self.timeout)  # nosec B310
                else:
                    response_context = open_validated_request(
                        request,
                        timeout=timeout or self.timeout,
                        validator=url_validator,
                    )
                with response_context as response:
                    self._last_request_monotonic = self.clock()
                    self.last_status_code = getattr(response, "status", None) or getattr(response, "code", None)
                    self.last_final_url = getattr(response, "geturl", lambda: full_url)() or full_url
                    self.last_redirected = self.last_final_url != full_url
                    payload = response.read().decode("utf-8")
                    self._clear_error()
                    break
            except urllib.error.HTTPError as exc:
                self._last_request_monotonic = self.clock()
                self.last_status_code = exc.code
                self.last_final_url = getattr(exc, "url", "") or full_url
                self.last_redirected = self.last_final_url != full_url
                self.last_error = f"http_{exc.code}"
                self.last_error_code = "source_unavailable"
                self.last_error_kind = "rate_limited" if exc.code == 429 else "http_error"
                self.last_retry_after_seconds = _retry_after_seconds(exc)
                if not self._should_retry_http_error(exc, attempt):
                    return ""
                self._sleep_before_retry(exc, attempt)
            except Exception as exc:
                self._last_request_monotonic = self.clock()
                self.last_final_url = full_url
                self.last_redirected = False
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
        except json.JSONDecodeError as exc:
            self.last_error = exc.__class__.__name__
            self.last_error_code = "source_unavailable"
            self.last_error_kind = "invalid_json"
            return {}

    def _build_url(self, url: str, params: Optional[dict] = None) -> str:
        if not params:
            return url
        query = urllib.parse.urlencode(params)
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{query}"

    def _set_blocked_url(self, url: str) -> None:
        self._clear_error()
        self.last_url = url
        self.last_final_url = url
        self.last_redirected = False
        self.last_cache_hit = False
        self.last_error = "blocked_unsafe_url"
        self.last_error_code = "source_unavailable"
        self.last_error_kind = "unsafe_url"

    def _should_retry_http_error(self, exc: urllib.error.HTTPError, attempt: int) -> bool:
        return attempt < self.retries and exc.code in self.RETRY_STATUS_CODES

    def _sleep_before_retry(self, exc: Optional[urllib.error.HTTPError], attempt: int) -> None:
        delay = self.retry_backoff * (2 ** attempt)
        retry_after = _retry_after_seconds(exc) if exc is not None else None
        if retry_after is not None:
            delay = max(delay, min(retry_after, self.retry_after_max))
        self.last_retry_delay_seconds = delay
        if delay > 0:
            self.sleep(delay)

    def _sleep_for_min_interval(self) -> None:
        if self.min_interval <= 0 or self._last_request_monotonic is None:
            return
        elapsed = self.clock() - self._last_request_monotonic
        delay = self.min_interval - elapsed
        if delay > 0:
            self.sleep(delay)

    def _clear_error(self) -> None:
        self.last_error = ""
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_retry_after_seconds = None


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, validator: Callable[[str], bool]) -> None:
        super().__init__()
        self.validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.validator(newurl):
            raise urllib.error.URLError("redirect target is not a safe public URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_validated_request(
    request: urllib.request.Request,
    *,
    timeout: int,
    validator: Callable[[str], bool],
):
    """Open a request only when the initial URL and every redirect are safe."""

    url = request.full_url
    if not validator(url):
        raise urllib.error.URLError("URL is not a safe public URL")
    opener = urllib.request.build_opener(_ValidatingRedirectHandler(validator))
    return opener.open(request, timeout=timeout)


def _retry_after_seconds(exc: urllib.error.HTTPError) -> Optional[float]:
    raw = exc.headers.get("Retry-After") if exc.headers else None
    if raw is None:
        return None
    value = str(raw).strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, retry_at.timestamp() - time.time())
    return seconds if seconds >= 0 else None


def _classify_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", "timeout"
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout", "timeout"
        return "source_unavailable", "network_error"
    return "source_unavailable", "network_error"
