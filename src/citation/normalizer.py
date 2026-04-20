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


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace."""

    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize_text(text: str) -> List[str]:
    """Tokenize text while removing low-value stopwords."""

    return [
        token
        for token in normalize_text(text).split()
        if token and token not in STOPWORDS
    ]


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
