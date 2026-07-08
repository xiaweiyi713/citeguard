"""Tests for the scholarly HTTP client retry and diagnostics behavior."""

from __future__ import annotations

import io
import urllib.error
import unittest
from email.utils import formatdate
from unittest import mock

from citeguard.retrieval.scholarly_clients import HTTPClient


class _Response:
    def __init__(self, payload: str, status: int = 200, final_url: str = ""):
        self.payload = payload.encode("utf-8")
        self.status = status
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload

    def geturl(self):
        return self.final_url


def _http_error(code: int, retry_after: str = ""):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("https://example.test", code, "error", headers, io.BytesIO())


class HTTPClientTests(unittest.TestCase):
    def test_retries_transient_http_errors_and_returns_success(self):
        sleeps = []
        client = HTTPClient(retries=1, retry_backoff=0.0, sleep=sleeps.append)
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=[_http_error(503), _Response('{"ok": true}')],
        ) as urlopen:
            payload = client.get_text("https://example.test")

        self.assertEqual(payload, '{"ok": true}')
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(client.last_error, "")
        self.assertEqual(client.last_status_code, 200)
        self.assertEqual(client.last_attempt_count, 2)
        self.assertEqual(client.last_retry_count, 1)
        self.assertIsNone(client.last_retry_after_seconds)

    def test_records_final_url_after_redirect(self):
        client = HTTPClient(retries=0, retry_backoff=0.0)
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=[_Response("ok", final_url="https://publisher.example/article")],
        ):
            payload = client.get_text("https://doi.org/10.5555/redirect")

        self.assertEqual(payload, "ok")
        self.assertEqual(client.last_url, "https://doi.org/10.5555/redirect")
        self.assertEqual(client.last_final_url, "https://publisher.example/article")
        self.assertTrue(client.last_redirected)

    def test_respects_retry_after_with_upper_bound(self):
        sleeps = []
        client = HTTPClient(retries=1, retry_backoff=0.1, retry_after_max=2.0, sleep=sleeps.append)
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=[_http_error(429, retry_after="10"), _Response("ok")],
        ):
            payload = client.get_text("https://example.test")

        self.assertEqual(payload, "ok")
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(client.last_error_code, "")
        self.assertEqual(client.last_error_kind, "")
        self.assertIsNone(client.last_retry_after_seconds)
        self.assertEqual(client.last_retry_delay_seconds, 2.0)

    def test_rate_limit_records_machine_readable_source_failure(self):
        client = HTTPClient(retries=0, retry_backoff=0.0)
        with mock.patch("urllib.request.urlopen", side_effect=[_http_error(429, retry_after="1")]):
            payload = client.get_text("https://example.test")

        self.assertEqual(payload, "")
        self.assertEqual(client.last_error, "http_429")
        self.assertEqual(client.last_error_code, "source_unavailable")
        self.assertEqual(client.last_error_kind, "rate_limited")
        self.assertEqual(client.last_status_code, 429)
        self.assertEqual(client.last_attempt_count, 1)
        self.assertEqual(client.last_retry_count, 0)
        self.assertEqual(client.last_retry_after_seconds, 1.0)
        self.assertIsNone(client.last_retry_delay_seconds)

    def test_rate_limit_accepts_retry_after_http_date(self):
        retry_after = formatdate(1005.0, usegmt=True)
        client = HTTPClient(retries=0, retry_backoff=0.0)
        with mock.patch("citeguard.retrieval.scholarly_clients.http.time.time", return_value=1000.0):
            with mock.patch("urllib.request.urlopen", side_effect=[_http_error(429, retry_after=retry_after)]):
                payload = client.get_text("https://example.test")

        self.assertEqual(payload, "")
        self.assertEqual(client.last_error_kind, "rate_limited")
        self.assertEqual(client.last_retry_after_seconds, 5.0)

    def test_past_retry_after_http_date_is_zero_wait_hint(self):
        retry_after = formatdate(995.0, usegmt=True)
        client = HTTPClient(retries=0, retry_backoff=0.0)
        with mock.patch("citeguard.retrieval.scholarly_clients.http.time.time", return_value=1000.0):
            with mock.patch("urllib.request.urlopen", side_effect=[_http_error(429, retry_after=retry_after)]):
                payload = client.get_text("https://example.test")

        self.assertEqual(payload, "")
        self.assertEqual(client.last_error_kind, "rate_limited")
        self.assertEqual(client.last_retry_after_seconds, 0.0)

    def test_timeout_records_machine_readable_timeout(self):
        client = HTTPClient(retries=0, retry_backoff=0.0)
        with mock.patch("urllib.request.urlopen", side_effect=[TimeoutError("slow")]):
            payload = client.get_text("https://example.test")

        self.assertEqual(payload, "")
        self.assertEqual(client.last_error, "TimeoutError")
        self.assertEqual(client.last_error_code, "timeout")
        self.assertEqual(client.last_error_kind, "timeout")

    def test_does_not_retry_non_transient_http_errors(self):
        client = HTTPClient(retries=3, retry_backoff=0.0)
        with mock.patch("urllib.request.urlopen", side_effect=[_http_error(404)]) as urlopen:
            payload = client.get_text("https://example.test")

        self.assertEqual(payload, "")
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(client.last_error, "http_404")
        self.assertEqual(client.last_error_code, "source_unavailable")
        self.assertEqual(client.last_error_kind, "http_error")
        self.assertEqual(client.last_status_code, 404)

    def test_get_json_uses_retrying_text_fetch(self):
        client = HTTPClient(retries=1, retry_backoff=0.0)
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=[TimeoutError("slow"), _Response('{"answer": 42}')],
        ):
            payload = client.get_json("https://example.test")

        self.assertEqual(payload["answer"], 42)

    def test_get_json_records_malformed_source_json(self):
        client = HTTPClient(retries=0, retry_backoff=0.0)
        with mock.patch("urllib.request.urlopen", side_effect=[_Response("{not json}")]):
            payload = client.get_json("https://example.test")

        self.assertEqual(payload, {})
        self.assertEqual(client.last_status_code, 200)
        self.assertEqual(client.last_error, "JSONDecodeError")
        self.assertEqual(client.last_error_code, "source_unavailable")
        self.assertEqual(client.last_error_kind, "invalid_json")
        self.assertEqual(client.last_attempt_count, 1)
        self.assertEqual(client.last_retry_count, 0)

    def test_cache_hit_clears_stale_source_failure_diagnostics(self):
        client = HTTPClient(retries=0, retry_backoff=0.0)
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=[_Response("cached"), _http_error(503)],
        ) as urlopen:
            self.assertEqual(client.get_text("https://example.test/cached"), "cached")
            self.assertEqual(client.get_text("https://example.test/fails"), "")
            self.assertEqual(client.last_error_code, "source_unavailable")
            self.assertEqual(client.get_text("https://example.test/cached"), "cached")

        self.assertEqual(urlopen.call_count, 2)
        self.assertTrue(client.last_cache_hit)
        self.assertEqual(client.last_url, "https://example.test/cached")
        self.assertEqual(client.last_final_url, "https://example.test/cached")
        self.assertFalse(client.last_redirected)
        self.assertEqual(client.last_attempt_count, 0)
        self.assertEqual(client.last_retry_count, 0)
        self.assertIsNone(client.last_retry_after_seconds)
        self.assertIsNone(client.last_retry_delay_seconds)
        self.assertEqual(client.last_error, "")
        self.assertEqual(client.last_error_code, "")
        self.assertEqual(client.last_error_kind, "")
        self.assertIsNone(client.last_status_code)

    def test_min_interval_waits_between_uncached_network_requests(self):
        sleeps = []
        now = [100.0]

        def sleep(delay):
            sleeps.append(delay)
            now[0] += delay

        client = HTTPClient(
            retries=0,
            retry_backoff=0.0,
            min_interval=0.5,
            sleep=sleep,
            clock=lambda: now[0],
        )
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=[_Response("first"), _Response("second")],
        ):
            self.assertEqual(client.get_text("https://example.test/one"), "first")
            self.assertEqual(client.get_text("https://example.test/two"), "second")

        self.assertEqual(sleeps, [0.5])


if __name__ == "__main__":
    unittest.main()
