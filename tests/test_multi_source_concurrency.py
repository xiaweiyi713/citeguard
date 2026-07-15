"""Multi-source fan-out must be concurrent and budget-bounded."""

import time
import threading
import unittest

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource


class _SlowSource(InMemoryMetadataSource):
    def __init__(self, records, name, delay):
        super().__init__(records)
        self.name = name
        self.delay = delay

    def search(self, query, top_k=5):
        time.sleep(self.delay)
        return super().search(query, top_k=top_k)

    def lookup(self, candidate):
        time.sleep(self.delay)
        return super().lookup(candidate)


REC_A = CitationRecord(citation_id="a", title="Parallel Fan Out Paper", year=2024, source="s1")
REC_B = CitationRecord(citation_id="b", title="Parallel Fan Out Paper Two", year=2024, source="s2")


class ConcurrencyTests(unittest.TestCase):
    def test_search_runs_sources_in_parallel(self):
        multi = MultiSourceMetadataSource(
            [_SlowSource([REC_A], "s1", 0.4), _SlowSource([REC_B], "s2", 0.4)]
        )
        start = time.perf_counter()
        results = multi.search("parallel fan out paper", top_k=5)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.7)  # serial would be ~0.8s
        self.assertEqual(len(results), 2)

    def test_lookup_runs_sources_in_parallel(self):
        multi = MultiSourceMetadataSource(
            [_SlowSource([REC_A], "s1", 0.4), _SlowSource([REC_B], "s2", 0.4)]
        )
        candidate = CitationRecord(citation_id="c", title="Parallel Fan Out Paper", year=2024)
        start = time.perf_counter()
        multi.lookup(candidate)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.7)

    def test_budget_records_timeout_and_returns_fast_source(self):
        multi = MultiSourceMetadataSource(
            [_SlowSource([REC_A], "fast", 0.05), _SlowSource([REC_B], "slow", 1.5)],
            budget_seconds=0.3,
        )
        start = time.perf_counter()
        results = multi.search("parallel fan out paper", top_k=5)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 1.0)  # must not wait for the slow source
        self.assertTrue(any(record.citation_id == "a" for record in results))
        self.assertIn("slow", multi.last_failures)
        codes = {detail.get("code") for detail in multi.last_failure_details}
        self.assertIn("budget_exceeded", codes)

    def test_failure_details_still_collected_per_source(self):
        class _Boom(InMemoryMetadataSource):
            name = "boom"

            def search(self, query, top_k=5):
                raise TimeoutError("nope")

        multi = MultiSourceMetadataSource([_Boom([]), _SlowSource([REC_A], "ok", 0.01)])
        results = multi.search("parallel fan out paper", top_k=5)
        self.assertTrue(any(record.citation_id == "a" for record in results))
        self.assertIn("boom", multi.last_failures)

    def test_repeated_timeout_never_overlaps_the_same_source(self):
        class _TrackedSlowSource(_SlowSource):
            def __init__(self):
                super().__init__([REC_A], "tracked", 0.35)
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def search(self, query, top_k=5):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                try:
                    return super().search(query, top_k=top_k)
                finally:
                    with self.lock:
                        self.active -= 1

        source = _TrackedSlowSource()
        multi = MultiSourceMetadataSource([source], budget_seconds=0.1)

        multi.search("first")
        started = time.perf_counter()
        multi.search("second")
        second_elapsed = time.perf_counter() - started
        time.sleep(0.4)

        self.assertLess(second_elapsed, 0.2)
        self.assertEqual(source.max_active, 1)
        self.assertEqual(multi.last_failure_details[0]["kind"], "timeout")


if __name__ == "__main__":
    unittest.main()
