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
        self.last_final_url = ""
        self.last_redirected = False
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


class EvidenceRateLimitHTTPClient(FakeHTTPClient):
    def __init__(self):
        self.requested_urls = []
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_status_code = None
        self.last_url = ""
        self.last_final_url = ""
        self.last_redirected = False
        self.last_error = ""
        self.last_cache_hit = False
        self.last_attempt_count = 0
        self.last_retry_count = 0
        self.last_retry_after_seconds = None
        self.last_retry_delay_seconds = None

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.requested_urls.append(url)
        self.last_error_code = "source_unavailable"
        self.last_error_kind = "rate_limited"
        self.last_status_code = 429
        self.last_url = url
        self.last_final_url = "https://publisher.example/rate-limited"
        self.last_redirected = True
        self.last_error = "http_429"
        self.last_cache_hit = False
        self.last_attempt_count = 1
        self.last_retry_count = 0
        self.last_retry_after_seconds = 3.0
        self.last_retry_delay_seconds = None
        return ""


class EvidenceNonHtmlHTTPClient(FakeHTTPClient):
    def __init__(self):
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_status_code = None
        self.last_url = ""
        self.last_final_url = ""
        self.last_redirected = False
        self.last_error = ""
        self.last_cache_hit = False
        self.last_attempt_count = 0
        self.last_retry_count = 0
        self.last_retry_after_seconds = None
        self.last_retry_delay_seconds = None

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.last_status_code = 200
        self.last_url = url
        self.last_final_url = "https://publisher.example/final-landing-page"
        self.last_redirected = True
        self.last_cache_hit = False
        self.last_attempt_count = 1
        self.last_retry_count = 0
        return "%PDF-1.7 publisher landing page returned a PDF shell"


class EvidenceNoExtractableHTMLHTTPClient(FakeHTTPClient):
    def __init__(self):
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_status_code = None
        self.last_url = ""
        self.last_error = ""
        self.last_cache_hit = False
        self.last_attempt_count = 0
        self.last_retry_count = 0
        self.last_retry_after_seconds = None
        self.last_retry_delay_seconds = None

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.last_status_code = 200
        self.last_url = url
        self.last_cache_hit = False
        self.last_attempt_count = 1
        self.last_retry_count = 0
        return "<html><head><title>Publisher</title></head><body><div></div></body></html>"


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


class CrossrefLookupHTTPClient:
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
        return {
            "message": {
                "title": ["Crossref DOI Resolver Normalization"],
                "DOI": "10.5555/MixedCase",
                "issued": {"date-parts": [[2026]]},
            }
        }

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
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


class ArxivLookupHTTPClient:
    def __init__(self):
        self.text_calls = []

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        params = dict(params or {})
        self.text_calls.append({"url": url, "params": params})
        arxiv_id = params.get("id_list", "1706.03762v5")
        return f"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>https://arxiv.org/abs/{arxiv_id}</id>
            <title>Attention Is All You Need</title>
            <summary>Transformer networks use attention mechanisms.</summary>
            <author><name>Ashish Vaswani</name></author>
            <published>2017-06-12T00:00:00Z</published>
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
        self.last_retry_after_seconds = None
        self.last_retry_delay_seconds = None

    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.last_error_code = "source_unavailable"
        self.last_error_kind = "rate_limited"
        self.last_status_code = 429
        self.last_url = url
        self.last_final_url = "https://publisher.example/rate-limited"
        self.last_redirected = True
        self.last_error = "http_429"
        self.last_retry_after_seconds = 3.0
        self.last_retry_delay_seconds = None
        return {}

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return ""


class MalformedJSONHTTPClient:
    def __init__(self):
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_status_code = None
        self.last_url = ""
        self.last_error = ""
        self.last_cache_hit = False
        self.last_attempt_count = 0
        self.last_retry_count = 0
        self.last_retry_after_seconds = None
        self.last_retry_delay_seconds = None

    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.last_error_code = "source_unavailable"
        self.last_error_kind = "invalid_json"
        self.last_status_code = 200
        self.last_url = url
        self.last_error = "JSONDecodeError"
        self.last_cache_hit = False
        self.last_attempt_count = 1
        self.last_retry_count = 0
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
        self.assertEqual(source.last_failure_details[0]["url"], "https://api.openalex.org/works")
        self.assertEqual(source.last_failure_details[0]["final_url"], "https://publisher.example/rate-limited")
        self.assertTrue(source.last_failure_details[0]["redirected"])
        self.assertEqual(source.last_failure_details[0]["attempt_count"], 0)
        self.assertEqual(source.last_failure_details[0]["retry_count"], 0)
        self.assertEqual(source.last_failure_details[0]["retry_after_seconds"], 3.0)
        self.assertIsNone(source.last_failure_details[0]["retry_delay_seconds"])

    def test_multi_source_records_malformed_json_as_source_unavailable(self):
        failing = OpenAlexMetadataSource(http_client=MalformedJSONHTTPClient())
        source = MultiSourceMetadataSource([failing])

        results = source.search("anything", top_k=1)

        self.assertEqual(results, [])
        self.assertEqual(source.last_failures, ["openalex"])
        detail = source.last_failure_details[0]
        self.assertEqual(detail["source"], "openalex")
        self.assertEqual(detail["code"], "source_unavailable")
        self.assertEqual(detail["kind"], "invalid_json")
        self.assertEqual(detail["status_code"], 200)
        self.assertEqual(detail["error"], "JSONDecodeError")
        self.assertEqual(detail["attempt_count"], 1)
        self.assertEqual(detail["retry_count"], 0)

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
                    abstract="This paper studies phantom references and fabricated metadata.",
                    venue="arXiv",
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
        chunk_sources = {chunk["source_field"]: chunk.get("source_name") for chunk in match.metadata["evidence_chunks"]}
        self.assertEqual(chunk_sources["openalex_remote_1_paragraph_1"], "openalex")
        self.assertEqual(chunk_sources["crossref_remote_1_paragraph_1"], "crossref")
        quality = match.metadata["metadata_quality"]
        self.assertIn("identifier", quality["present_fields"])
        self.assertIn("abstract", quality["present_fields"])
        self.assertNotIn("title", quality["missing_fields"])
        self.assertEqual(
            quality["confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )

    def test_openalex_search_harvests_remote_evidence_chunks(self):
        source = OpenAlexMetadataSource(http_client=FakeHTTPClient())
        results = source.search("phantom references fabricated metadata", top_k=1)
        self.assertEqual(len(results), 1)
        chunks = results[0].metadata.get("evidence_chunks", [])
        self.assertTrue(chunks)
        self.assertTrue(any("phantom references" in chunk["text"].lower() for chunk in chunks))
        self.assertTrue(all(chunk.get("source_name") == "openalex" for chunk in chunks))

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

    def test_openalex_omits_unconfigured_mailto(self):
        http_client = CapturingHTTPClient()
        source = OpenAlexMetadataSource(
            mailto="research@example.com",
            http_client=http_client,
            harvest_evidence=False,
        )

        source.search("phantom references fabricated metadata", top_k=1)

        self.assertEqual(source.mailto, "")
        self.assertEqual(http_client.json_calls[0]["params"]["search"], "phantom references fabricated metadata")
        self.assertNotIn("mailto", http_client.json_calls[0]["params"])

    def test_doi_registry_probe_reports_registered_doi_with_resolution_url(self):
        class HandleHTTPClient(FakeHTTPClient):
            def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
                self.last_error = ""
                return {
                    "responseCode": 1,
                    "handle": "10.1360/ssi-2020-0204",
                    "values": [
                        {"index": 1, "type": "URL", "data": {"format": "string", "value": "https://www.sciengine.com/SSI/doi/10.1360/SSI-2020-0204"}}
                    ],
                }

        from citeguard.retrieval.scholarly_clients.doi_registry import DoiRegistryProbe

        probe = DoiRegistryProbe(http_client=HandleHTTPClient())
        result = probe.check("https://doi.org/10.1360/SSI-2020-0204")

        self.assertTrue(result["checked"])
        self.assertTrue(result["registered"])
        self.assertEqual(result["status"], "registered")
        self.assertEqual(result["doi"], "10.1360/ssi-2020-0204")
        self.assertIn("sciengine.com", result["resolution_url"])
        self.assertIn("not_full_verification", result["interpretation"])

    def test_doi_registry_probe_reports_unregistered_doi_conservatively(self):
        class MissingHandleHTTPClient(FakeHTTPClient):
            def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
                self.last_error = ""
                return {"responseCode": 100, "handle": "10.9999/fake"}

        from citeguard.retrieval.scholarly_clients.doi_registry import DoiRegistryProbe

        probe = DoiRegistryProbe(http_client=MissingHandleHTTPClient())
        result = probe.check("10.9999/fake")

        self.assertTrue(result["checked"])
        self.assertFalse(result["registered"])
        self.assertIn("not_fabrication_proof", result["interpretation"])

    def test_doi_registry_probe_maps_http_404_to_not_registered(self):
        class NotFoundHTTPClient(FakeHTTPClient):
            def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
                self.last_error = "http_404"
                self.last_status_code = 404
                return {}

        from citeguard.retrieval.scholarly_clients.doi_registry import DoiRegistryProbe

        probe = DoiRegistryProbe(http_client=NotFoundHTTPClient())
        result = probe.check("10.9999/fake-2099")

        self.assertTrue(result["checked"])
        self.assertFalse(result["registered"])
        self.assertEqual(result["status"], "not_registered")

    def test_doi_registry_probe_treats_outage_as_no_conclusion(self):
        class FailingHTTPClient(FakeHTTPClient):
            def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
                self.last_error = "timeout"
                return {}

        from citeguard.retrieval.scholarly_clients.doi_registry import DoiRegistryProbe

        probe = DoiRegistryProbe(http_client=FailingHTTPClient())
        result = probe.check("10.1360/ssi-2020-0204")

        self.assertFalse(result["checked"])
        self.assertIsNone(result["registered"])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["detail"], "timeout")

    def test_crossref_skips_mostly_cjk_search_queries_without_http_calls(self):
        http_client = CapturingHTTPClient()
        source = CrossrefMetadataSource(http_client=http_client, harvest_evidence=False)

        results = source.search("迈向第三代人工智能", top_k=3)

        self.assertEqual(results, [])
        self.assertEqual(http_client.json_calls, [])

    def test_crossref_still_searches_mixed_and_english_queries(self):
        http_client = CapturingHTTPClient()
        source = CrossrefMetadataSource(http_client=http_client, harvest_evidence=False)

        source.search("BERT pretraining survey 大模型", top_k=2)

        self.assertEqual(len(http_client.json_calls), 1)

    def test_crossref_cjk_candidate_with_doi_still_resolves_via_lookup(self):
        http_client = CrossrefLookupHTTPClient()
        source = CrossrefMetadataSource(http_client=http_client, harvest_evidence=False)

        record = source.lookup(
            CitationRecord(
                citation_id="candidate-zh",
                title="迈向第三代人工智能",
                authors=["张钹"],
                year=2020,
                venue="",
                abstract="",
                doi="10.5555/resolver",
                source="input",
            )
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.doi, "10.5555/mixedcase")

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
        quality = record.metadata["metadata_quality"]
        self.assertEqual(quality["schema_version"], 1)
        self.assertIn("year", quality["missing_fields"])
        self.assertIn("venue", quality["missing_fields"])
        self.assertIn("abstract", quality["missing_fields"])
        self.assertIn("url", quality["missing_fields"])
        self.assertIn("identifier", quality["present_fields"])
        self.assertTrue(quality["identifiers"]["doi"])
        self.assertEqual(
            quality["confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )

    def test_crossref_lookup_normalizes_common_doi_resolver_prefixes(self):
        http_client = CrossrefLookupHTTPClient()
        source = CrossrefMetadataSource(http_client=http_client, harvest_evidence=False)

        record = source.lookup(
            CitationRecord(
                citation_id="candidate",
                title="Crossref DOI Resolver Normalization",
                doi="DOI: HTTPS://DX.DOI.ORG/10.5555/MixedCase.",
            )
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.doi, "10.5555/mixedcase")
        self.assertEqual(
            http_client.json_calls[0]["url"],
            "https://api.crossref.org/works/10.5555%2Fmixedcase",
        )

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
        quality = record.metadata["metadata_quality"]
        self.assertIn("venue", quality["missing_fields"])
        self.assertIn("abstract", quality["missing_fields"])
        self.assertIn("identifier", quality["missing_fields"])
        self.assertIn("url", quality["missing_fields"])
        self.assertFalse(quality["identifiers"]["doi"])
        self.assertFalse(quality["identifiers"]["arxiv_id"])
        self.assertEqual(
            quality["confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )

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
        quality = record.metadata["metadata_quality"]
        self.assertIn("year", quality["missing_fields"])
        self.assertIn("identifier", quality["present_fields"])
        self.assertTrue(quality["identifiers"]["arxiv_id"])
        self.assertEqual(
            quality["confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )

    def test_arxiv_lookup_normalizes_common_arxiv_url_forms(self):
        cases = {
            "HTTPS://ARXIV.ORG/PDF/1706.03762V5.PDF.": "1706.03762v5",
            "https://arxiv.org/abs/hep-th/9901001V2": "hep-th/9901001v2",
            "arXiv: math.AG/0601001": "math.ag/0601001",
        }
        for arxiv_id, expected in cases.items():
            with self.subTest(arxiv_id=arxiv_id):
                http_client = ArxivLookupHTTPClient()
                source = ArxivMetadataSource(http_client=http_client, harvest_evidence=False)

                record = source.lookup(
                    CitationRecord(
                        citation_id="candidate",
                        title="Attention Is All You Need",
                        arxiv_id=arxiv_id,
                    )
                )

                self.assertIsNotNone(record)
                self.assertEqual(record.arxiv_id, expected)
                self.assertEqual(http_client.text_calls[0]["params"]["id_list"], expected)

    def test_in_memory_lookup_normalizes_identifier_url_forms(self):
        record = CitationRecord(
            citation_id="fixture",
            title="Attention Is All You Need",
            doi="10.48550/arxiv.1706.03762",
            arxiv_id="1706.03762v5",
        )
        source = InMemoryMetadataSource([record])

        self.assertIs(
            source.lookup(
                CitationRecord(
                    citation_id="candidate",
                    title="",
                    arxiv_id="https://arxiv.org/pdf/1706.03762v5.pdf",
                )
            ),
            record,
        )

        old_style_record = CitationRecord(
            citation_id="old-fixture",
            title="Old Style arXiv Fixture",
            arxiv_id="math.AG/0601001v2",
        )
        old_style_source = InMemoryMetadataSource([old_style_record])
        self.assertIs(
            old_style_source.lookup(
                CitationRecord(
                    citation_id="candidate",
                    title="",
                    arxiv_id="https://arxiv.org/abs/math.AG/0601001V2",
                )
            ),
            old_style_record,
        )
        self.assertIs(
            source.lookup(
                CitationRecord(
                    citation_id="candidate",
                    title="",
                    doi="DOI: https://doi.org/10.48550/arxiv.1706.03762",
                )
            ),
            record,
        )

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

    def test_remote_evidence_report_preserves_retry_after_hint(self):
        http_client = EvidenceRateLimitHTTPClient()

        report = harvest_remote_evidence_report(
            http_client,
            urls=["https://example.org/paper"],
            source_name="openalex",
            timeout=1,
        )

        failure = report["failures"][0]
        self.assertEqual(report["chunks"], [])
        self.assertEqual(failure["stage"], "remote_evidence")
        self.assertEqual(failure["code"], "source_unavailable")
        self.assertEqual(failure["kind"], "rate_limited")
        self.assertEqual(failure["status_code"], 429)
        self.assertEqual(failure["retry_after_seconds"], 3.0)
        self.assertIsNone(failure["retry_delay_seconds"])
        self.assertEqual(failure["attempt_count"], 1)
        self.assertEqual(failure["retry_count"], 0)

    def test_remote_evidence_report_records_non_html_landing_page(self):
        http_client = EvidenceNonHtmlHTTPClient()

        report = harvest_remote_evidence_report(
            http_client,
            urls=["https://example.org/paper.pdf"],
            source_name="crossref",
            timeout=1,
        )

        failure = report["failures"][0]
        self.assertEqual(report["chunks"], [])
        self.assertEqual(failure["stage"], "remote_evidence")
        self.assertEqual(failure["code"], "source_unavailable")
        self.assertEqual(failure["kind"], "non_html_response")
        self.assertEqual(failure["status_code"], 200)
        self.assertEqual(failure["url"], "https://example.org/paper.pdf")
        self.assertEqual(failure["final_url"], "https://publisher.example/final-landing-page")
        self.assertTrue(failure["redirected"])
        self.assertEqual(failure["attempt_count"], 1)
        self.assertEqual(failure["retry_count"], 0)

    def test_remote_evidence_report_records_html_without_extractable_text(self):
        http_client = EvidenceNoExtractableHTMLHTTPClient()

        report = harvest_remote_evidence_report(
            http_client,
            urls=["https://example.org/empty-landing-page"],
            source_name="crossref",
            timeout=1,
        )

        failure = report["failures"][0]
        self.assertEqual(report["chunks"], [])
        self.assertEqual(failure["stage"], "remote_evidence")
        self.assertEqual(failure["code"], "source_unavailable")
        self.assertEqual(failure["kind"], "no_extractable_evidence")
        self.assertEqual(failure["status_code"], 200)
        self.assertEqual(failure["url"], "https://example.org/empty-landing-page")
        self.assertEqual(failure["attempt_count"], 1)
        self.assertEqual(failure["retry_count"], 0)

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
            http_min_interval=0.25,
            mailto="maintainer@example.org",
        )

        self.assertIsInstance(source, OpenAlexMetadataSource)
        self.assertEqual(source.mailto, "maintainer@example.org")
        self.assertFalse(source.harvest_evidence)
        self.assertEqual(source.http_client.timeout, 3)
        self.assertEqual(source.http_client.user_agent, f"CiteGuard/{__version__} (mailto:maintainer@example.org)")
        self.assertEqual(source.http_client.retries, 2)
        self.assertEqual(source.http_client.retry_backoff, 0.5)
        self.assertEqual(source.http_client.min_interval, 0.25)

    def test_factory_default_user_agent_avoids_placeholder_contact_url(self):
        source = build_live_metadata_source(["openalex"], harvest_remote_evidence=False)

        self.assertEqual(source.mailto, "")
        self.assertEqual(source.http_client.user_agent, f"CiteGuard/{__version__}")
        self.assertNotIn("research@example.com", source.http_client.user_agent)

    def test_crossref_omits_unconfigured_mailto_and_includes_configured_mailto(self):
        default_client = CapturingHTTPClient()
        default_source = CrossrefMetadataSource(
            mailto="research@example.com",
            http_client=default_client,
            harvest_evidence=False,
        )

        default_source.search("sparse crossref metadata", top_k=1)

        self.assertEqual(default_source.mailto, "")
        self.assertEqual(default_client.json_calls[0]["params"]["query.bibliographic"], "sparse crossref metadata")
        self.assertNotIn("mailto", default_client.json_calls[0]["params"])

        configured_client = CapturingHTTPClient()
        configured_source = CrossrefMetadataSource(
            mailto="maintainer@example.org",
            http_client=configured_client,
            harvest_evidence=False,
        )

        configured_source.search("sparse crossref metadata", top_k=1)

        self.assertEqual(configured_client.json_calls[0]["params"]["mailto"], "maintainer@example.org")

    def test_openalex_handles_null_primary_location_and_source(self):
        # OpenAlex routinely returns primary_location or its nested source as JSON
        # null; the adapter must not crash on those records.
        source = OpenAlexMetadataSource(http_client=NullLocationHTTPClient())
        results = source.search("anything", top_k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].venue, "")
        self.assertEqual(results[0].url, "https://openalex.org/W999")
        quality = results[0].metadata["metadata_quality"]
        self.assertIn("venue", quality["missing_fields"])
        self.assertIn("abstract", quality["missing_fields"])
        self.assertIn("identifier", quality["missing_fields"])
        self.assertFalse(quality["identifiers"]["doi"])
        self.assertFalse(quality["identifiers"]["arxiv_id"])
        self.assertEqual(
            quality["confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )


if __name__ == "__main__":
    unittest.main()
