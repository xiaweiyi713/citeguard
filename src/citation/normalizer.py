"""Normalization helpers used across retrieval and verification."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable, List, Optional, Set


STOPWORDS: Set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "to",
    "with",
}


# CJK Unified Ideographs main block (covers common Chinese); extend later if needed.
_CJK_PATTERN = "一-鿿"


def normalize_text(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace; keep latin and CJK."""

    text = text.lower()
    text = re.sub(rf"[^a-z0-9{_CJK_PATTERN}\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _cjk_bigrams(run: str) -> List[str]:
    """Character bigrams for a run of CJK characters (unigram if length 1)."""

    if len(run) == 1:
        return [run]
    return [run[index : index + 2] for index in range(len(run) - 1)]


def tokenize_text(text: str) -> List[str]:
    """Tokenize text: latin words (minus stopwords) + CJK character bigrams."""

    tokens: List[str] = []
    for chunk in normalize_text(text).split():
        for segment in re.findall(rf"[{_CJK_PATTERN}]+|[a-z0-9]+", chunk):
            if re.match(rf"[{_CJK_PATTERN}]", segment):
                tokens.extend(_cjk_bigrams(segment))
            elif segment not in STOPWORDS:
                tokens.append(segment)
    return tokens


def sequence_similarity(left: str, right: str) -> float:
    """Character-level string similarity."""

    if not left or not right:
        return 0.0
    return SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio()


def year_matches(candidate_year: Optional[int], canonical_year: Optional[int]) -> bool:
    """Year equality with a narrow tolerance for preprint versus venue metadata."""

    if candidate_year is None or canonical_year is None:
        return False
    return abs(candidate_year - canonical_year) <= 1


def author_coverage(candidate_authors: Iterable[str], canonical_authors: Iterable[str]) -> float:
    """Estimate how much of the candidate author list matches the canonical list."""

    candidate = {normalize_text(name) for name in candidate_authors if normalize_text(name)}
    canonical = {normalize_text(name) for name in canonical_authors if normalize_text(name)}
    if not candidate or not canonical:
        return 0.0
    return len(candidate & canonical) / len(candidate)
