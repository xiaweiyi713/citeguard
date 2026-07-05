"""Tests for multi-source scholarly adapters."""

import unittest

from citeguard.verification import CitationRecord
from citeguard.retrieval import MetadataSourceRetriever
from citeguard.retrieval.scholarly_clients import (
    ArxivMetadataSource,
    build_live_metadata_source,
    CrossrefMetadataSource,
    InMemoryMetadataSource,
    MultiSourceMetadataSource,
    OpenAlexMetadataSource,
    SemanticScholarMetadataSource,
)
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.retrieval.scholarly_clients.evidence import (
    harvest_remote_evidence,
    harvest_remote_evidence_report,
    is_allowed_remote_evidence_url,
)
from citeguard.version import __version__


class FakeHTTPClient:
    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return {
            "results": [
                {
                    "id": "https://openalex.org/W123",
                    "display_name": "GhostCite: Citation Validity in the Age of Large Language Models",
                    "authorships": [{"author": {"display_name": "Zhe Xu"}}],
                    "publication_year": 2026,
                    "primary_location": {
                        "landing_page_url": "https://example.org/paper",
                        "source": {"display_name": "arXiv"},
                    },
                    "abstract_inverted_index": {
                        "phantom": [0],
                        "references": [1],
                        "and": [2],
                        "fabricated": [3],
                        "metadata": [4],
                    },
                }
            ]
        }

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        if url == "https://example.org/paper":
            return """
            <html>
              <head><meta name="description" content="This paper measures citation validity in large language models." /></head>
              <body>
                <p>We analyze phantom references and fabricated metadata in large language models.</p>
              </body>
            </html>
            """
        return ""


class NullLocationHTTPClient:
    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return {
            "results": [
                {
                    "id": "https://openalex.org/W999",
                    "display_name": "A Paper With No Location Metadata",
                    "authorships": [{"author": {"display_name": "Jane Doe"}}],
                    "publication_year": 2025,
                    "primary_location": None,
                    "best_oa_location": None,
                    "host_venue": None,
                    "abstract_inverted_index": {},
                }
            ]
        }

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return ""


class CountingHTTPClient(FakeHTTPClient):
    def __init__(self):
        self.text_calls = 0
        self.requested_urls = []

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.text_calls += 1
        self.requested_urls.append(url)
        return super().get_text(url, params=params, headers=headers, use_cache=use_cache, timeout=timeout)


class EvidenceTimeoutHTTPClient(FakeHTTPClient):
    def __init__(self):
        self.requested_urls = []
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_status_code = None
        self.last_url = ""
        self.last_error = ""
        self.last_cache_hit = False

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.requested_urls.append(url)
        self.last_error_code = "timeout"
        self.last_error_kind = "timeout"
        self.last_status_code = None
        self.last_url = url
        self.last_error = "TimeoutError"
        self.last_cache_hit = False
        return ""


class CapturingHTTPClient(FakeHTTPClient):
    def __init__(self):
        self.json_calls = []

    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.json_calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "headers": dict(headers or {}),
                "use_cache": use_cache,
                "timeout": timeout,
            }
        )
        return super().get_json(url, params=params, headers=headers, use_cache=use_cache, timeout=timeout)


class CrossrefSparseHTTPClient:
    def __init__(self):
        self.text_calls = []

    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return {
            "message": {
                "items": [
                    {
                        "title": "Sparse Crossref Metadata Should Keep Its Full Title",
                        "container-title": None,
                        "author": [
                            {"given": "Ada", "family": "Lovelace"},
                            None,
                            "not-an-author-object",
                        ],
                        "issued": {"date-parts": [[None], []]},
                        "DOI": "https://doi.org/10.5555/SPARSE",
                        "URL": None,
                        "link": {"URL": "https://publisher.example/sparse"},
                    }
                ]
            }
        }

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.text_calls.append(url)
        return ""


class CrossrefEvidenceTimeoutHTTPClient(CrossrefSparseHTTPClient):
    def __init__(self):
        super().__init__()
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_status_code = None
        self.last_url = ""
        self.last_error = ""
        self.last_cache_hit = False

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.text_calls.append(url)
        self.last_error_code = "timeout"
        self.last_error_kind = "timeout"
        self.last_status_code = None
        self.last_url = url
        self.last_error = "TimeoutError"
        self.last_cache_hit = False
        return ""


class SemanticScholarSparseHTTPClient:
    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return {
            "data": [
                {
                    "paperId": None,
                    "title": "  Sparse Semantic Scholar Metadata  ",
                    "authors": [
                        {"name": "Grace Hopper"},
                        None,
                        "Katherine Johnson",
                        {"name": None},
                    ],
                    "year": "2024",
                    "venue": None,
                    "abstract": None,
                    "externalIds": ["not-a-dict"],
                    "url": None,
                }
            ]
        }

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return ""


class ArxivSparseHTTPClient:
    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>https://arxiv.org/abs/2401.01234v2</id>
            <title>
              Sparse arXiv Metadata Should Stay Usable
            </title>
            <summary>
              This abstract has
              extra whitespace.
            </summary>
            <author><name>Ada Lovelace</name></author>
            <author></author>
            <published>not-a-date</published>
            <arxiv:doi>https://doi.org/10.48550/arxiv.2401.01234</arxiv:doi>
          </entry>
          <entry>
            <title></title>
            <summary></summary>
          </entry>
        </feed>
        """

    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return {}


class RateLimitedHTTPClient:
    def __init__(self):
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_status_code = None
        self.last_url = ""
        self.last_error = ""

    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.last_error_code = "source_unavailable"
        self.last_error_kind = "rate_limited"
        self.last_status_code = 429
        self.last_url = url
        self.last_error = "http_429"
        return {}

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return ""


class TimeoutMetadataSource(MetadataSource):
    name = "timeout_source"

    def all_records(self):
        return []

    def search(self, query, top_k=5):
        raise TimeoutError("source timed out")

    def lookup(self, candidate):
        raise TimeoutError("source timed out")


class ScholarlySourceTests(unittest.TestCase):
    def test_multi_source_search_deduplicates_and_merges_records(self):
        left = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="left-1",
                    title="GhostCite: Citation Validity in the Age of Large Language Models",
                    authors=["Zhe Xu"],
                    year=2026,
                    doi="10.1000/ghostcite",
                )
            ]
        )
        right = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="right-1",
                    title="GhostCite: Citation Validity in the Age of Large Language Models",
                    authors=["Zhe Xu"],
                    year=2026,
                    doi="10.1000/ghostcite",
                    abstract="This paper studies phantom references and fabricated metadata.",
                    venue="arXiv",
                )
            ]
        )

        source = MultiSourceMetadataSource([left, right])
        results = source.search("phantom references fabricated metadata", top_k=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].doi, "10.1000/ghostcite")
        self.assertTrue(results[0].abstract)

    def test_multi_source_records_structured_http_failure_details(self):
        failing = OpenAlexMetadataSource(http_client=RateLimitedHTTPClient())
        source = MultiSourceMetadataSource([failing])

        results = source.search("anything", top_k=1)

        self.assertEqual(results, [])
        self.assertEqual(source.last_failures, ["openalex"])
        self.assertEqual(source.last_failure_details[0]["source"], "openalex")
        self.assertEqual(source.last_failure_details[0]["code"], "source_unavailable")
        self.assertEqual(source.last_failure_details[0]["kind"], "rate_limited")
        self.assertEqual(source.last_failure_details[0]["status_code"], 429)

    def test_multi_source_classifies_direct_timeouts(self):
        source = MultiSourceMetadataSource([TimeoutMetadataSource()])

        results = source.search("anything", top_k=1)

        self.assertEqual(results, [])
        self.assertEqual(source.last_failures, ["timeout_source"])
        self.assertEqual(source.last_failure_details[0]["code"], "timeout")
        self.assertEqual(source.last_failure_details[0]["kind"], "timeout")
        self.assertEqual(source.last_failure_details[0]["error"], "TimeoutError")

    def test_metadata_source_retriever_scores_source_search_results(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="match",
                    title="OpenScholar: Synthesizing Scientific Literature with Retrieval-Augmented Language Models",
                    authors=["Akari Asai"],
                    year=2024,
                    abstract="Scientific literature synthesis and citation hallucinations.",
                ),
                CitationRecord(
                    citation_id="other",
                    title="Generic Language Model Paper",
                    authors=["Other Author"],
                    year=2023,
                    abstract="General language modeling work.",
                ),
            ]
        )
        retriever = MetadataSourceRetriever(source)
        results = retriever.search("scientific literature citation hallucinations", top_k=2)
        self.assertEqual(results[0].citation.citation_id, "match")

    def test_multi_source_lookup_merges_evidence_chunks(self):
        left = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="left-1",
                    title="GhostCite: Citation Validity in the Age of Large Language Models",
                    authors=["Zhe Xu"],
                    year=2026,
                    doi="10.1000/ghostcite",
                    metadata={
                        "evidence_chunks": [
                            {
                                "text": "We analyze phantom references in large language models.",
                                "source_field": "openalex_remote_1_paragraph_1",
                                "source_url": "https://openalex.example/paper",
                            }
                        ]
                    },
                )
            ]
        )
        right = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="right-1",
                    title="GhostCite: Citation Validity in the Age of Large Language Models",
                    authors=["Zhe Xu"],
                    year=2026,
                    doi="10.1000/ghostcite",
                    metadata={
                        "evidence_chunks": [
                            {
                                "text": "The study also measures fabricated metadata across many models.",
                                "source_field": "crossref_remote_1_paragraph_1",
                                "source_url": "https://crossref.example/paper",
                            }
                        ]
                    },
                )
            ]
        )
        source = MultiSourceMetadataSource([left, right])
        match = source.lookup(
            CitationRecord(
                citation_id="candidate",
                title="GhostCite: Citation Validity in the Age of Large Language Models",
                authors=["Zhe Xu"],
                year=2026,
                doi="10.1000/ghostcite",
            )
        )
        self.assertIsNotNone(match)
        self.assertEqual(len(match.metadata["evidence_chunks"]), 2)
        self.assertEqual(len(match.metadata["evidence_spans"]), 2)

    def test_openalex_search_harvests_remote_evidence_chunks(self):
        source = OpenAlexMetadataSource(http_client=FakeHTTPClient())
        results = source.search("phantom references fabricated metadata", top_k=1)
        self.assertEqual(len(results), 1)
        chunks = results[0].metadata.get("evidence_chunks", [])
        self.assertTrue(chunks)
        self.assertTrue(any("phantom references" in chunk["text"].lower() for chunk in chunks))

    def test_openalex_requests_include_configured_mailto(self):
        http_client = CapturingHTTPClient()
        source = OpenAlexMetadataSource(
            mailto="maintainer@example.org",
            http_client=http_client,
            harvest_evidence=False,
        )

        source.search("phantom references fabricated metadata", top_k=1)
        source_for_lookup = OpenAlexMetadataSource(
            mailto="maintainer@example.org",
            http_client=http_client,
            harvest_evidence=False,
        )
        source_for_lookup.lookup(
            CitationRecord(
                citation_id="candidate",
                title="GhostCite",
                doi="10.1000/ghostcite",
            )
        )

        self.assertGreaterEqual(len(http_client.json_calls), 2)
        self.assertEqual(http_client.json_calls[0]["params"]["mailto"], "maintainer@example.org")
        self.assertEqual(http_client.json_calls[1]["params"]["mailto"], "maintainer@example.org")
        self.assertIn("doi:10.1000/ghostcite", http_client.json_calls[1]["params"]["filter"])

    def test_crossref_handles_sparse_or_unexpected_record_shapes(self):
        http_client = CrossrefSparseHTTPClient()
        source = CrossrefMetadataSource(http_client=http_client, harvest_evidence=True)

        results = source.search("sparse crossref metadata", top_k=1)

        self.assertEqual(len(results), 1)
        record = results[0]
        self.assertEqual(record.title, "Sparse Crossref Metadata Should Keep Its Full Title")
        self.assertEqual(record.authors, ["Ada Lovelace"])
        self.assertIsNone(record.year)
        self.assertEqual(record.venue, "")
        self.assertEqual(record.doi, "10.5555/sparse")
        self.assertEqual(record.url, "")
        self.assertEqual(http_client.text_calls, ["https://publisher.example/sparse", "https://doi.org/10.5555/sparse"])

    def test_semantic_scholar_handles_sparse_or_unexpected_record_shapes(self):
        source = SemanticScholarMetadataSource(http_client=SemanticScholarSparseHTTPClient())

        results = source.search("sparse semantic scholar metadata", top_k=1)

        self.assertEqual(len(results), 1)
        record = results[0]
        self.assertEqual(record.title, "Sparse Semantic Scholar Metadata")
        self.assertEqual(record.authors, ["Grace Hopper", "Katherine Johnson"])
        self.assertEqual(record.year, 2024)
        self.assertEqual(record.venue, "")
        self.assertEqual(record.abstract, "")
        self.assertEqual(record.doi, "")
        self.assertEqual(record.url, "")
        self.assertEqual(record.metadata["paper_id"], "")

    def test_arxiv_handles_sparse_atom_entries_and_skips_blank_records(self):
        source = ArxivMetadataSource(http_client=ArxivSparseHTTPClient(), harvest_evidence=False)

        results = source.search("sparse arxiv metadata", top_k=5)

        self.assertEqual(len(results), 1)
        record = results[0]
        self.assertEqual(record.title, "Sparse arXiv Metadata Should Stay Usable")
        self.assertEqual(record.authors, ["Ada Lovelace"])
        self.assertIsNone(record.year)
        self.assertEqual(record.abstract, "This abstract has extra whitespace.")
        self.assertEqual(record.doi, "10.48550/arxiv.2401.01234")
        self.assertEqual(record.arxiv_id, "2401.01234v2")
        self.assertEqual(record.url, "https://arxiv.org/abs/2401.01234v2")

    def test_openalex_can_skip_remote_evidence_harvesting(self):
        http_client = CountingHTTPClient()
        source = OpenAlexMetadataSource(http_client=http_client, harvest_evidence=False)

        results = source.search("phantom references fabricated metadata", top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(http_client.text_calls, 0)
        self.assertEqual(results[0].metadata.get("evidence_chunks", []), [])

    def test_remote_evidence_report_records_nonfatal_fetch_failures(self):
        http_client = EvidenceTimeoutHTTPClient()

        report = harvest_remote_evidence_report(
            http_client,
            urls=["https://example.org/paper"],
            source_name="openalex",
            timeout=1,
        )

        self.assertEqual(report["chunks"], [])
        self.assertEqual(report["failures"][0]["stage"], "remote_evidence")
        self.assertEqual(report["failures"][0]["code"], "timeout")
        self.assertEqual(report["failures"][0]["kind"], "timeout")
        self.assertEqual(report["failures"][0]["url"], "https://example.org/paper")

    def test_openalex_records_remote_evidence_failure_without_source_outage(self):
        source = MultiSourceMetadataSource([OpenAlexMetadataSource(http_client=EvidenceTimeoutHTTPClient())])

        results = source.search("phantom references fabricated metadata", top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(source.last_failures, [])
        failures = results[0].metadata.get("evidence_harvest_failures", [])
        self.assertEqual(failures[0]["stage"], "remote_evidence")
        self.assertEqual(failures[0]["code"], "timeout")
        self.assertEqual(failures[0]["source"], "openalex")
        self.assertEqual(results[0].metadata.get("evidence_chunks", []), [])

    def test_crossref_records_doi_landing_page_timeout_as_evidence_failure(self):
        http_client = CrossrefEvidenceTimeoutHTTPClient()
        source = CrossrefMetadataSource(http_client=http_client, harvest_evidence=True)

        results = source.search("sparse crossref metadata", top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(
            http_client.text_calls,
            ["https://publisher.example/sparse", "https://doi.org/10.5555/sparse"],
        )
        failures = results[0].metadata.get("evidence_harvest_failures", [])
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(failure["stage"] == "remote_evidence" for failure in failures))
        self.assertTrue(all(failure["code"] == "timeout" for failure in failures))

    def test_remote_evidence_skips_blocked_or_non_http_urls(self):
        http_client = CountingHTTPClient()

        chunks = harvest_remote_evidence(
            http_client,
            urls=[
                "https://kns.cnki.net/kcms/detail/example",
                "https://www.wanfangdata.com.cn/details/detail.do",
                "file:///tmp/local.html",
                "https://example.org/paper",
            ],
            source_name="openalex",
            timeout=1,
        )

        self.assertEqual(http_client.requested_urls, ["https://example.org/paper"])
        self.assertTrue(chunks)
        self.assertFalse(is_allowed_remote_evidence_url("https://kns.cnki.net/kcms/detail/example"))
        self.assertFalse(is_allowed_remote_evidence_url("https://www.wanfangdata.com.cn/details/detail.do"))
        self.assertFalse(is_allowed_remote_evidence_url("file:///tmp/local.html"))
        self.assertTrue(is_allowed_remote_evidence_url("https://example.org/paper"))

    def test_factory_passes_remote_evidence_setting_to_sources(self):
        source = build_live_metadata_source(
            ["openalex"],
            harvest_remote_evidence=False,
            http_timeout=3,
            http_retries=2,
            http_retry_backoff=0.5,
            mailto="maintainer@example.org",
        )

        self.assertIsInstance(source, OpenAlexMetadataSource)
        self.assertEqual(source.mailto, "maintainer@example.org")
        self.assertFalse(source.harvest_evidence)
        self.assertEqual(source.http_client.timeout, 3)
        self.assertEqual(source.http_client.user_agent, f"CiteGuard/{__version__} (mailto:maintainer@example.org)")
        self.assertEqual(source.http_client.retries, 2)
        self.assertEqual(source.http_client.retry_backoff, 0.5)

    def test_factory_default_user_agent_avoids_placeholder_contact_url(self):
        source = build_live_metadata_source(["openalex"], harvest_remote_evidence=False)

        self.assertEqual(source.http_client.user_agent, f"CiteGuard/{__version__}")
        self.assertNotIn("example.invalid", source.http_client.user_agent)

    def test_openalex_handles_null_primary_location_and_source(self):
        # OpenAlex routinely returns primary_location or its nested source as JSON
        # null; the adapter must not crash on those records.
        source = OpenAlexMetadataSource(http_client=NullLocationHTTPClient())
        results = source.search("anything", top_k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].venue, "")
        self.assertEqual(results[0].url, "https://openalex.org/W999")


if __name__ == "__main__":
    unittest.main()
