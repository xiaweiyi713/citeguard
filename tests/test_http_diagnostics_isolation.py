"""Per-request diagnostics must not leak between concurrent callers of one HTTPClient.

Batch verification (`audit_citations`) fans out across citations with a thread
pool while every worker drives the *same* adapter instances, so one `HTTPClient`
is shared. Failure provenance (`last_error_code` and friends) is read back right
after each call by `resolve._identifier_authority`,
`multi_source._source_failure_detail`, `support_reporting`, and
`runtime_health`. When that state was process-wide, one citation's timeout was
reported as another citation's `sources_failed` — a real bibliography audit
produced a result claiming `identifier_lookup.status=miss` (the source answered)
and `sources_failed=["arxiv"]` (the source failed) simultaneously, with a
borrowed `outage_limited=true`.

Two properties are required, and both are tested here:

1. Threads running concurrently must not see each other's diagnostics.
2. A thread reused by a pool must not carry diagnostics from its previous task
   (thread-local storage alone does not give this; every request must reset).

Shared-by-design state (the response cache, the polite-pool rate limiter) must
stay shared.
"""

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from citeguard.retrieval.scholarly_clients.http import HTTPClient


class HTTPDiagnosticsIsolationTests(unittest.TestCase):
    def test_diagnostics_do_not_leak_between_concurrent_threads(self):
        client = HTTPClient(timeout=1, retries=0)
        client._cache["https://example.invalid/ok"] = "body"
        seen = {}
        started = threading.Event()

        def failing_thread():
            client._record_failure("timeout", "timeout", "TimeoutError")
            started.set()
            seen["failing"] = client.last_error_code

        def clean_thread():
            started.wait(timeout=5)
            client.get_text("https://example.invalid/ok")
            seen["clean_error"] = client.last_error_code
            seen["clean_hit"] = client.last_cache_hit

        first = threading.Thread(target=failing_thread)
        second = threading.Thread(target=clean_thread)
        first.start()
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)

        self.assertEqual(seen["failing"], "timeout", "the failing thread must see its own failure")
        self.assertEqual(seen["clean_error"], "", "a successful thread must not inherit another's failure")
        self.assertTrue(seen["clean_hit"])

    def test_pooled_thread_does_not_reuse_previous_task_diagnostics(self):
        # A pool reuses worker threads, so thread-local storage alone is not
        # enough: each request must reset its own diagnostics.
        client = HTTPClient(timeout=1, retries=0)
        client._cache["https://example.invalid/ok"] = "body"
        codes = []

        def failing_task():
            client._record_failure("timeout", "timeout", "TimeoutError")

        def clean_task():
            client.get_text("https://example.invalid/ok")
            codes.append(client.last_error_code)

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(failing_task).result()
            pool.submit(clean_task).result()

        self.assertEqual(codes, [""], "a reused worker must not report the previous task's failure")

    def test_response_cache_is_still_shared_across_threads(self):
        client = HTTPClient(timeout=1, retries=0)
        client._cache["https://example.invalid/x"] = "cached-body"
        results = []

        def read_cached():
            results.append(client.get_text("https://example.invalid/x"))

        threads = [threading.Thread(target=read_cached) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(results, ["cached-body", "cached-body"])

    def test_untouched_thread_sees_clean_defaults(self):
        client = HTTPClient(timeout=1, retries=0)
        client._record_failure("timeout", "timeout", "TimeoutError")
        observed = {}

        def idle_thread():
            observed["code"] = client.last_error_code
            observed["hit"] = client.last_cache_hit
            observed["status"] = client.last_status_code

        thread = threading.Thread(target=idle_thread)
        thread.start()
        thread.join(timeout=5)

        self.assertEqual(observed["code"], "")
        self.assertFalse(observed["hit"])
        self.assertIsNone(observed["status"])


if __name__ == "__main__":
    unittest.main()
