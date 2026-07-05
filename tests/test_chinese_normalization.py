"""Tests for CJK-aware normalization and tokenization."""

import unittest

from citeguard.citation import normalize_text, sequence_similarity, tokenize_text


class ChineseNormalizationTests(unittest.TestCase):
    def test_normalize_keeps_cjk_characters(self):
        self.assertEqual(normalize_text("深度学习的引用幻觉！"), "深度学习的引用幻觉")

    def test_normalize_still_handles_english(self):
        self.assertEqual(normalize_text("Attention Is All You Need!"), "attention is all you need")

    def test_tokenize_cjk_uses_character_bigrams(self):
        self.assertEqual(tokenize_text("引用幻觉问题"), ["引用", "用幻", "幻觉", "觉问", "问题"])

    def test_tokenize_mixed_chinese_english(self):
        tokens = tokenize_text("基于 BERT 的检索")
        self.assertIn("bert", tokens)
        self.assertIn("基于", tokens)
        self.assertIn("检索", tokens)

    def test_sequence_similarity_chinese_titles(self):
        high = sequence_similarity("大模型引用幻觉分析", "大模型引用幻觉分析")
        low = sequence_similarity("大模型引用幻觉分析", "量子计算综述")
        self.assertEqual(high, 1.0)
        self.assertLess(low, 0.3)

    def test_english_tokenization_unchanged(self):
        self.assertEqual(tokenize_text("the citation hallucination"), ["citation", "hallucination"])


if __name__ == "__main__":
    unittest.main()
