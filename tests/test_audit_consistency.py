"""Core verdicts stay stable across workers and cache replay."""

import tempfile
import unittest

from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.verification import CitationRecord, audit_citations
from citeguard.verification.cache import CachingMetadataSource


def _core_verdicts(report):
    return [
        (
            result.verdict.value,
            result.canonical_record.title if result.canonical_record is not None else None,
            result.canonical_record.year if result.canonical_record is not None else None,
        )
        for result in report.results
    ]


class AuditConsistencyTests(unittest.TestCase):
    def test_single_thread_multi_thread_and_cache_replay_agree(self):
        records = [
            CitationRecord(
                citation_id=f"paper-{index}",
                title=f"Consistency Paper {index}",
                authors=["Ada Lovelace"],
                year=2017 + index,
                doi=f"10.5555/consistency-{index}",
                source="memory",
            )
            for index in range(4)
        ]
        candidates = [
            CitationRecord(
                citation_id=f"cand-{index}",
                title=record.title,
                year=record.year,
                doi=record.doi,
                metadata={"title_explicit": True},
            )
            for index, record in enumerate(records)
        ]
        source = InMemoryMetadataSource(records)

        single = audit_citations(candidates, source, max_workers=1)
        multi = audit_citations(candidates, source, max_workers=4)
        self.assertEqual(_core_verdicts(single), _core_verdicts(multi))

        with tempfile.TemporaryDirectory() as tmp:
            cached = CachingMetadataSource(source, db_path=f"{tmp}/cache.sqlite")
            first = audit_citations(candidates, cached, max_workers=1)
            replay = audit_citations(candidates, cached, max_workers=4)
        self.assertEqual(_core_verdicts(single), _core_verdicts(first))
        self.assertEqual(_core_verdicts(first), _core_verdicts(replay))


if __name__ == "__main__":
    unittest.main()
