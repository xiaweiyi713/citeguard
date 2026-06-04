# CiteGuard v2 实现计划:claim 支撑性核验 + 中文支持

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 claim↔paper 支撑性核验(独立工具 `check_claim_support`,4 档弃权优先判定,复用现有 NLI+reranker ensemble),并让整条链路对中文可用。

**Architecture:** 先修中文匹配底层(`normalizer`),再在 `src/verification/support.py` 写 claim-free 支撑包装(逐证据 span 评估 → 4 档映射),复用 v1 `resolve_citation` 定位论文;模型不可用自动降级 heuristic 并如实标注;MCP 暴露新工具,模型名可经 env 配置(多语)。

**Tech Stack:** Python ≥3.9(核心库零三方依赖,`unittest`);可选 `[models]`(transformers/sentence-transformers/torch)仅深度模式用;MCP SDK 仅 server 层用。

**关键事实(实现者必读):**
- 测试用 `unittest`,运行 `python3 -m unittest discover -s tests`。包根目录就叫 `src`。
- 复用 `src/verifiers`(已导出):`SupportAssessment(backend_name, score, passed, rationale, details)`、`SupportBackend`、`HeuristicSupportBackend`、`build_default_support_backend(...)`、`build_production_support_backend(...)`、`DEFAULT_RERANKER_MODEL`、`DEFAULT_NLI_MODEL`。`src/verifiers/support_backends.py` 还有 `split_evidence_text(text)->List[str]`。
- ensemble backend 的 `assess()` 返回的 `SupportAssessment.details["components"]` 是 `[{"backend","score","passed","details"}, ...]`;其中 `backend=="transformers_nli"` 的 component 的 `details["probabilities"]` 形如 `{"entailment","contradiction","neutral"}`。
- 复用 v1:`src/verification` 已导出 `parse_citation`、`verify_citation`、`resolve_citation`、`CachingMetadataSource`、`Verdict` 等;`resolve.py` 有 `STRONG_MATCH=0.70`、`resolve_citation(candidate, source)->ResolveOutcome(best, score, alternatives, sources_checked, sources_responded, ambiguous)`。
- `CitationRecord`(`src/graph`)有 `title/abstract/metadata`,`metadata` 可含 `evidence_chunks`(list of {text, source_field, source_url})。
- ⚠️ 当前 `normalize_text` 用 `re.sub(r"[^a-z0-9\s]", " ", text)` 会把中文删光 —— 这是 Task 1 要修的。
- 提交信息用英文祈使句,**不加** Claude 署名脚注。

---

## 文件结构

```
src/citation/normalizer.py             # MODIFY  Task 1   CJK-aware normalize/tokenize
src/verification/support.py            # CREATE  Task 2-5 SupportVerdict/Result/Policy + assess_support + check_claim_support
src/verification/__init__.py           # MODIFY  Task 6   导出 support 公共 API
src/mcp_server/server.py               # MODIFY  Task 7   check_claim_support_tool + env 模型配置
skills/citeguard-verify/SKILL.md       # MODIFY  Task 8   支撑性使用指引
README.md                              # MODIFY  Task 8   claim-support + 中文说明
data/eval/support_eval.json            # CREATE  Task 9   支撑性评测数据(含中文/neutral/contradiction)
src/verification/support_eval.py       # CREATE  Task 9   评测加载 + 指标
scripts/eval_support.py                # CREATE  Task 9   评测脚本(深度模式本地跑)
docs/chinaxiv_spike.md                 # CREATE  Task 10  ChinaXiv 可行性 spike 结论
tests/test_chinese_normalization.py    # CREATE  Task 1
tests/test_verification_support.py     # CREATE  Task 3-5
tests/test_verification_support_resolve.py # CREATE Task 5 (check_claim_support 端到端)
tests/test_support_eval.py             # CREATE  Task 9
```

实现顺序即任务顺序:**B1 中文匹配 → support 模型/helper/映射/端到端 → 导出 → MCP/文档 → 评测 → ChinaXiv spike**。

---

## Task 1: 中文匹配修复(CJK-aware normalizer)

**Files:**
- Modify: `src/citation/normalizer.py`
- Test: `tests/test_chinese_normalization.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chinese_normalization.py
"""Tests for CJK-aware normalization and tokenization."""

import unittest

from src.citation import normalize_text, sequence_similarity, tokenize_text


class ChineseNormalizationTests(unittest.TestCase):
    def test_normalize_keeps_cjk_characters(self):
        self.assertEqual(normalize_text("深度学习的引用幻觉！"), "深度学习的引用幻觉")

    def test_normalize_still_handles_english(self):
        self.assertEqual(normalize_text("Attention Is All You Need!"), "attention is all you need")

    def test_tokenize_cjk_uses_character_bigrams(self):
        # 4 chars -> 3 bigrams
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
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_chinese_normalization -v`
Expected: FAIL（中文被删光导致多个断言不成立)

- [ ] **Step 3: 修改 `src/citation/normalizer.py`**

把文件顶部 `normalize_text` 与 `tokenize_text` 替换为下面版本(其余 `STOPWORDS`、`sequence_similarity`、`year_matches`、`author_coverage` 不变):

```python
# CJK 统一表意文字主区间(够覆盖常见中文);如需可后续扩展
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
        # split each whitespace chunk into alternating CJK / non-CJK segments
        for segment in re.findall(rf"[{_CJK_PATTERN}]+|[a-z0-9]+", chunk):
            if re.match(rf"[{_CJK_PATTERN}]", segment):
                tokens.extend(_cjk_bigrams(segment))
            elif segment not in STOPWORDS:
                tokens.append(segment)
    return tokens
```

(确保文件已 `import re` 且 `from typing import ... List ...` —— 现有文件已有这些导入。)

- [ ] **Step 4: 运行,确认通过 + 全套无回归**

Run: `python3 -m unittest tests.test_chinese_normalization -v` → PASS(6)
Run: `python3 -m unittest discover -s tests` → 全绿(英文行为不变,v1 用例不回归)

- [ ] **Step 5: 提交**

```bash
git add src/citation/normalizer.py tests/test_chinese_normalization.py
git commit -m "Make text normalization and tokenization CJK-aware"
```

---

## Task 2: 中文核验端到端 sanity(复用 v1 路径)

**Files:**
- Test: `tests/test_chinese_verification.py`（新增,不改产品代码)

验证 Task 1 的修复确实解锁了对中文论文的 v1 核验(纯测试任务,证明底层修复在上层生效)。

- [ ] **Step 1: 写测试**

```python
# tests/test_chinese_verification.py
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
```

- [ ] **Step 2: 运行,确认通过**

Run: `python3 -m unittest tests.test_chinese_verification -v`
Expected: PASS(2)。若 `test_chinese_title_resolves_and_verifies` 失败,说明 Task 1 的 `verification_match_score` 路径对中文 token/相似度仍不足 —— 不要改阈值,回头检查 Task 1 的 bigram/normalize 是否正确,必要时报 BLOCKED。

- [ ] **Step 3: 提交**

```bash
git add tests/test_chinese_verification.py
git commit -m "Add Chinese-language verification regression tests"
```

---

## Task 3: 支撑性数据模型与判定策略

**Files:**
- Create: `src/verification/support.py`
- Test: `tests/test_verification_support.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verification_support.py
"""Tests for claim-support models and verdict mapping."""

import unittest

from src.verification.support import (
    DEFAULT_SUPPORT_POLICY,
    SupportDecisionPolicy,
    SupportResult,
    SupportVerdict,
)


class SupportModelTests(unittest.TestCase):
    def test_default_policy_values(self):
        self.assertEqual(DEFAULT_SUPPORT_POLICY.entail_strong, 0.55)
        self.assertEqual(DEFAULT_SUPPORT_POLICY.contra_strong, 0.55)

    def test_support_result_to_dict(self):
        result = SupportResult(
            verdict=SupportVerdict.SUPPORTED,
            confidence=0.8,
            claim="X improves Y.",
            evidence={"text": "X improves Y by 10%.", "source_field": "abstract_sentence_1", "source_url": ""},
            nli_scores={"entailment": 0.8, "contradiction": 0.05, "neutral": 0.15},
            engine="ensemble",
            resolution={"verdict": "matched", "title": "A Paper", "year": 2024, "sources_checked": ["openalex"]},
            explanation="ok",
            lang="en",
        )
        data = result.to_dict()
        self.assertEqual(data["verdict"], "supported")
        self.assertEqual(data["evidence"]["source_field"], "abstract_sentence_1")
        self.assertEqual(data["nli_scores"]["entailment"], 0.8)
        self.assertEqual(data["engine"], "ensemble")
        self.assertEqual(data["resolution"]["title"], "A Paper")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_support -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.verification.support'`

- [ ] **Step 3: 创建 `src/verification/support.py`(本任务只写模型与策略部分)**

```python
"""Claim-support verification: does a paper support a claim? (abstract-level)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional


class SupportVerdict(str, Enum):
    """Outcome of judging whether a paper supports a claim."""

    SUPPORTED = "supported"
    WEAKLY_SUPPORTED = "weakly_supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTRADICTED = "contradicted"


@dataclass(frozen=True)
class SupportDecisionPolicy:
    """Thresholds controlling the 4-way support verdict mapping."""

    entail_strong: float = 0.55
    entail_weak: float = 0.30
    contra_strong: float = 0.55
    margin: float = 0.05
    relatedness_floor: float = 0.30   # min combined score for a contradiction span to count
    weak_relatedness: float = 0.40    # combined score that yields weakly_supported


DEFAULT_SUPPORT_POLICY = SupportDecisionPolicy()


@dataclass(frozen=True)
class SupportResult:
    """Result of a claim-support check."""

    verdict: SupportVerdict
    confidence: float
    claim: str
    evidence: Dict[str, str]
    nli_scores: Optional[Dict[str, float]]
    engine: str
    resolution: Dict[str, Any]
    explanation: str
    lang: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 4),
            "claim": self.claim,
            "evidence": dict(self.evidence),
            "nli_scores": dict(self.nli_scores) if self.nli_scores else None,
            "engine": self.engine,
            "resolution": dict(self.resolution),
            "explanation": self.explanation,
            "lang": self.lang,
        }
```

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_verification_support -v`
Expected: PASS(2)

- [ ] **Step 5: 提交**

```bash
git add src/verification/support.py tests/test_verification_support.py
git commit -m "Add claim-support models and decision policy"
```

---

## Task 4: 证据 span 构建与 NLI 抽取 helper

**Files:**
- Modify: `src/verification/support.py`
- Test: `tests/test_verification_support.py`（追加用例)

- [ ] **Step 1: 追加失败测试**

在 `tests/test_verification_support.py` 顶部补充 import,并新增一个测试类:

```python
from src.graph import CitationRecord
from src.verifiers import SupportAssessment
from src.verification.support import _extract_nli, build_evidence_spans


class SupportHelperTests(unittest.TestCase):
    def test_build_evidence_spans_from_title_abstract_chunks(self):
        citation = CitationRecord(
            citation_id="c",
            title="A Title",
            abstract="First sentence here. Second sentence about X improving Y.",
            metadata={"evidence_chunks": [{"text": "Chunk text.", "source_field": "openalex_remote_1", "source_url": "http://e"}]},
        )
        spans = build_evidence_spans(citation)
        texts = [s["text"] for s in spans]
        self.assertIn("A Title", texts)
        self.assertTrue(any("Second sentence about X" in t for t in texts))
        self.assertTrue(any(s["source_url"] == "http://e" for s in spans))

    def test_extract_nli_from_ensemble_components(self):
        ensemble = SupportAssessment(
            backend_name="ensemble_support",
            score=0.6,
            passed=True,
            rationale="x",
            details={"components": [
                {"backend": "transformers_nli", "score": 0.7, "passed": True,
                 "details": {"probabilities": {"entailment": 0.7, "contradiction": 0.1, "neutral": 0.2}}},
                {"backend": "heuristic_support", "score": 0.5, "passed": True, "details": {}},
            ]},
        )
        nli = _extract_nli(ensemble)
        self.assertEqual(nli["entailment"], 0.7)

    def test_extract_nli_none_for_heuristic(self):
        heuristic = SupportAssessment(backend_name="heuristic_support", score=0.5, passed=True, rationale="x", details={})
        self.assertIsNone(_extract_nli(heuristic))
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_support -v`
Expected: FAIL — `ImportError: cannot import name 'build_evidence_spans'`

- [ ] **Step 3: 在 `support.py` 追加 helper(import 段补充 List/Tuple + 依赖)**

在 `support.py` 顶部 import 区补充(把 Task 3 的 `from typing import Any, Dict, Optional` 扩成下面这行):

```python
from typing import Any, Dict, List, Optional

from src.graph import CitationRecord
from src.verifiers import SupportAssessment
from src.verifiers.support_backends import split_evidence_text
```

在文件末尾追加:

```python
def build_evidence_spans(citation: CitationRecord) -> List[Dict[str, str]]:
    """Candidate evidence spans: title + abstract sentences + metadata chunks."""

    spans: List[Dict[str, str]] = []
    seen = set()

    def add(text: str, source_field: str, source_url: str = "") -> None:
        cleaned = " ".join(str(text).split())
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        spans.append({"text": cleaned, "source_field": source_field, "source_url": source_url})

    if citation.title:
        add(citation.title, "title")
    if citation.abstract:
        for index, sentence in enumerate(split_evidence_text(citation.abstract), start=1):
            add(sentence, f"abstract_sentence_{index}")
    for index, chunk in enumerate(citation.metadata.get("evidence_chunks", []), start=1):
        if isinstance(chunk, dict):
            add(chunk.get("text", ""), str(chunk.get("source_field", f"metadata_chunk_{index}")), str(chunk.get("source_url", "")))
        else:
            add(str(chunk), f"metadata_chunk_{index}")
    return spans


def _extract_nli(assessment: SupportAssessment) -> Optional[Dict[str, float]]:
    """Pull NLI probabilities out of an ensemble or NLI assessment, if present."""

    if assessment.backend_name == "transformers_nli":
        probs = assessment.details.get("probabilities")
        return dict(probs) if probs else None
    if assessment.backend_name == "ensemble_support":
        for component in assessment.details.get("components", []):
            if component.get("backend") == "transformers_nli":
                probs = component.get("details", {}).get("probabilities")
                return dict(probs) if probs else None
    return None
```

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_verification_support -v` → PASS(5)

- [ ] **Step 5: 提交**

```bash
git add src/verification/support.py tests/test_verification_support.py
git commit -m "Add evidence-span builder and NLI extraction helper"
```

---

## Task 5: assess_support 判定映射 + check_claim_support 端到端

**Files:**
- Modify: `src/verification/support.py`
- Test: `tests/test_verification_support.py`（追加映射用例)
- Test: `tests/test_verification_support_resolve.py`（端到端)

- [ ] **Step 1: 追加映射失败测试(合成 backend,无模型)**

在 `tests/test_verification_support.py` 追加:

```python
from src.verification.support import assess_support


class _FakeBackend:
    """Returns a preset SupportAssessment per evidence text (keyword-matched)."""

    def __init__(self, table, ensemble=True):
        self.table = table          # {substring: (score, probs_or_None)}
        self.ensemble = ensemble

    def assess(self, claim_text, evidence_text):
        score, probs = 0.0, None
        for key, (s, p) in self.table.items():
            if key in evidence_text:
                score, probs = s, p
                break
        if self.ensemble and probs is not None:
            return SupportAssessment(
                backend_name="ensemble_support", score=score, passed=score >= 0.5, rationale="x",
                details={"components": [
                    {"backend": "transformers_nli", "score": probs["entailment"], "passed": False, "details": {"probabilities": probs}},
                    {"backend": "heuristic_support", "score": score, "passed": False, "details": {}},
                ]},
            )
        return SupportAssessment(backend_name="heuristic_support", score=score, passed=score >= 0.5, rationale="x", details={})


def _paper(abstract):
    return CitationRecord(citation_id="p", title="Some Paper", abstract=abstract, source="memory")


class AssessSupportTests(unittest.TestCase):
    def test_supported_when_entailment_strong(self):
        backend = _FakeBackend({"X improves Y": (0.6, {"entailment": 0.8, "contradiction": 0.05, "neutral": 0.15})})
        result = assess_support("X improves Y.", _paper("Study shows X improves Y in trials."), backend)
        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.engine, "ensemble")

    def test_contradicted_when_contradiction_strong_and_related(self):
        backend = _FakeBackend({"X improves Y": (0.6, {"entailment": 0.05, "contradiction": 0.8, "neutral": 0.15})})
        result = assess_support("X improves Y.", _paper("We find X improves Y is false; X does not improve Y."), backend)
        self.assertEqual(result.verdict, SupportVerdict.CONTRADICTED)

    def test_insufficient_when_neutral(self):
        backend = _FakeBackend({"unrelated topic": (0.1, {"entailment": 0.1, "contradiction": 0.1, "neutral": 0.8})})
        result = assess_support("X improves Y.", _paper("This is an unrelated topic about birds."), backend)
        self.assertEqual(result.verdict, SupportVerdict.INSUFFICIENT_EVIDENCE)

    def test_heuristic_engine_never_contradicts(self):
        backend = _FakeBackend({"X improves Y": (0.7, None)}, ensemble=False)
        result = assess_support("X improves Y.", _paper("X improves Y greatly."), backend)
        self.assertEqual(result.engine, "heuristic")
        self.assertIn(result.verdict, (SupportVerdict.WEAKLY_SUPPORTED, SupportVerdict.INSUFFICIENT_EVIDENCE))
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_support -v`
Expected: FAIL — `ImportError: cannot import name 'assess_support'`

- [ ] **Step 3: 在 `support.py` 追加 `assess_support` 与 `check_claim_support`**

import 区补充:

```python
from src.retrieval.scholarly_clients.base import MetadataSource
from src.verifiers import SupportBackend, build_default_support_backend

from .resolve import STRONG_MATCH, resolve_citation
```

文件末尾追加:

```python
def _prob(nli: Optional[Dict[str, float]], key: str) -> float:
    return float(nli.get(key, 0.0)) if nli else 0.0


def assess_support(
    claim: str,
    citation: CitationRecord,
    backend: Optional[SupportBackend] = None,
    policy: SupportDecisionPolicy = DEFAULT_SUPPORT_POLICY,
    lang: str = "",
    resolution: Optional[Dict[str, Any]] = None,
) -> SupportResult:
    """Judge whether `citation` supports `claim`, over abstract-level evidence."""

    backend = backend or build_default_support_backend()
    resolution = resolution if resolution is not None else {"verdict": "matched", "title": citation.title}

    spans = build_evidence_spans(citation)
    if not spans:
        return SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE, confidence=0.0, claim=claim,
            evidence={"text": "", "source_field": "none", "source_url": ""}, nli_scores=None,
            engine="heuristic", resolution=resolution,
            explanation="No abstract or evidence text was available to judge support.", lang=lang,
        )

    assessed = []  # (span, assessment, nli)
    for span in spans:
        assessment = backend.assess(claim, span["text"])
        assessed.append((span, assessment, _extract_nli(assessment)))

    engine = "ensemble" if any(nli for _, _, nli in assessed) else "heuristic"
    best_score_span, best_score_assessment, _ = max(assessed, key=lambda item: item[1].score)
    best_score = best_score_assessment.score

    if engine == "ensemble":
        ent_span, _, ent_nli = max(assessed, key=lambda item: _prob(item[2], "entailment"))
        entailment = _prob(ent_nli, "entailment")
        ent_contra = _prob(ent_nli, "contradiction")
        related = [item for item in assessed if item[1].score >= policy.relatedness_floor]
        con_span, _, con_nli = max(
            related or assessed, key=lambda item: _prob(item[2], "contradiction")
        )
        contradiction = _prob(con_nli, "contradiction") if related else 0.0

        if entailment >= policy.entail_strong and entailment >= ent_contra + policy.margin:
            return _result(SupportVerdict.SUPPORTED, entailment, claim, ent_span, ent_nli, engine, resolution,
                           "The abstract entails the claim.", lang)
        if contradiction >= policy.contra_strong:
            return _result(SupportVerdict.CONTRADICTED, contradiction, claim, con_span, con_nli, engine, resolution,
                           "The abstract contradicts the claim.", lang)
        if entailment >= policy.entail_weak or best_score >= policy.weak_relatedness:
            span = ent_span if entailment >= best_score else best_score_span
            return _result(SupportVerdict.WEAKLY_SUPPORTED, max(entailment, best_score), claim, span, ent_nli, engine,
                           resolution, "Partial or related evidence, but not strong enough.", lang)
        return _result(SupportVerdict.INSUFFICIENT_EVIDENCE, round(1.0 - best_score, 4), claim, best_score_span, ent_nli,
                       engine, resolution, "The abstract does not address the claim (cannot confirm).", lang)

    # heuristic engine: never SUPPORTED/CONTRADICTED (lexical overlap can't prove either)
    if best_score >= policy.weak_relatedness:
        return _result(SupportVerdict.WEAKLY_SUPPORTED, best_score, claim, best_score_span, None, engine, resolution,
                       "Lexical overlap suggests relatedness; deep models not loaded.", lang)
    return _result(SupportVerdict.INSUFFICIENT_EVIDENCE, round(1.0 - best_score, 4), claim, best_score_span, None, engine,
                   resolution, "Insufficient lexical overlap; deep models not loaded.", lang)


def _result(verdict, confidence, claim, span, nli, engine, resolution, explanation, lang) -> SupportResult:
    return SupportResult(
        verdict=verdict, confidence=round(float(confidence), 4), claim=claim,
        evidence={"text": span["text"], "source_field": span["source_field"], "source_url": span.get("source_url", "")},
        nli_scores=nli, engine=engine, resolution=resolution, explanation=explanation, lang=lang,
    )


def check_claim_support(
    claim: str,
    candidate: CitationRecord,
    source: MetadataSource,
    backend: Optional[SupportBackend] = None,
    policy: SupportDecisionPolicy = DEFAULT_SUPPORT_POLICY,
    lang: str = "",
) -> SupportResult:
    """Resolve the cited paper, then judge whether it supports the claim."""

    outcome = resolve_citation(candidate, source)
    checked = outcome.sources_checked
    if outcome.best is None or outcome.score < STRONG_MATCH:
        return SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE, confidence=0.0, claim=claim,
            evidence={"text": "", "source_field": "none", "source_url": ""}, nli_scores=None, engine="none",
            resolution={"verdict": "not_found", "sources_checked": checked},
            explanation=f"Could not locate the paper in {', '.join(checked)}; cannot judge support. Provide a DOI/arXiv id.",
            lang=lang,
        )
    if outcome.ambiguous:
        return SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE, confidence=0.0, claim=claim,
            evidence={"text": "", "source_field": "none", "source_url": ""}, nli_scores=None, engine="none",
            resolution={"verdict": "ambiguous", "sources_checked": checked},
            explanation="The citation is ambiguous; provide a DOI/arXiv id before judging support.", lang=lang,
        )
    resolution = {
        "verdict": "matched",
        "title": outcome.best.title,
        "year": outcome.best.year,
        "sources_checked": checked,
    }
    return assess_support(claim, outcome.best, backend=backend, policy=policy, lang=lang, resolution=resolution)
```

- [ ] **Step 4: 运行映射测试,确认通过**

Run: `python3 -m unittest tests.test_verification_support -v` → PASS(9)

- [ ] **Step 5: 写 check_claim_support 端到端测试**

```python
# tests/test_verification_support_resolve.py
"""End-to-end check_claim_support over an in-memory source (no models, no network)."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verifiers import SupportAssessment
from src.verification.parse import parse_citation
from src.verification.support import SupportVerdict, check_claim_support


class _FakeEnsembleBackend:
    def assess(self, claim_text, evidence_text):
        probs = {"entailment": 0.82, "contradiction": 0.05, "neutral": 0.13} if "improves" in evidence_text else {"entailment": 0.1, "contradiction": 0.1, "neutral": 0.8}
        return SupportAssessment(
            backend_name="ensemble_support", score=0.6, passed=True, rationale="x",
            details={"components": [{"backend": "transformers_nli", "score": probs["entailment"], "passed": True, "details": {"probabilities": probs}}]},
        )


class CheckClaimSupportTests(unittest.TestCase):
    def setUp(self):
        self.paper = CitationRecord(
            citation_id="p1", title="Method M for Task T", abstract="We show method M improves task T accuracy.",
            authors=["A. Author"], year=2024, source="memory",
        )
        self.source = InMemoryMetadataSource([self.paper])

    def test_supported_end_to_end(self):
        candidate = parse_citation(title="Method M for Task T", year=2024)
        result = check_claim_support("Method M improves task T.", candidate, self.source, backend=_FakeEnsembleBackend())
        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.resolution["verdict"], "matched")

    def test_unresolved_paper_is_insufficient_not_unsupported(self):
        candidate = parse_citation(title="A Paper That Does Not Exist Anywhere")
        result = check_claim_support("Some claim.", candidate, self.source, backend=_FakeEnsembleBackend())
        self.assertEqual(result.verdict, SupportVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(result.resolution["verdict"], "not_found")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: 运行,确认通过 + 全套**

Run: `python3 -m unittest tests.test_verification_support_resolve -v` → PASS(2)
Run: `python3 -m unittest discover -s tests` → 全绿

- [ ] **Step 7: 提交**

```bash
git add src/verification/support.py tests/test_verification_support.py tests/test_verification_support_resolve.py
git commit -m "Add claim-support verdict mapping and check_claim_support"
```

---

## Task 6: 包导出

**Files:**
- Modify: `src/verification/__init__.py`
- Test: `tests/test_verification_support_resolve.py`（追加 import 断言)

- [ ] **Step 1: 追加失败测试**

在 `tests/test_verification_support_resolve.py` 末尾(类外)新增:

```python
class SupportExportTests(unittest.TestCase):
    def test_support_api_exported_from_package(self):
        from src.verification import (
            SupportDecisionPolicy,
            SupportResult,
            SupportVerdict,
            assess_support,
            check_claim_support,
        )
        self.assertTrue(callable(check_claim_support))
        self.assertTrue(callable(assess_support))
        self.assertEqual(SupportVerdict.SUPPORTED.value, "supported")
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_verification_support_resolve.SupportExportTests -v`
Expected: FAIL — `ImportError: cannot import name 'check_claim_support' from 'src.verification'`

- [ ] **Step 3: 修改 `src/verification/__init__.py`**

在现有 import 与 `__all__` 中加入 support 符号(与现有风格一致):

```python
from .support import (
    DEFAULT_SUPPORT_POLICY,
    SupportDecisionPolicy,
    SupportResult,
    SupportVerdict,
    assess_support,
    check_claim_support,
)
```

并把 `"DEFAULT_SUPPORT_POLICY", "SupportDecisionPolicy", "SupportResult", "SupportVerdict", "assess_support", "check_claim_support"` 加入 `__all__`(保持字母序)。

- [ ] **Step 4: 运行,确认通过 + 全套**

Run: `python3 -m unittest tests.test_verification_support_resolve -v` → PASS(3)
Run: `python3 -m unittest discover -s tests` → 全绿

- [ ] **Step 5: 提交**

```bash
git add src/verification/__init__.py tests/test_verification_support_resolve.py
git commit -m "Export claim-support public API"
```

---

## Task 7: MCP 工具 + 多语模型 env 配置(B2)

**Files:**
- Modify: `src/mcp_server/server.py`

注:测试套件不导入 `src/mcp_server`,本任务靠 import 冒烟验证(需 `.venv` 里的 mcp,见 v1 经验:默认 python 3.9 装不了 mcp,用 Python ≥3.10 的 venv)。

- [ ] **Step 1: 在 `server.py` 增加 support backend 构建 + 新工具**

在 import 区补充:

```python
from src.verification import check_claim_support
```

在 `_source()` 之后追加惰性 support backend(读 env 模型名,模型缺失会自动降级 heuristic):

```python
_SUPPORT_BACKEND = None


def _support_backend():
    global _SUPPORT_BACKEND
    if _SUPPORT_BACKEND is None:
        from src.verifiers import (
            DEFAULT_NLI_MODEL,
            DEFAULT_RERANKER_MODEL,
            build_production_support_backend,
        )
        reranker = os.environ.get("CITEGUARD_RERANKER_MODEL", DEFAULT_RERANKER_MODEL)
        nli = os.environ.get("CITEGUARD_NLI_MODEL", DEFAULT_NLI_MODEL)
        _SUPPORT_BACKEND = build_production_support_backend(
            reranker_model_name=reranker, nli_model_name=nli
        )
    return _SUPPORT_BACKEND
```

在文件中(其它 `@mcp.tool()` 旁)新增工具:

```python
@mcp.tool()
def check_claim_support_tool(
    claim: str,
    raw_text: str = "",
    title: str = "",
    authors: Optional[List[str]] = None,
    year: Optional[int] = None,
    venue: str = "",
    doi: str = "",
    arxiv_id: str = "",
    lang: str = "",
) -> dict:
    """Judge whether a cited paper SUPPORTS a claim sentence (abstract-level).

    Resolves the paper (existence), then assesses support with a reranker+NLI
    ensemble. Verdicts: supported | weakly_supported | insufficient_evidence |
    contradicted. `insufficient_evidence` means the abstract does not address the
    claim — NOT that the paper is unsupportive. Deep models are downloaded on first
    use; without them the engine falls back to "heuristic" (no supported/contradicted
    verdicts) and says so. Set CITEGUARD_RERANKER_MODEL / CITEGUARD_NLI_MODEL to use
    multilingual models for non-English claims.
    """
    candidate = parse_citation(
        raw_text=raw_text, title=title, authors=authors, year=year, venue=venue, doi=doi, arxiv_id=arxiv_id
    )
    return check_claim_support(claim, candidate, _source(), backend=_support_backend(), lang=lang).to_dict()
```

- [ ] **Step 2: import 冒烟(默认 python3 即可——import 不应触发模型/网络)**

Run: `python3 -c "import ast; ast.parse(open('src/mcp_server/server.py').read()); print('syntax OK')"`
Expected: `syntax OK`（默认 3.9 没装 mcp,无法真正 import；语法检查确保无错。)

若有 Python ≥3.10 + `pip install -e ".[mcp]"` 的环境(如 v1 用的 `.venv`):
Run: `.venv/bin/python -c "import src.mcp_server.server as s; print('tools', hasattr(s, 'check_claim_support_tool'))"`
Expected: `tools True`，无网络、无模型下载(惰性构建)。

- [ ] **Step 3: 全套测试无回归**

Run: `python3 -m unittest discover -s tests` → 全绿(server 不在测试内)

- [ ] **Step 4: 提交**

```bash
git add src/mcp_server/server.py
git commit -m "Add check_claim_support MCP tool with configurable support models"
```

---

## Task 8: SKILL.md + README 文档

**Files:**
- Modify: `skills/citeguard-verify/SKILL.md`
- Modify: `README.md`

- [ ] **Step 1: 更新 `SKILL.md`**

在 `## How to use` 列表后、`## How to present results` 前,新增一节(英文):

```markdown
## Checking claim support (deep mode)

After verifying a citation exists, you can check whether the paper actually supports
the sentence: call `check_claim_support_tool` with the `claim` sentence plus the
citation fields. Verdicts:
- `supported` / `weakly_supported` — the abstract entails (or partially supports) the claim.
- `insufficient_evidence` — the abstract does NOT address the claim. Present this as
  "the abstract can't confirm this — check the full text or a human", NOT as "the paper
  does not support it".
- `contradicted` — the abstract actively contradicts the claim; highlight as high-risk.

Notes: deep mode needs models (downloaded on first use; slow). If `engine` is
`"heuristic"`, say the result is weak (deep models not loaded), and never report
`contradicted` in that mode. For non-English claims, multilingual models can be
configured via environment variables.
```

- [ ] **Step 2: 更新 `README.md`**

在 `### Claude Code skill` 小节之前(`## Use as an Agent Tool` 章节内)新增:

```markdown
### Claim support (deep mode, v2)

Beyond existence/metadata, `check_claim_support_tool` judges whether a paper actually
**supports a claim sentence**, using a reranker + NLI ensemble over the abstract.
Verdicts: `supported` / `weakly_supported` / `insufficient_evidence` / `contradicted`.
It is abstain-leaning: when the abstract does not address the claim it returns
`insufficient_evidence` (not "unsupported"). Deep models are downloaded on first use
(`pip install -e ".[models]"`, Python ≥ 3.10); without them it falls back to a labelled
`heuristic` engine. Pre-download with `python3 scripts/warmup_support_models.py`.
```

在 `## 中文说明` 节内补一段:

```markdown
**中文支持**:文本匹配已支持中文(CJK 分词 + 字符二元组),可核验 OpenAlex/Crossref 中已收录的中文论文。支撑性深度模式判定中文 claim 时,建议用环境变量配置多语模型:`CITEGUARD_RERANKER_MODEL`、`CITEGUARD_NLI_MODEL`。知网/万方无开放免费 API,本项目不直连、不爬取受限内容。
```

- [ ] **Step 3: 全套测试无回归(文档任务)**

Run: `python3 -m unittest discover -s tests` → 全绿

- [ ] **Step 4: 提交**

```bash
git add skills/citeguard-verify/SKILL.md README.md
git commit -m "Document claim-support deep mode and Chinese support"
```

---

## Task 9: 支撑性评测(数据 + 指标 + 脚本)

**Files:**
- Create: `data/eval/support_eval.json`
- Create: `src/verification/support_eval.py`
- Create: `scripts/eval_support.py`
- Test: `tests/test_support_eval.py`

设计:评测在 (claim, evidence_text, gold) 三元组上**直接跑 backend**(不需 resolve),含中英文 + supported/neutral/contradiction。`compute_support_metrics` 在合成预测上确定性可测(CI 安全);完整模型版由 `scripts/eval_support.py` 本地跑(需 `[models]`)。

- [ ] **Step 1: 创建 `data/eval/support_eval.json`**

```json
{
  "cases": [
    {"id": "s01", "claim": "Method M improves task T accuracy.", "evidence": "We show method M improves task T accuracy by 5 points.", "gold": "supported", "lang": "en"},
    {"id": "s02", "claim": "Retrieval-augmented models synthesize scientific literature.", "evidence": "OpenScholar synthesizes scientific literature with retrieval-augmented language models.", "gold": "supported", "lang": "en"},
    {"id": "s03", "claim": "The method improves accuracy.", "evidence": "This paper surveys unrelated hardware power-management techniques.", "gold": "insufficient_evidence", "lang": "en"},
    {"id": "s04", "claim": "Model M increases accuracy on task T.", "evidence": "We find that model M does not improve, and in fact reduces, accuracy on task T.", "gold": "contradicted", "lang": "en"},
    {"id": "s05", "claim": "大语言模型存在引用幻觉问题。", "evidence": "本文分析了大语言模型在学术写作中的引用幻觉与伪造参考文献问题。", "gold": "supported", "lang": "zh"},
    {"id": "s06", "claim": "该方法显著提升了检索准确率。", "evidence": "本文主要讨论了一种无关的图像压缩算法。", "gold": "insufficient_evidence", "lang": "zh"}
  ]
}
```

- [ ] **Step 2: 写失败测试**

```python
# tests/test_support_eval.py
"""Tests for the support evaluation harness (metrics are model-free / synthetic)."""

import os
import unittest

from src.verification.support_eval import compute_support_metrics, load_support_eval


class SupportEvalTests(unittest.TestCase):
    def test_compute_metrics_counts_correct_and_misjudgments(self):
        preds = [
            ("supported", "supported"),
            ("contradicted", "contradicted"),
            ("insufficient_evidence", "insufficient_evidence"),
            ("supported", "contradicted"),  # a misjudged true-support
        ]
        m = compute_support_metrics(preds)
        self.assertEqual(m["n"], 4)
        self.assertEqual(m["accuracy"], 0.75)
        # supported wrongly called contradicted/insufficient counts as misjudged support
        self.assertEqual(m["misjudged_support_rate"], 0.5)

    def test_load_support_eval_reads_seed_file(self):
        cases = load_support_eval(os.path.join("data", "eval", "support_eval.json"))
        self.assertGreaterEqual(len(cases), 6)
        self.assertIn(cases[0].gold, {"supported", "weakly_supported", "insufficient_evidence", "contradicted"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行,确认失败**

Run: `python3 -m unittest tests.test_support_eval -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.verification.support_eval'`

- [ ] **Step 4: 实现 `src/verification/support_eval.py`**

```python
"""Offline evaluation of claim-support assessment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Tuple

from src.graph import CitationRecord
from src.verifiers import SupportBackend

from .support import assess_support


@dataclass(frozen=True)
class SupportCase:
    case_id: str
    claim: str
    evidence: str
    gold: str
    lang: str = ""


def load_support_eval(path: str) -> List[SupportCase]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return [
        SupportCase(c["id"], c["claim"], c["evidence"], c["gold"], c.get("lang", ""))
        for c in data["cases"]
    ]


def run_support_eval(cases: List[SupportCase], backend: SupportBackend) -> Dict[str, float]:
    preds: List[Tuple[str, str]] = []
    for case in cases:
        paper = CitationRecord(citation_id=case.case_id, title="", abstract=case.evidence, source="eval")
        result = assess_support(case.claim, paper, backend=backend, lang=case.lang)
        preds.append((case.gold, result.verdict.value))
    return compute_support_metrics(preds)


def compute_support_metrics(preds: List[Tuple[str, str]]) -> Dict[str, float]:
    n = len(preds)
    correct = sum(1 for gold, pred in preds if gold == pred)
    supported_total = sum(1 for gold, _ in preds if gold == "supported")
    misjudged_support = sum(
        1 for gold, pred in preds if gold == "supported" and pred in ("contradicted", "insufficient_evidence")
    )
    contra_total = sum(1 for gold, _ in preds if gold == "contradicted")
    contra_hit = sum(1 for gold, pred in preds if gold == "contradicted" and pred == "contradicted")
    return {
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "misjudged_support_rate": round(misjudged_support / supported_total, 4) if supported_total else 0.0,
        "contradiction_recall": round(contra_hit / contra_total, 4) if contra_total else 0.0,
    }
```

- [ ] **Step 5: 实现 `scripts/eval_support.py`**

```python
"""Run the claim-support evaluation. Needs the [models] extra for the deep engine."""

from __future__ import annotations

import argparse
import json

from _bootstrap import ensure_project_root

ensure_project_root()

from src.verifiers import build_production_support_backend
from src.verification.support_eval import load_support_eval, run_support_eval


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CiteGuard claim-support assessment.")
    parser.add_argument("--dataset", default="data/eval/support_eval.json")
    args = parser.parse_args()
    cases = load_support_eval(args.dataset)
    metrics = run_support_eval(cases, build_production_support_backend())
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 运行测试,确认通过**

Run: `python3 -m unittest tests.test_support_eval -v` → PASS(2)
Run: `python3 -m unittest discover -s tests` → 全绿
(注:`scripts/eval_support.py` 真跑需要 `[models]` + 网络下模型,本任务不要求实跑;`_bootstrap` 已存在于 `scripts/`。)

- [ ] **Step 7: 提交**

```bash
git add data/eval/support_eval.json src/verification/support_eval.py scripts/eval_support.py tests/test_support_eval.py
git commit -m "Add claim-support evaluation harness and seed dataset"
```

---

## Task 10: ChinaXiv 可行性 spike(B3)

**Files:**
- Create: `docs/chinaxiv_spike.md`

这是**调研任务**,交付物是结论文档与 go/no-go;不写推测性适配器代码。

- [ ] **Step 1: 探测候选开放端点**

依次尝试(允许失败,记录结果):

```bash
curl -sS -m 20 -A "CiteGuard/0.2 (mailto:research@example.com)" "https://www.chinaxiv.org/oai/OAIHandler?verb=Identify" | head -40
curl -sS -m 20 "http://chinaxiv.org/oai/OAIHandler?verb=Identify" | head -40
curl -sS -m 20 "https://www.chinaxiv.org/home.htm" -o /dev/null -w "%{http_code}\n"
```

也可用项目内 `HTTPClient` 试 `get_text`,看是否拿到结构化(OAI XML / JSON)响应。

- [ ] **Step 2: 写结论文档 `docs/chinaxiv_spike.md`**

记录:尝试过的 URL、返回(状态码/片段/是否需鉴权/是否结构化)、能否在不爬取受限内容的前提下取得元数据,并给出明确结论:

- **GO**:有可用开放端点 → 给出端点、响应格式样例,并在文档末尾列出"下一步:实现 `ChinaxivMetadataSource`(仿 `crossref.py`/`openalex.py`,带 Fake-HTTP 单测),接入 `build_live_metadata_source` 源名表"作为后续任务(本计划不强行实现,留作 follow-up issue)。
- **NO-GO**:无可用开放端点 → 文档说明原因,结论为"暂不接入;保留可插拔 `MetadataSource` 接口,待端点确认后再加"。

- [ ] **Step 3: 提交**

```bash
git add docs/chinaxiv_spike.md
git commit -m "Add ChinaXiv open-endpoint feasibility spike findings"
```

---

## 收尾验证

- [ ] **全量测试**

Run: `python3 -m unittest discover -s tests -v`
Expected: v1 + v2 全部 PASS,英文用例零回归,新增中文/支撑用例全绿。

- [ ] **支撑性评测(heuristic,CI 安全)**

可选:`python3 -c "from _bootstrap import ensure_project_root as e; e(); from src.verifiers import build_default_support_backend; from src.verification.support_eval import load_support_eval, run_support_eval; print(run_support_eval(load_support_eval('data/eval/support_eval.json'), build_default_support_backend()))"`
(heuristic 引擎下不会产出 supported/contradicted;此处仅确认链路跑通、不报错。深度指标用 `scripts/eval_support.py` + `[models]` 本地看。)

---

## 自检对照(计划 vs spec)

- spec §3.1 独立工具 + 内部 resolve → Task 5 `check_claim_support` + Task 7 工具 ✅
- spec §3.2 四档弃权优先 → Task 3 `SupportVerdict` + Task 5 映射 ✅
- spec §3.3 判定映射(best entailment / best contradiction / 弃权)→ Task 5 `assess_support` ✅
- spec §3.4 引擎降级、heuristic 不产 contradicted、warmup → Task 5(heuristic 分支)+ Task 7(env)+ Task 8(文档)✅
- spec §3.5 SupportResult 字段 → Task 3 `to_dict` ✅
- spec §B1 CJK normalize/tokenize + 零回归 → Task 1、Task 2 ✅
- spec §B2 env 模型名 + lang 透传 → Task 7 + `assess_support(lang=...)` ✅
- spec §B3 ChinaXiv spike + go/no-go → Task 10 ✅
- spec §5 MCP/库/skill/README → Task 6/7/8 ✅
- spec §6 合成单测 + 模型版 eval 脚本 → Task 5/9 ✅
- spec 非目标(知网/万方直连、全文级、多篇支撑)→ 未纳入,符合 ✅
