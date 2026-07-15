"""Polluted/hijacked records must degrade to ambiguous, never confident mismatch."""

import unittest

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource
from citeguard.verification.models import Verdict
from citeguard.verification.parse import parse_citation
from citeguard.verification.resolve import is_suspect_record, resolve_citation
from citeguard.verification.verify import verify_citation


TRUE_2017 = CitationRecord(citation_id="real", title="Attention Is All You Need",
                           authors=["Ashish Vaswani"], year=2017, source="crossref")
JUNK_2025 = CitationRecord(citation_id="junk", title="Attention Is All You Need",
                           authors=["Ashish Vaswani"], year=2025, doi="10.65215/2q58a426",
                           source="openalex", metadata={"cited_by_count": 6583})


class _Named(InMemoryMetadataSource):
    def __init__(self, records, name):
        super().__init__(records)
        self.name = name


class SuspectHeuristicTests(unittest.TestCase):
    def test_greylisted_doi_prefix_is_suspect(self):
        self.assertTrue(is_suspect_record(JUNK_2025, now_year=2026))

    def test_huge_citations_on_brand_new_year_is_suspect(self):
        record = CitationRecord(citation_id="x", title="T", year=2026, source="s",
                                metadata={"cited_by_count": 5000})
        self.assertTrue(is_suspect_record(record, now_year=2026))

    def test_normal_record_not_suspect(self):
        self.assertFalse(is_suspect_record(TRUE_2017, now_year=2026))

    def test_old_paper_with_many_citations_not_suspect(self):
        record = CitationRecord(citation_id="y", title="T", year=2017, source="s",
                                metadata={"cited_by_count": 90000})
        self.assertFalse(is_suspect_record(record, now_year=2026))


class YearConflictTests(unittest.TestCase):
    def test_cross_source_year_conflict_degrades_to_ambiguous(self):
        source = MultiSourceMetadataSource([_Named([TRUE_2017], "crossref"), _Named([JUNK_2025], "openalex")])
        candidate = parse_citation(title="Attention Is All You Need", year=2017)  # no identifier
        outcome = resolve_citation(candidate, source)
        self.assertTrue(outcome.ambiguous)
        self.assertEqual(outcome.ambiguity_reason, "year_conflict")
        result = verify_citation(candidate, source)
        self.assertEqual(result.verdict, Verdict.AMBIGUOUS)
        self.assertEqual(result.suggested_citation, "")
        self.assertEqual(result.suggested_bibtex, "")
        self.assertEqual(result.suggested_gbt7714, "")
        self.assertIn("year", result.explanation.lower())

    def test_suspect_only_best_degrades_to_ambiguous(self):
        source = MultiSourceMetadataSource([_Named([JUNK_2025], "openalex")])
        candidate = parse_citation(title="Attention Is All You Need", year=2017)
        result = verify_citation(candidate, source)
        self.assertEqual(result.verdict, Verdict.AMBIGUOUS)
        self.assertEqual(result.suggested_citation, "")

    def test_non_suspect_wins_tie_over_suspect(self):
        # identical title+authors+year -> equal match score; non-suspect must rank first
        twin_true = CitationRecord(citation_id="clean", title="Attention Is All You Need",
                                   authors=["Ashish Vaswani"], year=2017, source="crossref")
        twin_junk = CitationRecord(citation_id="dirty", title="Attention Is All You Need",
                                   authors=["Ashish Vaswani"], year=2017, doi="10.65215/aaaa",
                                   source="openalex")
        source = MultiSourceMetadataSource([_Named([twin_junk], "openalex"), _Named([twin_true], "crossref")])
        outcome = resolve_citation(parse_citation(title="Attention Is All You Need", year=2017), source)
        self.assertEqual(outcome.best.citation_id, "clean")

    def test_identifier_hit_overrides_year_conflict(self):
        # with an identifier hit the consensus downgrade must NOT fire (id is definitive)
        from tests.test_identifier_authority import _HitIdentifierSource, AIAYN_TRUE

        arxiv = _HitIdentifierSource([], "arxiv", AIAYN_TRUE)
        openalex = _Named([JUNK_2025], "openalex")
        candidate = parse_citation(title="Attention Is All You Need", arxiv_id="1706.03762", year=2017)
        result = verify_citation(candidate, MultiSourceMetadataSource([openalex, arxiv]))
        self.assertEqual(result.verdict, Verdict.VERIFIED)


if __name__ == "__main__":
    unittest.main()
