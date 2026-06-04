"""Chinese-language citation verification works end-to-end on the v1 path."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verification import Verdict, parse_citation, verify_citation


class ChineseVerificationTests(unittest.TestCase):
    def setUp(self):
        self.paper = CitationRecord(
            citation_id="zh-1",
            title="大语言模型中的引用幻觉分析",
            authors=["张三"],
            year=2025,
            source="memory",
        )
        self.source = InMemoryMetadataSource([self.paper])

    def test_chinese_title_resolves_and_verifies(self):
        candidate = parse_citation(title="大语言模型中的引用幻觉分析", authors=["张三"], year=2025)
        result = verify_citation(candidate, self.source)
        self.assertEqual(result.verdict, Verdict.VERIFIED)

    def test_fabricated_chinese_title_not_found(self):
        candidate = parse_citation(title="一种永不存在的量子引用消除方法")
        result = verify_citation(candidate, self.source)
        self.assertEqual(result.verdict, Verdict.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
