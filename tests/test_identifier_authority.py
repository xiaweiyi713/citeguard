"""Strict identifier lookup: by id only, no title fallback, failure detectable."""

import unittest

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.arxiv import ArxivMetadataSource
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.retrieval.scholarly_clients.crossref import CrossrefMetadataSource


ARXIV_ATOM_OK = """<?xml version=\"1.0\"?>
<feed xmlns=\"http://www.w3.org/2005/Atom\">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <title>Attention Is All You Need</title>
    <summary>Transformer.</summary>
    <published>2017-06-12T00:00:00Z</published>
    <author><name>Ashish Vaswani</name></author>
  </entry>
</feed>"""


class _ScriptedHTTP:
    """Returns queued (payload, error_code) pairs; mimics HTTPClient state tracking."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.last_error = ""
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_status_code = None
        self.last_url = ""
        self.calls = []

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        self.calls.append((url, dict(params or {})))
        payload, error_code = self.payloads.pop(0) if self.payloads else ("", "timeout")
        self.last_error_code = error_code
        self.last_error_kind = "timeout" if error_code else ""
        self.last_error = error_code
        self.last_url = url
        return payload

    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        import json
        payload = self.get_text(url, params=params, headers=headers, use_cache=use_cache, timeout=timeout)
        try:
            return json.loads(payload) if payload else {}
        except Exception:
            return {}


class AdapterIdentifierLookupTests(unittest.TestCase):
    def test_base_default_is_none(self):
        class _Dummy(MetadataSource):
            name = "dummy"

            def all_records(self):
                return []

            def search(self, query, top_k=5):
                return []

            def lookup(self, candidate):
                return None

        self.assertIsNone(_Dummy().lookup_identifier(CitationRecord(citation_id="c", title="t")))

    def test_arxiv_identifier_hit_uses_id_list_only(self):
        http = _ScriptedHTTP([(ARXIV_ATOM_OK, "")])
        source = ArxivMetadataSource(http_client=http, harvest_evidence=False)
        record = source.lookup_identifier(CitationRecord(citation_id="c", title="", arxiv_id="1706.03762"))
        self.assertIsNotNone(record)
        self.assertEqual(record.year, 2017)
        self.assertEqual(len(http.calls), 1)
        self.assertIn("id_list", http.calls[0][1])

    def test_arxiv_identifier_failure_leaves_error_state(self):
        http = _ScriptedHTTP([("", "timeout")])
        source = ArxivMetadataSource(http_client=http, harvest_evidence=False)
        record = source.lookup_identifier(CitationRecord(citation_id="c", title="", arxiv_id="1706.03762"))
        self.assertIsNone(record)
        self.assertEqual(http.last_error_code, "timeout")  # no title-search whitewash

    def test_arxiv_identifier_none_without_id(self):
        http = _ScriptedHTTP([])
        source = ArxivMetadataSource(http_client=http, harvest_evidence=False)
        self.assertIsNone(source.lookup_identifier(CitationRecord(citation_id="c", title="Some Title")))
        self.assertEqual(http.calls, [])

    def test_crossref_identifier_hit_by_doi(self):
        crossref_payload = (
            '{"message": {"DOI": "10.1000/xyz", "title": ["A Real Paper"],'
            ' "author": [{"given": "A", "family": "Author"}],'
            ' "issued": {"date-parts": [[2020]]}}}'
        )
        http = _ScriptedHTTP([(crossref_payload, "")])
        source = CrossrefMetadataSource(http_client=http, harvest_evidence=False)
        record = source.lookup_identifier(CitationRecord(citation_id="c", title="", doi="10.1000/xyz"))
        self.assertIsNotNone(record)
        self.assertEqual(len(http.calls), 1)

    def test_crossref_identifier_none_without_doi(self):
        http = _ScriptedHTTP([])
        source = CrossrefMetadataSource(http_client=http, harvest_evidence=False)
        self.assertIsNone(source.lookup_identifier(CitationRecord(citation_id="c", title="Some Title")))
        self.assertEqual(http.calls, [])


if __name__ == "__main__":
    unittest.main()
