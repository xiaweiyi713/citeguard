# CiteGuard 引用核验能力(v1)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 CiteGuard 强项(存在性 + 元数据核验)做成一个 claim-free 的核心库,并通过 MCP server 暴露给 Claude Code / Codex / Cursor 等 agent 调用,发现问题时给出改正建议。

**Architecture:** 新增 `src/verification/`(纯逻辑核心库,复用现有 `scholarly_clients` 数据源与 `src/citation` 工具函数,不依赖 claim/写作链路);`src/mcp_server/` 用 FastMCP 暴露 `verify_citation` / `audit_citations` 两个工具;`skills/citeguard-verify/` 提供薄 Claude Code Skill;`data/eval/` + `scripts/eval_verification.py` 提供离线可复现的可信度评测。

**Tech Stack:** Python ≥3.9,标准库 `urllib`/`sqlite3`/`re`/`unittest`(运行时零三方依赖),MCP Python SDK(`mcp`,仅 MCP server 这一可选层需要)。

**关键事实(实现者必读):**
- 测试框架是 **`unittest`**,不是 pytest。CI 跑 `python3 -m unittest discover -s tests`。
- 包根目录就叫 `src`,导入形如 `from src.graph import CitationRecord`。
- `CitationRecord` 是 frozen dataclass,字段:`citation_id, title, authors: List[str], year: Optional[int], venue, abstract, doi, arxiv_id, url, source, metadata: Dict`。
- 数据源接口 `MetadataSource`(`src/retrieval/scholarly_clients/base.py`):`all_records()` / `search(query, top_k)` / `lookup(candidate) -> Optional[CitationRecord]`。
- 可复用工具:`src/citation`(`sequence_similarity`、`author_coverage`、`year_matches`、`normalize_text`、`CitationFormatter.format_reference(record) -> str`);`src/retrieval/scholarly_clients/utils.py`(`normalize_doi`、`normalize_arxiv_id`、`stable_record_id(prefix, value)`、`canonical_record_key(record)`)。
- ⚠️ **不要**直接用 `utils.record_match_score` 的阈值做核验匹配:它把 DOI/arXiv 权重设为 0.6,纯标题最高只能到 0.40,会把"有标题无 DOI"的真实引用误判为 not_found。本计划用专门的 `verification_match_score`(标题主导)替代。
- 测试一律用 `InMemoryMetadataSource`(`src/retrieval/scholarly_clients/in_memory.py`)做数据源,**不联网**。
- 提交信息用英文祈使句(与现有 commit 风格一致),**不加** Claude 署名脚注。

---

## 文件结构

```
src/verification/
  __init__.py        # 导出公共 API
  models.py          # Verdict 枚举、FieldDiff、VerificationResult、AuditReport
  parse.py           # parse_citation() + DOI/arXiv/year 抽取
  resolve.py         # verification_match_score、source_names、resolve_citation
  verify.py          # verify_citation():裁定 + 字段差异 + 改正建议
  audit.py           # audit_citations():批量 + 汇总
  cache.py           # CachingMetadataSource:SQLite 持久缓存(装饰器,另一个 MetadataSource)
  eval.py            # 评测集加载 + 指标计算
src/mcp_server/
  __init__.py
  server.py          # FastMCP server,暴露 verify_citation / audit_citations
skills/citeguard-verify/
  SKILL.md           # 薄 Claude Code Skill
data/eval/
  verification_eval.json   # 离线评测:corpus(真实论文) + cases(正确/污染/伪造/模糊)
scripts/
  eval_verification.py     # 跑评测、打印指标
tests/
  test_verification_parse.py
  test_verification_resolve.py
  test_verification_verify.py
  test_verification_audit.py
  test_verification_cache.py
  test_verification_eval.py
```

每个 `src/verification/*` 文件单一职责;`resolve` 不感知缓存(缓存是包在数据源外的装饰器),`verify` 不感知形态(MCP/CLI 都复用同一函数)。

---

## Task 1: 核验数据模型

**Files:**
- Create: `src/verification/models.py`
- Test: `tests/test_verification_models.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verification_models.py
"""Tests for verification data models."""

import unittest

from src.graph import CitationRecord
from src.verification.models import AuditReport, FieldDiff, VerificationResult, Verdict


class ModelsTests(unittest.TestCase):
    def _result(self, verdict):
        record = CitationRecord(citation_id="c1", title="A Real Paper", year=2024)
        return VerificationResult(
            verdict=verdict,
            confidence=0.91,
            input_citation=record,
            canonical_record=record,
            field_diffs=[FieldDiff("year", 2023, 2024, False)],
            suggested_citation="Doe (2024). A Real Paper.",
            explanation="ok",
            sources_checked=["openalex"],
            sources_responded=["openalex"],
        )

    def test_result_to_dict_is_json_friendly(self):
        data = self._result(Verdict.METADATA_MISMATCH).to_dict()
        self.assertEqual(data["verdict"], "metadata_mismatch")
        self.assertEqual(data["confidence"], 0.91)
        self.assertEqual(data["field_diffs"][0]["field"], "year")
        self.assertEqual(data["sources_checked"], ["openalex"])
        self.assertEqual(data["alternatives"], [])

    def test_audit_report_to_dict_carries_summary(self):
        report = AuditReport(
            results=[self._result(Verdict.VERIFIED)],
            summary={"verified": 1, "not_found": 0},
        )
        data = report.to_dict()
        self.assertEqual(data["summary"]["verified"], 1)
        self.assertEqual(len(data["results"]), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_models -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'src.verification'`

- [ ] **Step 3: 实现 models.py**

```python
# src/verification/models.py
"""Data models for claim-free citation verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.graph import CitationRecord


class Verdict(str, Enum):
    """Outcome of verifying a single citation."""

    VERIFIED = "verified"
    METADATA_MISMATCH = "metadata_mismatch"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class FieldDiff:
    """Per-field comparison between the input citation and the canonical record."""

    field: str
    candidate: Any
    canonical: Any
    matches: bool


@dataclass(frozen=True)
class VerificationResult:
    """Result of verifying one citation."""

    verdict: Verdict
    confidence: float
    input_citation: CitationRecord
    canonical_record: Optional[CitationRecord]
    field_diffs: List[FieldDiff]
    suggested_citation: str
    explanation: str
    sources_checked: List[str]
    sources_responded: List[str]
    alternatives: List[CitationRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 4),
            "input": asdict(self.input_citation),
            "canonical_record": asdict(self.canonical_record) if self.canonical_record else None,
            "field_diffs": [asdict(diff) for diff in self.field_diffs],
            "suggested_citation": self.suggested_citation,
            "explanation": self.explanation,
            "sources_checked": list(self.sources_checked),
            "sources_responded": list(self.sources_responded),
            "alternatives": [asdict(record) for record in self.alternatives],
        }


@dataclass(frozen=True)
class AuditReport:
    """Result of verifying a batch of citations."""

    results: List[VerificationResult]
    summary: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": dict(self.summary),
            "results": [result.to_dict() for result in self.results],
        }
```

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_verification_models -v`
Expected: PASS(2 个用例)

- [ ] **Step 5: 提交**

```bash
git add src/verification/models.py tests/test_verification_models.py
git commit -m "Add verification data models"
```

---

## Task 2: 引用解析(自由文本 → 候选记录)

**Files:**
- Create: `src/verification/parse.py`
- Test: `tests/test_verification_parse.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verification_parse.py
"""Tests for citation parsing."""

import unittest

from src.verification.parse import extract_arxiv_id, extract_doi, extract_year, parse_citation


class ParseTests(unittest.TestCase):
    def test_extract_doi_from_free_text(self):
        text = "Some Paper. https://doi.org/10.1145/3539618.3591708 (2023)"
        self.assertEqual(extract_doi(text), "10.1145/3539618.3591708")

    def test_extract_arxiv_id_from_free_text(self):
        self.assertEqual(extract_arxiv_id("See arXiv:2411.14199 for details"), "2411.14199")

    def test_extract_year(self):
        self.assertEqual(extract_year("Published in 2024 at NeurIPS"), 2024)
        self.assertIsNone(extract_year("no year here"))

    def test_parse_structured_fields(self):
        record = parse_citation(
            title="OpenScholar",
            authors=["Akari Asai"],
            year=2024,
            doi="https://doi.org/10.1000/XYZ",
        )
        self.assertEqual(record.title, "OpenScholar")
        self.assertEqual(record.doi, "10.1000/xyz")
        self.assertEqual(record.authors, ["Akari Asai"])
        self.assertTrue(record.metadata["title_explicit"])

    def test_parse_raw_text_uses_text_as_query_not_explicit_title(self):
        record = parse_citation(raw_text="Asai et al., OpenScholar, arXiv:2411.14199, 2024")
        self.assertEqual(record.arxiv_id, "2411.14199")
        self.assertEqual(record.year, 2024)
        self.assertFalse(record.metadata["title_explicit"])
        self.assertEqual(record.metadata["raw_text"], "Asai et al., OpenScholar, arXiv:2411.14199, 2024")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_parse -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'src.verification.parse'`

- [ ] **Step 3: 实现 parse.py**

```python
# src/verification/parse.py
"""Parse free-text or structured citation input into a candidate record."""

from __future__ import annotations

import re
from typing import List, Optional

from src.graph import CitationRecord
from src.retrieval.scholarly_clients.utils import (
    normalize_arxiv_id,
    normalize_doi,
    stable_record_id,
)

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
ARXIV_LABELLED_RE = re.compile(r"arxiv:\s*(\d{4}\.\d{4,5})", re.IGNORECASE)
ARXIV_BARE_RE = re.compile(r"\b(\d{4}\.\d{4,5})\b")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def extract_doi(text: str) -> str:
    match = DOI_RE.search(text or "")
    return normalize_doi(match.group(0)) if match else ""


def extract_arxiv_id(text: str) -> str:
    match = ARXIV_LABELLED_RE.search(text or "")
    if match:
        return normalize_arxiv_id(match.group(1))
    match = ARXIV_BARE_RE.search(text or "")
    return normalize_arxiv_id(match.group(1)) if match else ""


def extract_year(text: str) -> Optional[int]:
    match = YEAR_RE.search(text or "")
    return int(match.group(0)) if match else None


def parse_citation(
    raw_text: str = "",
    title: str = "",
    authors: Optional[List[str]] = None,
    year: Optional[int] = None,
    venue: str = "",
    doi: str = "",
    arxiv_id: str = "",
) -> CitationRecord:
    """Build a candidate CitationRecord from whatever the caller provides.

    `title` is treated as an explicit, comparable title only when passed in.
    When only `raw_text` is given it is used as the search query (stored in
    metadata['raw_text']) and NOT treated as an explicit title.
    """

    authors = list(authors or [])
    doi = normalize_doi(doi) or extract_doi(raw_text)
    arxiv_id = normalize_arxiv_id(arxiv_id) or extract_arxiv_id(raw_text)
    if year is None:
        year = extract_year(raw_text)

    title_explicit = bool(title)
    search_title = title or raw_text
    seed = doi or arxiv_id or search_title or "citation"
    return CitationRecord(
        citation_id=stable_record_id("input", seed),
        title=search_title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        source="input",
        metadata={"raw_text": raw_text, "title_explicit": title_explicit},
    )
```

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_verification_parse -v`
Expected: PASS(5 个用例)

- [ ] **Step 5: 提交**

```bash
git add src/verification/parse.py tests/test_verification_parse.py
git commit -m "Add citation input parsing"
```

---

## Task 3: 解析匹配(resolve)

**Files:**
- Create: `src/verification/resolve.py`
- Test: `tests/test_verification_resolve.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verification_resolve.py
"""Tests for citation resolution."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource
from src.verification.parse import parse_citation
from src.verification.resolve import (
    STRONG_MATCH,
    resolve_citation,
    source_names,
    verification_match_score,
)


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.openscholar = CitationRecord(
            citation_id="openscholar",
            title="OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented LMs",
            authors=["Akari Asai", "Jacqueline He"],
            year=2024,
            venue="arXiv",
            doi="10.48550/arxiv.2411.14199",
            source="memory",
        )
        self.source = InMemoryMetadataSource([self.openscholar])

    def test_title_match_reaches_strong_threshold_without_doi(self):
        candidate = parse_citation(
            title="OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented LMs",
            authors=["Akari Asai"],
            year=2024,
        )
        score = verification_match_score(candidate, self.openscholar)
        self.assertGreaterEqual(score, STRONG_MATCH)

    def test_doi_match_is_definitive(self):
        candidate = parse_citation(title="Totally Different Title", doi="10.48550/arXiv.2411.14199")
        self.assertEqual(verification_match_score(candidate, self.openscholar), 1.0)

    def test_resolve_returns_best_match(self):
        candidate = parse_citation(title=self.openscholar.title, year=2024)
        outcome = resolve_citation(candidate, self.source)
        self.assertIsNotNone(outcome.best)
        self.assertEqual(outcome.best.citation_id, "openscholar")
        self.assertGreaterEqual(outcome.score, STRONG_MATCH)
        self.assertFalse(outcome.ambiguous)

    def test_resolve_unknown_title_returns_no_strong_match(self):
        candidate = parse_citation(title="A Completely Unrelated Quantum Chemistry Paper")
        outcome = resolve_citation(candidate, self.source)
        self.assertTrue(outcome.best is None or outcome.score < STRONG_MATCH)

    def test_resolve_flags_ambiguous_near_duplicates(self):
        twin_a = CitationRecord(citation_id="a", title="Deep Learning for Citation Analysis", year=2022, source="memory")
        twin_b = CitationRecord(citation_id="b", title="Deep Learning for Citation Analyses", year=2022, source="memory")
        source = InMemoryMetadataSource([twin_a, twin_b])
        candidate = parse_citation(title="Deep Learning for Citation Analysis")
        outcome = resolve_citation(candidate, source)
        self.assertTrue(outcome.ambiguous)

    def test_source_names_unwraps_multi_source(self):
        multi = MultiSourceMetadataSource([self.source])
        # InMemoryMetadataSource has no `name` override; multi reports its children's names.
        self.assertIsInstance(source_names(multi), list)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_resolve -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'src.verification.resolve'`

- [ ] **Step 3: 实现 resolve.py**

```python
# src/verification/resolve.py
"""Resolve a candidate citation to a canonical record across metadata sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.citation import author_coverage, sequence_similarity, year_matches
from src.graph import CitationRecord
from src.retrieval.scholarly_clients.base import MetadataSource
from src.retrieval.scholarly_clients.multi_source import MultiSourceMetadataSource
from src.retrieval.scholarly_clients.utils import normalize_arxiv_id, normalize_doi

STRONG_MATCH = 0.70
AMBIGUOUS_MARGIN = 0.05


@dataclass(frozen=True)
class ResolveOutcome:
    best: Optional[CitationRecord]
    score: float
    alternatives: List[CitationRecord]
    sources_checked: List[str]
    sources_responded: List[str]
    ambiguous: bool


def verification_match_score(candidate: CitationRecord, record: CitationRecord) -> float:
    """Title-dominant match score suited to verification (DOI/arXiv are definitive)."""

    if candidate.doi and record.doi and normalize_doi(candidate.doi) == normalize_doi(record.doi):
        return 1.0
    if (
        candidate.arxiv_id
        and record.arxiv_id
        and normalize_arxiv_id(candidate.arxiv_id) == normalize_arxiv_id(record.arxiv_id)
    ):
        return 1.0
    title = sequence_similarity(candidate.title, record.title)
    author = author_coverage(candidate.authors, record.authors)
    year = 1.0 if year_matches(candidate.year, record.year) else 0.0
    return 0.70 * title + 0.18 * author + 0.12 * year


def source_names(source: MetadataSource) -> List[str]:
    """Human-readable list of the underlying source names (unwraps wrappers)."""

    inner = getattr(source, "inner", source)
    if isinstance(inner, MultiSourceMetadataSource):
        return [child.name for child in inner.sources]
    return [inner.name]


def resolve_citation(candidate: CitationRecord, source: MetadataSource) -> ResolveOutcome:
    checked = source_names(source)
    query = candidate.title or candidate.metadata.get("raw_text", "")

    results: List[CitationRecord] = []
    if candidate.doi or candidate.arxiv_id:
        match = source.lookup(candidate)
        if match is not None:
            results.append(match)
    if query:
        results.extend(source.search(query, top_k=5))

    responded = sorted({record.source for record in results if record.source})

    seen = set()
    scored = []
    for record in results:
        if record.citation_id in seen:
            continue
        seen.add(record.citation_id)
        scored.append((verification_match_score(candidate, record), record))
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return ResolveOutcome(None, 0.0, [], checked, responded, False)

    best_score, best = scored[0]
    alternatives = [record for _, record in scored[1:4]]
    ambiguous = (
        best_score >= STRONG_MATCH
        and len(scored) > 1
        and (best_score - scored[1][0]) < AMBIGUOUS_MARGIN
        and not (candidate.doi or candidate.arxiv_id)
    )
    return ResolveOutcome(best, best_score, alternatives, checked, responded, ambiguous)
```

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_verification_resolve -v`
Expected: PASS(6 个用例)

- [ ] **Step 5: 提交**

```bash
git add src/verification/resolve.py tests/test_verification_resolve.py
git commit -m "Add citation resolution with title-dominant matching"
```

---

## Task 4: 单条核验(verify)

**Files:**
- Create: `src/verification/verify.py`
- Test: `tests/test_verification_verify.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verification_verify.py
"""Tests for single-citation verification."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verification.models import Verdict
from src.verification.parse import parse_citation
from src.verification.verify import verify_citation


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.real = CitationRecord(
            citation_id="ghostcite",
            title="GhostCite: A Large-Scale Analysis of Citation Validity",
            authors=["Zhe Xu", "Lin Wang"],
            year=2026,
            venue="arXiv",
            doi="10.48550/arxiv.2602.06718",
            source="memory",
        )
        self.source = InMemoryMetadataSource([self.real])

    def test_correct_citation_is_verified(self):
        candidate = parse_citation(
            title="GhostCite: A Large-Scale Analysis of Citation Validity",
            authors=["Zhe Xu"],
            year=2026,
        )
        result = verify_citation(candidate, self.source)
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.suggested_citation, "")

    def test_wrong_year_is_metadata_mismatch_with_suggestion(self):
        candidate = parse_citation(
            title="GhostCite: A Large-Scale Analysis of Citation Validity",
            authors=["Zhe Xu"],
            year=2021,
        )
        result = verify_citation(candidate, self.source)
        self.assertEqual(result.verdict, Verdict.METADATA_MISMATCH)
        self.assertIn("year", [diff.field for diff in result.field_diffs if not diff.matches])
        self.assertTrue(result.suggested_citation)

    def test_fabricated_citation_is_not_found(self):
        candidate = parse_citation(title="Quantum Teleportation of Citation Hallucinations in Llamas")
        result = verify_citation(candidate, self.source)
        self.assertEqual(result.verdict, Verdict.NOT_FOUND)
        self.assertIn("Could not be verified", result.explanation)

    def test_not_found_notes_possible_outage_when_no_source_responded(self):
        empty_source = InMemoryMetadataSource([])
        candidate = parse_citation(title="Anything At All")
        result = verify_citation(candidate, empty_source)
        self.assertEqual(result.verdict, Verdict.NOT_FOUND)
        self.assertEqual(result.sources_responded, [])
        self.assertIn("outage", result.explanation)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_verify -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'src.verification.verify'`

- [ ] **Step 3: 实现 verify.py**

```python
# src/verification/verify.py
"""Verify a single citation: existence + metadata, with a suggested fix."""

from __future__ import annotations

from typing import List, Optional

from src.citation import CitationFormatter, author_coverage, sequence_similarity, year_matches
from src.graph import CitationRecord
from src.retrieval.scholarly_clients.base import MetadataSource
from src.retrieval.scholarly_clients.utils import normalize_doi

from .models import FieldDiff, VerificationResult, Verdict
from .resolve import STRONG_MATCH, resolve_citation

TITLE_MATCH = 0.90
AUTHOR_MATCH = 0.50
VENUE_MATCH = 0.60


def _field_diffs(candidate: CitationRecord, canonical: CitationRecord) -> List[FieldDiff]:
    """Compare only the fields the caller actually provided."""

    diffs: List[FieldDiff] = []
    if candidate.metadata.get("title_explicit"):
        matches = sequence_similarity(candidate.title, canonical.title) >= TITLE_MATCH
        diffs.append(FieldDiff("title", candidate.title, canonical.title, matches))
    if candidate.authors:
        matches = author_coverage(candidate.authors, canonical.authors) >= AUTHOR_MATCH
        diffs.append(FieldDiff("authors", candidate.authors, canonical.authors, matches))
    if candidate.year is not None:
        diffs.append(
            FieldDiff("year", candidate.year, canonical.year, year_matches(candidate.year, canonical.year))
        )
    if candidate.venue:
        matches = sequence_similarity(candidate.venue, canonical.venue) >= VENUE_MATCH
        diffs.append(FieldDiff("venue", candidate.venue, canonical.venue, matches))
    if candidate.doi:
        matches = normalize_doi(candidate.doi) == normalize_doi(canonical.doi)
        diffs.append(FieldDiff("doi", candidate.doi, canonical.doi, matches))
    return diffs


def verify_citation(
    candidate: CitationRecord,
    source: MetadataSource,
    formatter: Optional[CitationFormatter] = None,
) -> VerificationResult:
    formatter = formatter or CitationFormatter()
    outcome = resolve_citation(candidate, source)
    checked, responded = outcome.sources_checked, outcome.sources_responded

    if outcome.best is None or outcome.score < STRONG_MATCH:
        outage = "" if responded else " No source returned any result, which may also indicate a temporary source outage."
        return VerificationResult(
            verdict=Verdict.NOT_FOUND,
            confidence=round(1.0 - outcome.score, 4),
            input_citation=candidate,
            canonical_record=None,
            field_diffs=[],
            suggested_citation="",
            explanation=f"Could not be verified in {', '.join(checked)}.{outage}",
            sources_checked=checked,
            sources_responded=responded,
            alternatives=outcome.alternatives,
        )

    if outcome.ambiguous:
        return VerificationResult(
            verdict=Verdict.AMBIGUOUS,
            confidence=round(outcome.score, 4),
            input_citation=candidate,
            canonical_record=outcome.best,
            field_diffs=[],
            suggested_citation="",
            explanation="Multiple plausible matches; cannot disambiguate without a DOI or arXiv id.",
            sources_checked=checked,
            sources_responded=responded,
            alternatives=outcome.alternatives,
        )

    diffs = _field_diffs(candidate, outcome.best)
    mismatched = [diff.field for diff in diffs if not diff.matches]
    if mismatched:
        return VerificationResult(
            verdict=Verdict.METADATA_MISMATCH,
            confidence=round(outcome.score, 4),
            input_citation=candidate,
            canonical_record=outcome.best,
            field_diffs=diffs,
            suggested_citation=formatter.format_reference(outcome.best),
            explanation=f"The paper exists, but these fields disagree with the canonical record: {', '.join(mismatched)}.",
            sources_checked=checked,
            sources_responded=responded,
        )

    return VerificationResult(
        verdict=Verdict.VERIFIED,
        confidence=round(outcome.score, 4),
        input_citation=candidate,
        canonical_record=outcome.best,
        field_diffs=diffs,
        suggested_citation="",
        explanation="Citation resolves to a real record and the provided metadata matches.",
        sources_checked=checked,
        sources_responded=responded,
    )
```

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_verification_verify -v`
Expected: PASS(4 个用例)

- [ ] **Step 5: 提交**

```bash
git add src/verification/verify.py tests/test_verification_verify.py
git commit -m "Add single-citation verification with suggested fixes"
```

---

## Task 5: 批量审计(audit)

**Files:**
- Create: `src/verification/audit.py`
- Test: `tests/test_verification_audit.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verification_audit.py
"""Tests for batch citation auditing."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verification.audit import audit_citations
from src.verification.parse import parse_citation


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.real = CitationRecord(
            citation_id="openscholar",
            title="OpenScholar: Synthesizing Scientific Literature",
            authors=["Akari Asai"],
            year=2024,
            source="memory",
        )
        self.source = InMemoryMetadataSource([self.real])

    def test_audit_counts_each_verdict(self):
        candidates = [
            parse_citation(title="OpenScholar: Synthesizing Scientific Literature", year=2024),  # verified
            parse_citation(title="OpenScholar: Synthesizing Scientific Literature", year=2010),  # mismatch
            parse_citation(title="A Fabricated Paper That Does Not Exist"),                      # not_found
        ]
        report = audit_citations(candidates, self.source)
        self.assertEqual(len(report.results), 3)
        self.assertEqual(report.summary["verified"], 1)
        self.assertEqual(report.summary["metadata_mismatch"], 1)
        self.assertEqual(report.summary["not_found"], 1)
        self.assertEqual(report.summary["ambiguous"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_audit -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'src.verification.audit'`

- [ ] **Step 3: 实现 audit.py**

```python
# src/verification/audit.py
"""Batch verification across many citations."""

from __future__ import annotations

from typing import List

from src.citation import CitationFormatter
from src.graph import CitationRecord
from src.retrieval.scholarly_clients.base import MetadataSource

from .models import AuditReport, Verdict
from .verify import verify_citation


def audit_citations(candidates: List[CitationRecord], source: MetadataSource) -> AuditReport:
    formatter = CitationFormatter()
    results = [verify_citation(candidate, source, formatter) for candidate in candidates]
    summary = {verdict.value: 0 for verdict in Verdict}
    for result in results:
        summary[result.verdict.value] += 1
    return AuditReport(results=results, summary=summary)
```

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_verification_audit -v`
Expected: PASS(1 个用例)

- [ ] **Step 5: 提交**

```bash
git add src/verification/audit.py tests/test_verification_audit.py
git commit -m "Add batch citation audit"
```

---

## Task 6: 持久缓存(CachingMetadataSource)

**Files:**
- Create: `src/verification/cache.py`
- Test: `tests/test_verification_cache.py`

说明:缓存做成一个**装饰另一个 `MetadataSource` 的 `MetadataSource`**,因此 `resolve`/`verify` 完全不改。`source_names()` 已通过 `getattr(source, "inner", source)` 自动解包(见 Task 3)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verification_cache.py
"""Tests for the SQLite-backed caching metadata source."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verification.cache import CachingMetadataSource


class _CountingSource(InMemoryMetadataSource):
    def __init__(self, records):
        super().__init__(records)
        self.search_calls = 0

    def search(self, query, top_k=5):
        self.search_calls += 1
        return super().search(query, top_k=top_k)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.record = CitationRecord(
            citation_id="r1",
            title="Citation Hallucination in Scientific Writing",
            authors=["A. Author"],
            year=2025,
            source="memory",
        )
        self.inner = _CountingSource([self.record])
        self.cached = CachingMetadataSource(self.inner, db_path=":memory:")

    def test_second_identical_search_hits_cache(self):
        first = self.cached.search("citation hallucination", top_k=5)
        second = self.cached.search("citation hallucination", top_k=5)
        self.assertEqual([r.citation_id for r in first], [r.citation_id for r in second])
        self.assertEqual(self.inner.search_calls, 1)

    def test_cache_roundtrip_preserves_fields(self):
        self.cached.search("citation hallucination", top_k=5)
        cached_again = self.cached.search("citation hallucination", top_k=5)
        self.assertEqual(cached_again[0].title, self.record.title)
        self.assertEqual(cached_again[0].year, 2025)
        self.assertEqual(cached_again[0].authors, ["A. Author"])

    def test_inner_is_exposed_for_unwrapping(self):
        self.assertIs(self.cached.inner, self.inner)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_cache -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'src.verification.cache'`

- [ ] **Step 3: 实现 cache.py**

```python
# src/verification/cache.py
"""A MetadataSource decorator that persists search/lookup results in SQLite."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import List, Optional

from src.citation import normalize_text
from src.graph import CitationRecord
from src.retrieval.scholarly_clients.base import MetadataSource
from src.retrieval.scholarly_clients.utils import canonical_record_key


class CachingMetadataSource(MetadataSource):
    """Wraps another source and memoizes results to a SQLite database."""

    name = "cached"

    def __init__(self, inner: MetadataSource, db_path: str = ":memory:") -> None:
        self.inner = inner
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT)")
        self._conn.commit()

    def all_records(self) -> List[CitationRecord]:
        return self.inner.all_records()

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        key = f"search:{normalize_text(query)}:{top_k}"
        cached = self._get(key)
        if cached is not None:
            return [CitationRecord(**item) for item in json.loads(cached)]
        records = self.inner.search(query, top_k=top_k)
        self._set(key, json.dumps([asdict(record) for record in records]))
        return records

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        key = f"lookup:{canonical_record_key(candidate)}"
        cached = self._get(key)
        if cached is not None:
            payload = json.loads(cached)
            return CitationRecord(**payload) if payload else None
        match = self.inner.lookup(candidate)
        self._set(key, json.dumps(asdict(match) if match else None))
        return match

    def _get(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)", (key, value))
        self._conn.commit()
```

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_verification_cache -v`
Expected: PASS(3 个用例)

- [ ] **Step 5: 提交**

```bash
git add src/verification/cache.py tests/test_verification_cache.py
git commit -m "Add SQLite caching metadata source"
```

---

## Task 7: 包导出与集成冒烟测试

**Files:**
- Create: `src/verification/__init__.py`
- Test: `tests/test_verification_integration.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verification_integration.py
"""End-to-end smoke test for the verification package public API."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verification import (
    AuditReport,
    CachingMetadataSource,
    Verdict,
    VerificationResult,
    audit_citations,
    parse_citation,
    verify_citation,
)


class IntegrationTests(unittest.TestCase):
    def test_public_api_end_to_end_through_cache(self):
        record = CitationRecord(
            citation_id="x",
            title="The AI Scientist-v2: Workshop-Level Automated Scientific Discovery",
            authors=["Yutaro Yamada"],
            year=2025,
            source="memory",
        )
        source = CachingMetadataSource(InMemoryMetadataSource([record]), db_path=":memory:")
        candidate = parse_citation(title=record.title, authors=["Yutaro Yamada"], year=2025)

        result = verify_citation(candidate, source)
        self.assertIsInstance(result, VerificationResult)
        self.assertEqual(result.verdict, Verdict.VERIFIED)

        report = audit_citations([candidate], source)
        self.assertIsInstance(report, AuditReport)
        self.assertEqual(report.summary["verified"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_integration -v`
Expected: FAIL,`ImportError: cannot import name 'verify_citation' from 'src.verification'`

- [ ] **Step 3: 实现 __init__.py**

```python
# src/verification/__init__.py
"""Claim-free citation verification (existence + metadata)."""

from .audit import audit_citations
from .cache import CachingMetadataSource
from .models import AuditReport, FieldDiff, VerificationResult, Verdict
from .parse import parse_citation
from .resolve import ResolveOutcome, resolve_citation, source_names, verification_match_score
from .verify import verify_citation

__all__ = [
    "AuditReport",
    "CachingMetadataSource",
    "FieldDiff",
    "ResolveOutcome",
    "VerificationResult",
    "Verdict",
    "audit_citations",
    "parse_citation",
    "resolve_citation",
    "source_names",
    "verification_match_score",
    "verify_citation",
]
```

- [ ] **Step 4: 运行全部测试,确认通过**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS(原有用例 + 新增 verification 用例全绿)

- [ ] **Step 5: 提交**

```bash
git add src/verification/__init__.py tests/test_verification_integration.py
git commit -m "Expose verification package public API"
```

---

## Task 8: 离线可复现评测集与指标

**Files:**
- Create: `data/eval/verification_eval.json`
- Create: `src/verification/eval.py`
- Create: `scripts/eval_verification.py`
- Test: `tests/test_verification_eval.py`

设计:`verification_eval.json` 自带一个小 `corpus`(被当作"真实存在的论文")和一组 `cases`。评测时用 corpus 构造 `InMemoryMetadataSource`,对每个 case 跑真实的 `verify_citation`。因此**离线、确定、CI 可跑**,且走的就是工具真实代码路径。线上多源评测可另跑(非本计划范围)。

- [ ] **Step 1: 创建评测数据(种子约 12 条,后续扩到 30–50)**

```json
{
  "corpus": [
    {"citation_id": "openscholar", "title": "OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented Language Models", "authors": ["Akari Asai", "Jacqueline He"], "year": 2024, "venue": "arXiv", "doi": "10.48550/arxiv.2411.14199", "arxiv_id": "2411.14199", "abstract": "", "url": "", "source": "eval", "metadata": {}},
    {"citation_id": "ghostcite", "title": "GhostCite: A Large-Scale Analysis of Citation Validity in the Age of Large Language Models", "authors": ["Zhe Xu"], "year": 2026, "venue": "arXiv", "doi": "10.48550/arxiv.2602.06718", "arxiv_id": "2602.06718", "abstract": "", "url": "", "source": "eval", "metadata": {}},
    {"citation_id": "aiscientist2", "title": "The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic Tree Search", "authors": ["Yutaro Yamada"], "year": 2025, "venue": "arXiv", "doi": "10.48550/arxiv.2504.08066", "arxiv_id": "2504.08066", "abstract": "", "url": "", "source": "eval", "metadata": {}},
    {"citation_id": "reasons", "title": "REASONS: A Benchmark for Retrieval and Automated Citations of Scientific Sentences", "authors": ["Deepa Tilwani"], "year": 2024, "venue": "arXiv", "doi": "10.48550/arxiv.2405.02228", "arxiv_id": "2405.02228", "abstract": "", "url": "", "source": "eval", "metadata": {}},
    {"citation_id": "attributionbench", "title": "AttributionBench: How Hard is Automatic Attribution Evaluation", "authors": ["Yifei Li"], "year": 2024, "venue": "arXiv", "doi": "10.48550/arxiv.2402.15089", "arxiv_id": "2402.15089", "abstract": "", "url": "", "source": "eval", "metadata": {}}
  ],
  "cases": [
    {"id": "c01", "expected": "verified", "fields": {"title": "OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented Language Models", "authors": ["Akari Asai"], "year": 2024}, "note": "exact title + correct year"},
    {"id": "c02", "expected": "verified", "fields": {"title": "GhostCite: A Large-Scale Analysis of Citation Validity in the Age of Large Language Models", "year": 2026}, "note": "exact title, no authors"},
    {"id": "c03", "expected": "verified", "fields": {"doi": "10.48550/arXiv.2504.08066"}, "note": "DOI-only, definitive identifier match"},
    {"id": "c04", "expected": "metadata_mismatch", "fields": {"title": "OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented Language Models", "authors": ["Akari Asai"], "year": 2019}, "note": "real paper, correct author, wrong year"},
    {"id": "c05", "expected": "metadata_mismatch", "fields": {"title": "GhostCite: A Large-Scale Analysis of Citation Validity in the Age of Large Language Models", "authors": ["Jane Fabricated"], "year": 2026}, "note": "real paper, wrong author"},
    {"id": "c06", "expected": "metadata_mismatch", "fields": {"title": "REASONS: A Benchmark for Retrieval and Automated Citations of Scientific Sentences", "authors": ["Deepa Tilwani"], "year": 2030}, "note": "real paper, correct author, impossible future year"},
    {"id": "c07", "expected": "not_found", "fields": {"title": "Quantum Teleportation of Citation Hallucinations in Alpacas"}, "note": "fabricated"},
    {"id": "c08", "expected": "not_found", "fields": {"title": "A Unified Theory of Phantom References That Was Never Written"}, "note": "fabricated"},
    {"id": "c09", "expected": "not_found", "fields": {"raw_text": "Nonexistent, J. (2099). Imaginary Methods for Imaginary Problems. Journal of Nowhere."}, "note": "fabricated free-text"},
    {"id": "c10", "expected": "verified", "fields": {"title": "AttributionBench: How Hard is Automatic Attribution Evaluation", "authors": ["Yifei Li"], "year": 2024}, "note": "exact"},
    {"id": "c11", "expected": "metadata_mismatch", "fields": {"title": "The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic Tree Search", "authors": ["Yutaro Yamada"], "year": 2022}, "note": "real paper, correct author, wrong year"},
    {"id": "c12", "expected": "not_found", "fields": {"title": "Self-Falsifying Agents Achieve Zero Hallucination Forever"}, "note": "fabricated"}
  ]
}
```

- [ ] **Step 2: 写失败测试**

```python
# tests/test_verification_eval.py
"""Tests for the verification evaluation harness."""

import os
import unittest

from src.verification.eval import compute_metrics, load_eval, run_eval

EVAL_PATH = os.path.join("data", "eval", "verification_eval.json")


class EvalTests(unittest.TestCase):
    def test_compute_metrics_on_known_predictions(self):
        preds = [
            ("verified", "verified"),
            ("metadata_mismatch", "metadata_mismatch"),
            ("not_found", "not_found"),
            ("verified", "not_found"),  # a false accusation
        ]
        metrics = compute_metrics(preds)
        self.assertEqual(metrics["n"], 4)
        self.assertEqual(metrics["accuracy"], 0.75)
        self.assertEqual(metrics["false_accusation_rate"], 0.5)
        self.assertEqual(metrics["fabrication_recall"], 1.0)

    def test_seed_eval_set_meets_baseline_quality(self):
        corpus, cases = load_eval(EVAL_PATH)
        self.assertGreaterEqual(len(cases), 12)
        metrics = run_eval(corpus, cases)
        # Seed set is designed to be fully separable; require no false accusations
        # and complete fabrication detection.
        self.assertEqual(metrics["false_accusation_rate"], 0.0)
        self.assertEqual(metrics["fabrication_recall"], 1.0)
        self.assertGreaterEqual(metrics["accuracy"], 0.9)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_eval -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'src.verification.eval'`

- [ ] **Step 4: 实现 eval.py**

```python
# src/verification/eval.py
"""Offline, reproducible evaluation of the verification pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Tuple

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource

from .parse import parse_citation
from .verify import verify_citation


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    expected: str
    fields: Dict
    note: str = ""


def load_eval(path: str) -> Tuple[List[CitationRecord], List[EvalCase]]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    corpus = [CitationRecord(**record) for record in data["corpus"]]
    cases = [
        EvalCase(case["id"], case["expected"], case["fields"], case.get("note", ""))
        for case in data["cases"]
    ]
    return corpus, cases


def run_eval(corpus: List[CitationRecord], cases: List[EvalCase]) -> Dict[str, float]:
    source = InMemoryMetadataSource(corpus)
    preds: List[Tuple[str, str]] = []
    for case in cases:
        candidate = parse_citation(**case.fields)
        result = verify_citation(candidate, source)
        preds.append((case.expected, result.verdict.value))
    return compute_metrics(preds)


def _precision_recall(preds: List[Tuple[str, str]], label: str) -> Tuple[float, float]:
    tp = sum(1 for expected, predicted in preds if expected == label and predicted == label)
    fp = sum(1 for expected, predicted in preds if expected != label and predicted == label)
    fn = sum(1 for expected, predicted in preds if expected == label and predicted != label)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return precision, recall


def compute_metrics(preds: List[Tuple[str, str]]) -> Dict[str, float]:
    n = len(preds)
    correct = sum(1 for expected, predicted in preds if expected == predicted)
    fab_p, fab_r = _precision_recall(preds, "not_found")
    meta_p, meta_r = _precision_recall(preds, "metadata_mismatch")
    verified_total = sum(1 for expected, _ in preds if expected == "verified")
    false_accusations = sum(
        1 for expected, predicted in preds if expected == "verified" and predicted == "not_found"
    )
    far = false_accusations / verified_total if verified_total else 0.0
    return {
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "fabrication_precision": round(fab_p, 4),
        "fabrication_recall": round(fab_r, 4),
        "metadata_error_precision": round(meta_p, 4),
        "metadata_error_recall": round(meta_r, 4),
        "false_accusation_rate": round(far, 4),
    }
```

- [ ] **Step 5: 实现 scripts/eval_verification.py**

```python
# scripts/eval_verification.py
"""Run the offline verification evaluation and print metrics."""

from __future__ import annotations

import argparse
import json

from src.verification.eval import load_eval, run_eval


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CiteGuard citation verification offline.")
    parser.add_argument("--dataset", default="data/eval/verification_eval.json")
    args = parser.parse_args()

    corpus, cases = load_eval(args.dataset)
    metrics = run_eval(corpus, cases)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 运行测试与脚本,确认通过**

Run: `python3 -m unittest tests.test_verification_eval -v`
Expected: PASS(2 个用例)

Run: `python3 scripts/eval_verification.py`
Expected: 打印含 `"false_accusation_rate": 0.0` 与 `"fabrication_recall": 1.0` 的 JSON 指标

- [ ] **Step 7: 提交**

```bash
git add data/eval/verification_eval.json src/verification/eval.py scripts/eval_verification.py tests/test_verification_eval.py
git commit -m "Add offline reproducible verification evaluation"
```

---

## Task 9: MCP server

**Files:**
- Create: `src/mcp_server/__init__.py`
- Create: `src/mcp_server/server.py`
- Modify: `pyproject.toml`(新增 `[project.optional-dependencies] mcp` 与 `[project.scripts]`)

注:本任务依赖三方包 `mcp`,与项目"运行时零依赖"原则不冲突(它是**可选** extra,核心库与测试都不依赖它)。FastMCP 的 API 按当前稳定形态编写;**Step 1 先核对已安装的 `mcp` 版本 API**。

- [ ] **Step 1: 安装并核对 MCP SDK 的 FastMCP API**

```bash
python3 -m pip install "mcp>=1.2"
python3 -c "from mcp.server.fastmcp import FastMCP; m=FastMCP('t'); print(type(m.tool)); print(hasattr(m,'run'))"
```
Expected: 不报错,打印出 `tool` 装饰器类型与 `True`。
若导入路径不同(老/新版本差异),据实调整 Step 3 中的 `from mcp.server.fastmcp import FastMCP` 与 `mcp.run(...)` 调用,其余逻辑不变。

- [ ] **Step 2: 实现 src/mcp_server/__init__.py**

```python
# src/mcp_server/__init__.py
"""MCP server exposing CiteGuard citation verification tools."""
```

- [ ] **Step 3: 实现 server.py**

```python
# src/mcp_server/server.py
"""FastMCP server: expose verify_citation and audit_citations to MCP clients."""

from __future__ import annotations

import os
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from src.retrieval.scholarly_clients import build_live_metadata_source
from src.verification import (
    CachingMetadataSource,
    audit_citations,
    parse_citation,
    verify_citation,
)

mcp = FastMCP("CiteGuard")


def _build_source():
    names = [n for n in os.environ.get("CITEGUARD_SOURCES", "openalex,crossref,arxiv").split(",") if n.strip()]
    mailto = os.environ.get("CITEGUARD_MAILTO", "research@example.com")
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    live = build_live_metadata_source(names, mailto=mailto, semantic_scholar_api_key=api_key)
    db_path = os.environ.get("CITEGUARD_CACHE", os.path.join("data", "logs", "verification_cache.sqlite"))
    return CachingMetadataSource(live, db_path=db_path)


# Build lazily so that import never triggers network or filesystem work.
_SOURCE = None


def _source():
    global _SOURCE
    if _SOURCE is None:
        _SOURCE = _build_source()
    return _SOURCE


@mcp.tool()
def verify_citation_tool(
    raw_text: str = "",
    title: str = "",
    authors: Optional[List[str]] = None,
    year: Optional[int] = None,
    venue: str = "",
    doi: str = "",
    arxiv_id: str = "",
) -> dict:
    """Verify ONE citation against live scholarly sources (OpenAlex/Crossref/arXiv).

    Provide either a free-text citation in `raw_text`, or structured fields
    (`title`, `authors`, `year`, `doi`, `arxiv_id`, `venue`). Returns a verdict
    (verified | metadata_mismatch | not_found | ambiguous), the canonical record,
    per-field diffs, a suggested corrected citation when confident, and which
    sources were checked. A `not_found` verdict means "could not be verified",
    not a definitive proof of fabrication.
    """
    candidate = parse_citation(
        raw_text=raw_text,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
    )
    return verify_citation(candidate, _source()).to_dict()


@mcp.tool()
def audit_citations_tool(citations: List[dict]) -> dict:
    """Verify MANY citations at once.

    `citations` is a list of objects, each with any of:
    `raw_text`, `title`, `authors`, `year`, `venue`, `doi`, `arxiv_id`.
    Returns a per-citation report plus a summary counting each verdict.
    """
    candidates = [
        parse_citation(
            raw_text=item.get("raw_text", ""),
            title=item.get("title", ""),
            authors=item.get("authors"),
            year=item.get("year"),
            venue=item.get("venue", ""),
            doi=item.get("doi", ""),
            arxiv_id=item.get("arxiv_id", ""),
        )
        for item in citations
    ]
    return audit_citations(candidates, _source()).to_dict()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 修改 pyproject.toml**

在 `[project.optional-dependencies]` 块内新增 `mcp` 组(放在现有 `api` / `models` 旁):

```toml
mcp = [
  "mcp>=1.2",
]
```

在文件中(`[tool.setuptools.packages.find]` 之前)新增控制台入口:

```toml
[project.scripts]
citeguard-mcp = "src.mcp_server.server:main"
```

- [ ] **Step 5: 冒烟验证(import 不触发网络)**

```bash
python3 -c "import src.mcp_server.server as s; print('tools-registered', bool(s.mcp))"
```
Expected: 打印 `tools-registered True`,无网络访问、无异常(数据源是惰性构建)。

手动联网验证(可选,需要网络):
```bash
python3 -c "from src.mcp_server.server import verify_citation_tool as v; import json; print(json.dumps(v(title='Attention Is All You Need', year=2017)['verdict']))"
```
Expected: 打印 `"verified"` 或 `"metadata_mismatch"`(取决于实时元数据)。

- [ ] **Step 6: 运行全量测试,确认无回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS(全绿;MCP server 不在测试内联网)

- [ ] **Step 7: 提交**

```bash
git add src/mcp_server/__init__.py src/mcp_server/server.py pyproject.toml
git commit -m "Add MCP server exposing citation verification tools"
```

---

## Task 10: Claude Code Skill 与 README

**Files:**
- Create: `skills/citeguard-verify/SKILL.md`
- Modify: `README.md`(新增 "Use as an Agent Tool (MCP / Skill)" 一节)

- [ ] **Step 1: 实现 SKILL.md**

```markdown
---
name: citeguard-verify
description: Use when checking, auditing, or fixing citations in scientific or technical writing — verifying that cited papers actually exist and that their metadata (title, authors, year, venue, DOI) is correct against live scholarly sources. Triggers when the user is writing related work / a literature review / a bibliography, pastes references, or asks to "check my citations".
---

# CiteGuard Citation Verification

You verify citations against real scholarly sources before trusting them. You do NOT invent or guess whether a paper exists — you call the CiteGuard MCP tools.

## When to use

- The user is drafting related work, a literature review, or a reference list.
- The user pasted citations / a bibliography and wants them checked.
- You are about to present citations you generated yourself — verify them first.

## How to use

1. For a single citation, call the `verify_citation_tool` MCP tool with structured
   fields (`title`, `authors`, `year`, `doi`, `arxiv_id`) when you have them, or
   `raw_text` for a free-text reference. Identifiers (DOI/arXiv) give the most
   reliable result.
2. For a list, call `audit_citations_tool` with an array of citation objects.
3. Read the `verdict` for each result:
   - `verified` — exists and metadata matches. Safe to keep.
   - `metadata_mismatch` — the paper exists but a field is wrong. Show the wrong
     fields (`field_diffs`) and offer the `suggested_citation` as a fix.
   - `not_found` — could not be verified. Flag it clearly as high-risk and ask the
     user to confirm; do NOT assert it is fabricated.
   - `ambiguous` — multiple plausible matches; ask the user to provide a DOI/arXiv id.

## How to present results

- Use a compact table: `✓ verified` / `⚠ metadata` / `✗ not found` / `? ambiguous`.
- For `metadata_mismatch`, show what is wrong and the suggested correction.
- NEVER silently rewrite the user's citations. Propose changes and let them decide.
- Always mention which sources were checked (`sources_checked`).
```

- [ ] **Step 2: 在 README.md 新增使用说明**

在 README 的 "Quick Start" 之后插入新章节(英文,面向国际受众):

```markdown
## Use as an Agent Tool (MCP / Skill)

CiteGuard can act as a citation-verification tool that other agents (Claude Code,
Codex, Cursor, Cline, …) call to check whether cited papers exist and whether their
metadata is correct.

### MCP server

Install the optional MCP dependency and run the server (stdio transport):

```bash
python -m pip install -e ".[mcp]"
citeguard-mcp
```

Configure it in any MCP-compatible client. Example (Claude Code `mcp` config):

```json
{
  "mcpServers": {
    "citeguard": { "command": "citeguard-mcp" }
  }
}
```

Environment variables: `CITEGUARD_SOURCES` (default `openalex,crossref,arxiv`),
`CITEGUARD_MAILTO`, `SEMANTIC_SCHOLAR_API_KEY`, `CITEGUARD_CACHE`.

Exposed tools:
- `verify_citation_tool` — verify one citation; returns verdict + canonical record +
  field diffs + suggested fix.
- `audit_citations_tool` — verify a list; returns a per-item report and a summary.

A `not_found` verdict means "could not be verified", not a definitive proof of
fabrication. Source outages lower confidence rather than producing false accusations.

### Claude Code skill

`skills/citeguard-verify/SKILL.md` makes Claude Code proactively verify citations
while you write. Copy it into your project's `.claude/skills/` (or a plugin) and keep
the MCP server configured so the skill has tools to call.
```

- [ ] **Step 3: 验证文档无坏链 / 运行全量测试**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS(全绿;本任务不改代码,确认无回归)

- [ ] **Step 4: 提交**

```bash
git add skills/citeguard-verify/SKILL.md README.md
git commit -m "Add Claude Code skill and agent-tool usage docs"
```

---

## 收尾验证

- [ ] **全量测试**

Run: `python3 -m unittest discover -s tests -v`
Expected: 原有 + 新增用例全部 PASS

- [ ] **离线评测**

Run: `python3 scripts/eval_verification.py`
Expected: `false_accusation_rate = 0.0`,`fabrication_recall = 1.0`,`accuracy ≥ 0.9`

- [ ] **MCP import 冒烟**

Run: `python3 -c "import src.mcp_server.server"`
Expected: 无异常、无网络访问

---

## 自检对照(计划 vs spec)

- spec §3 三层架构 → Task 1–7(核心库)、Task 9(MCP)、Task 10(Skill)✅
- spec §4 两个工具 `verify`/`audit` → Task 9 暴露 `verify_citation_tool` / `audit_citations_tool` ✅
- spec §4 出参(verdict/置信度/canonical/field_diffs/suggested/explanation/sources)→ Task 1 `VerificationResult.to_dict()` ✅
- spec §5 流水线(归一化→标识符优先→检索→打分→裁定)→ Task 2 parse、Task 3 resolve、Task 4 verify ✅
- spec §6 防误判红线(源不可达≠不存在、not_found 措辞)→ Task 4 `outage` 说明 + `sources_responded` + "Could not be verified" 措辞 ✅
- spec §7 性能(无模型、缓存、礼貌访问)→ 全程零模型;Task 6 SQLite 缓存;Task 9 复用既有 `HTTPClient`(已带 User-Agent)与 `build_live_metadata_source(mailto=...)` ✅
- spec §8 轻量可信度评测(伪造 P/R、元数据错误、误伤率)→ Task 8 `compute_metrics` ✅
- spec §9 CC Skill 行为(触发、表格呈现、只提议不偷改)→ Task 10 SKILL.md ✅
- spec §10 语言约定(工具/README 英文、spec 中文)→ Task 9/10 工具 docstring 与 README 英文 ✅

> v1 明确不含支撑性 NLI / 矛盾检测 / 写作链路(spec 非目标),保留旧代码不动。
