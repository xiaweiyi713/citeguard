# M1 实现计划:信任与速度攻坚(P0-1 … P0-5)

> **For agentic workers:** 按任务顺序执行,TDD(先写失败测试),每任务独立提交。规格来源:`docs/improvement_proposal_2026-07.md` §3 P0 部分。分支:`fix/m1-trust-and-speed`。

**Goal:** 修复两个 P0 断层——标识符被静默丢弃导致正确引用被误判(信任),以及全串行多源导致单条核验 15–107s(速度)——并用金标 canary 把修复钉死。

**Architecture:** 在适配器层新增严格的 `lookup_identifier`(仅按 id 查、不落标题);resolve 层新增"标识符权威裁决"前置步骤(hit 必胜 / failed 降级 / miss 记录),并加入污染记录防御(年份共识、可疑记录启发);multi-source 层用 `ThreadPoolExecutor` 跨源并发 + 时间预算;verify 层把 id 失败降级为 `ambiguous + outage_limited`,门禁 `suggested_citation`。全部走既有 failure-details 通道,不引入新依赖。

**Tech Stack:** 标准库(`concurrent.futures`);`unittest`;不新增三方依赖。

**关键事实(实现者必读):**
- 测试:`python3 -m unittest discover -s tests`(545 个,全绿是底线)。包名 `citeguard`,分支 `fix/m1-trust-and-speed`,提交信息英文祈使句、**不加** AI 署名。
- `ResolveOutcome`(`citeguard/verification/resolve.py:19-28`)是 frozen dataclass,仅在本文件 2 处**位置参数**构造(`:105`、`:115`)——新增字段必须放末尾带默认值,并同步改这两处。
- `VerificationResult` 在 `citeguard/verification/models.py:172` 起,已有 `sources_failed / source_failure_details / source_failure_mode / outage_limited / doi_registration / alternatives` 等字段;`to_dict()` 在 `:191`;`next_action` 由 `verification_next_action(verdict, failure_mode, failed)` 推导——**id 失败只要把失败细节并入 failed/details,next_action 就会自动变为 inspect/retry,无需改该函数**。
- `verify.py` 现状(177 行):NOT_FOUND 分支已处理 outage 降置信 + DOI 注册表兜底;AMBIGUOUS/MISMATCH/VERIFIED 分支均已透传 failure 字段。
- `HTTPClient`(`http.py`)失败后设置 `last_error_code/last_error_kind/last_status_code/...`,**成功的下一次请求会清空它们**——这正是 arXiv id 查询失败被标题搜索"洗白"的机制,权威裁决必须在 id 请求后**立即**读取状态。
- `crossref.py:76-90` 的 `lookup` 已含 DOI 直查分支(`{BASE_URL}/{quote(normalize_doi(...))}`),抽取复用即可;`arxiv.py:55-72` 的 `lookup` 含 id_list 分支,同样抽取。
- `runtime.py:687` 是 MCP/CLI 建源点(已显式传 `harvest_remote_evidence=remote_evidence_enabled(env)`);`factory.py:30` 的库默认 `True` 要翻成 `False`。
- MCP 契约测试(`tests/test_mcp_server.py` 等)可能对 `to_dict()` 键集合有严格断言——新增 `identifier_lookup` 键后按契约同步更新测试与 `docs/agent_output_contract.md`,**不得**为过测试而隐藏新字段。
- 沿用项目红线:任何降级都不得表述为"伪造";`not_found`/`ambiguous` 措辞一律"无法确认/无法消歧"。

---

## 文件结构(改动面)

```
citeguard/retrieval/scholarly_clients/base.py        # T2  +lookup_identifier 默认实现
citeguard/retrieval/scholarly_clients/arxiv.py       # T2  抽取严格 id 查询
citeguard/retrieval/scholarly_clients/crossref.py    # T2  抽取严格 DOI 查询
citeguard/retrieval/scholarly_clients/multi_source.py# T1 _rank 归一化;T6 并发+预算
citeguard/retrieval/scholarly_clients/factory.py     # T6  harvest 默认 False + budget 透传
citeguard/verification/resolve.py                    # T3  权威裁决 + T5 污染防御
citeguard/verification/verify.py                     # T4  id 失败降级 + arxiv_id diff + suggested 门禁
citeguard/verification/models.py                     # T4  VerificationResult.identifier_lookup
citeguard/runtime.py                                 # T6  CITEGUARD_SOURCE_BUDGET
data/eval/canary_golden.json                         # T7
scripts/canary_live.py                               # T7
.github/workflows/canary.yml                         # T7
docs/agent_output_contract.md, CHANGELOG.md          # T8
tests/test_rank_normalization.py                     # T1
tests/test_identifier_authority.py                   # T2+T3+T4
tests/test_polluted_record_defense.py                # T5
tests/test_multi_source_concurrency.py               # T6
```

执行顺序即任务号:T1(独立小修)→ T2 → T3 → T4 → T5 → T6 → T7 → T8。

---

## Task 1: 修复 `_rank` 的 source_score 归一化 bug(P0-3)

**Files:** Modify `citeguard/retrieval/scholarly_clients/multi_source.py`;Test `tests/test_rank_normalization.py`

- [ ] **Step 1: 失败测试**

```python
# tests/test_rank_normalization.py
"""_rank must not let a raw source relevance score dominate ranking."""

import unittest

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource


class RankNormalizationTests(unittest.TestCase):
    def test_huge_raw_relevance_does_not_beat_strong_title_match(self):
        strong_title = CitationRecord(
            citation_id="good", title="Attention Is All You Need",
            authors=["A"], year=2017, source="memory",
            metadata={"source_score": 5.0},
        )
        junk_high_score = CitationRecord(
            citation_id="junk", title="A Totally Different Survey of Networks",
            authors=["B"], year=2025, source="memory",
            metadata={"source_score": 15329.672},
        )
        multi = MultiSourceMetadataSource(
            [InMemoryMetadataSource([strong_title]), InMemoryMetadataSource([junk_high_score])]
        )
        ranked = multi._rank("Attention Is All You Need", [junk_high_score, strong_title])
        self.assertEqual(ranked[0].citation_id, "good")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**:`python3 -m unittest tests.test_rank_normalization -v` → FAIL(junk 排第一)
- [ ] **Step 3: 修复**——`multi_source.py` `_rank` 内将

```python
            source_score = float(record.metadata.get("source_score", 0.0))
```

改为(压缩到 0–1,单调有界):

```python
            raw_source_score = float(record.metadata.get("source_score", 0.0))
            source_score = raw_source_score / (raw_source_score + 50.0) if raw_source_score > 0 else 0.0
```

- [ ] **Step 4: 确认通过 + 全量**:目标测试 PASS;`python3 -m unittest discover -s tests` 全绿(若既有测试依赖旧排序,按新语义修测试并在提交信息说明)。
- [ ] **Step 5: 提交**:`git add ... && git commit -m "Normalize raw source relevance in multi-source ranking"`

---

## Task 2: 适配器严格标识符查询 `lookup_identifier`(P0-1 底座)

**Files:** Modify `base.py` / `arxiv.py` / `crossref.py`;Test `tests/test_identifier_authority.py`(新建,先放适配器级用例)

- [ ] **Step 1: 失败测试**

```python
# tests/test_identifier_authority.py
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
    """Returns queued payloads; records error state like HTTPClient does."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
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
            def all_records(self): return []
            def search(self, query, top_k=5): return []
            def lookup(self, candidate): return None
        self.assertIsNone(_Dummy().lookup_identifier(CitationRecord(citation_id="c", title="t")))

    def test_arxiv_identifier_hit_uses_id_list_only(self):
        http = _ScriptedHTTP([(ARXIV_ATOM_OK, "")])
        src = ArxivMetadataSource(http_client=http, harvest_evidence=False)
        record = src.lookup_identifier(CitationRecord(citation_id="c", title="", arxiv_id="1706.03762"))
        self.assertIsNotNone(record)
        self.assertEqual(record.year, 2017)
        self.assertEqual(len(http.calls), 1)
        self.assertIn("id_list", http.calls[0][1])

    def test_arxiv_identifier_failure_leaves_error_state(self):
        http = _ScriptedHTTP([("", "timeout")])
        src = ArxivMetadataSource(http_client=http, harvest_evidence=False)
        record = src.lookup_identifier(CitationRecord(citation_id="c", title="", arxiv_id="1706.03762"))
        self.assertIsNone(record)
        self.assertEqual(http.last_error_code, "timeout")  # 状态未被标题搜索洗白

    def test_arxiv_identifier_none_without_id(self):
        http = _ScriptedHTTP([])
        src = ArxivMetadataSource(http_client=http, harvest_evidence=False)
        self.assertIsNone(src.lookup_identifier(CitationRecord(citation_id="c", title="Some Title")))
        self.assertEqual(http.calls, [])

    def test_crossref_identifier_hit_by_doi(self):
        crossref_payload = (
            '{"message": {"DOI": "10.1000/xyz", "title": ["A Real Paper"],'
            ' "author": [{"given": "A", "family": "Author"}],'
            ' "issued": {"date-parts": [[2020]]}}}'
        )
        http = _ScriptedHTTP([(crossref_payload, "")])
        src = CrossrefMetadataSource(http_client=http, harvest_evidence=False)
        record = src.lookup_identifier(CitationRecord(citation_id="c", title="", doi="10.1000/xyz"))
        self.assertIsNotNone(record)
        self.assertEqual(len(http.calls), 1)


if __name__ == "__main__":
    unittest.main()
```

注:`_ScriptedHTTP` 若与 crossref 实际解析路径(`get_json` vs `get_text`)不匹配,以**读到的 crossref.py 实际实现**为准调整 Fake(不得改产品代码来适配 Fake)。

- [ ] **Step 2: 确认失败**(`AttributeError: lookup_identifier`)。
- [ ] **Step 3: 实现**
  - `base.py` 增加默认方法:

```python
    def lookup_identifier(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        """Resolve strictly by persistent identifier (DOI/arXiv id).

        Returns None when this source does not support the candidate's
        identifier or the identifier has no record. Implementations must NOT
        fall back to title search here.
        """
        return None
```

  - `arxiv.py`:把 `lookup` 的 id_list 分支抽成 `lookup_identifier`(仅 `candidate.arxiv_id` 时发一次 `id_list` 请求并 `_parse_entries`,命中 `_remember` 并返回,否则 None,**无标题回退**);`lookup` 改为先调 `self.lookup_identifier(candidate)`,命中即返回,其余逻辑不变。
  - `crossref.py`:同样把 DOI 直查分支抽成 `lookup_identifier`(仅 `candidate.doi` 时直查 works/{doi}),`lookup` 复用。
- [ ] **Step 4: 确认通过 + 全量绿。**
- [ ] **Step 5: 提交**:`git commit -m "Add strict identifier-only lookup to arXiv and Crossref adapters"`

---

## Task 3: resolve 层标识符权威裁决(P0-1 核心)

**Files:** Modify `citeguard/verification/resolve.py`;Test 追加到 `tests/test_identifier_authority.py`

- [ ] **Step 1: 追加失败测试**(用 Fake MetadataSource,模拟"arXiv 挂了 + OpenAlex 有同名污染记录"的实测场景)

```python
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource
from citeguard.verification.parse import parse_citation
from citeguard.verification.resolve import resolve_citation


AIAYN_TRUE = CitationRecord(
    citation_id="arxiv:aiayn", title="Attention Is All You Need",
    authors=["Ashish Vaswani"], year=2017, arxiv_id="1706.03762", source="arxiv",
)
AIAYN_JUNK = CitationRecord(
    citation_id="openalex:junk", title="Attention Is All You Need",
    authors=["Ashish Vaswani"], year=2025, doi="10.65215/2q58a426", source="openalex",
    metadata={"source_score": 15329.672, "cited_by_count": 6583},
)


class _NamedMemory(InMemoryMetadataSource):
    def __init__(self, records, name):
        super().__init__(records)
        self.name = name


class _FailingIdentifierSource(_NamedMemory):
    """lookup_identifier always fails like a timed-out arXiv."""

    def __init__(self, records, name):
        super().__init__(records, name)
        self.http_client = _ScriptedHTTP([])  # 队列耗尽 → ("", "timeout")

    def lookup_identifier(self, candidate):
        self.http_client.get_text("http://export.arxiv.org/api/query", params={"id_list": candidate.arxiv_id})
        return None


class _HitIdentifierSource(_NamedMemory):
    def __init__(self, records, name, hit):
        super().__init__(records, name)
        self.http_client = _ScriptedHTTP([("ok", "")])
        self._hit = hit

    def lookup_identifier(self, candidate):
        self.http_client.get_text("http://export.arxiv.org/api/query", params={"id_list": candidate.arxiv_id})
        return self._hit


class IdentifierAuthorityResolveTests(unittest.TestCase):
    def _candidate(self):
        return parse_citation(title="Attention Is All You Need", arxiv_id="1706.03762", year=2017)

    def test_identifier_hit_beats_polluted_title_match(self):
        arxiv = _HitIdentifierSource([], "arxiv", AIAYN_TRUE)
        openalex = _NamedMemory([AIAYN_JUNK], "openalex")
        outcome = resolve_citation(self._candidate(), MultiSourceMetadataSource([openalex, arxiv]))
        self.assertEqual(outcome.best.citation_id, "arxiv:aiayn")
        self.assertEqual(outcome.score, 1.0)
        self.assertEqual(outcome.identifier_lookup["status"], "hit")

    def test_identifier_failure_is_surfaced_not_silent(self):
        arxiv = _FailingIdentifierSource([], "arxiv")
        openalex = _NamedMemory([AIAYN_JUNK], "openalex")
        outcome = resolve_citation(self._candidate(), MultiSourceMetadataSource([openalex, arxiv]))
        self.assertEqual(outcome.identifier_lookup["status"], "failed")
        self.assertIn("arxiv", outcome.sources_failed)

    def test_identifier_unavailable_when_source_not_configured(self):
        openalex = _NamedMemory([AIAYN_JUNK], "openalex")
        outcome = resolve_citation(self._candidate(), MultiSourceMetadataSource([openalex]))
        self.assertEqual(outcome.identifier_lookup["status"], "unavailable")

    def test_identifier_miss_recorded(self):
        arxiv = _HitIdentifierSource([], "arxiv", None)  # 响应正常但查无此 id
        arxiv.http_client = _ScriptedHTTP([("<feed xmlns=\\"http://www.w3.org/2005/Atom\\"></feed>", "")])
        openalex = _NamedMemory([AIAYN_JUNK], "openalex")
        outcome = resolve_citation(self._candidate(), MultiSourceMetadataSource([openalex, arxiv]))
        self.assertEqual(outcome.identifier_lookup["status"], "miss")
```

- [ ] **Step 2: 确认失败**(`ResolveOutcome` 无 `identifier_lookup` / `AttributeError`)。
- [ ] **Step 3: 实现 `resolve.py`**
  1. `ResolveOutcome` 末尾追加字段(带默认,兼容两处位置构造——同时把这两处构造改为**关键字参数**以杜绝再犯):

```python
    identifier_lookup: Optional[Dict[str, Any]] = None
    ambiguity_reason: str = ""
```

  2. 新增:

```python
IDENTIFIER_AUTHORITY = {"arxiv_id": "arxiv", "doi": "crossref"}


def _child_sources(source: MetadataSource) -> List[MetadataSource]:
    inner = getattr(source, "inner", source)
    if isinstance(inner, MultiSourceMetadataSource):
        return list(inner.sources)
    return [inner]


def _identifier_authority(candidate: CitationRecord, source: MetadataSource):
    """Strictly resolve the caller-provided identifier at its home source.

    Returns (info_dict, record_or_None); info["status"] in
    {"hit", "miss", "failed", "unavailable"}. Never falls back to title search.
    """
    if candidate.arxiv_id:
        kind, value = "arxiv_id", normalize_arxiv_id(candidate.arxiv_id)
    elif candidate.doi:
        kind, value = "doi", normalize_doi(candidate.doi)
    else:
        return None
    authority = IDENTIFIER_AUTHORITY[kind]
    info: Dict[str, Any] = {"kind": kind, "value": value, "source": authority}
    child = next((item for item in _child_sources(source) if getattr(item, "name", "") == authority), None)
    if child is None:
        info["status"] = "unavailable"
        return info, None

    last_detail: Optional[Dict[str, Any]] = None
    for _attempt in range(2):  # 一次显式重试:权威路径值得多一次机会
        try:
            record = child.lookup_identifier(candidate)
        except Exception as exc:
            code, kind_ = _classify_source_exception(exc)
            last_detail = {"source": authority, "code": code, "kind": kind_,
                           "status_code": None, "url": "", "error": exc.__class__.__name__}
            continue
        http_client = getattr(child, "http_client", None)
        error_code = getattr(http_client, "last_error_code", "") if http_client is not None else ""
        if record is not None:
            info["status"] = "hit"
            return info, record
        if not error_code:
            info["status"] = "miss"
            return info, None
        last_detail = {
            "source": authority, "code": error_code,
            "kind": getattr(http_client, "last_error_kind", ""),
            "status_code": getattr(http_client, "last_status_code", None),
            "url": getattr(http_client, "last_url", ""),
            "error": getattr(http_client, "last_error", ""),
        }
    info["status"] = "failed"
    if last_detail is not None:
        info["failure_detail"] = last_detail
    return info, last_detail
```

  注意 failed 时返回 `(info, last_detail)` 里第二个元素**不是记录**——调用侧按 status 区分(见下),不要误当 record 用;为清晰可改为始终返回 `(info, record_or_None)` 并把 detail 放 `info["failure_detail"]`(**推荐后者**,实现时统一)。
  3. `resolve_citation` 开头接线(替换现有 `if candidate.doi or candidate.arxiv_id: lookup` 段):

```python
    identifier_info = None
    authority = _identifier_authority(candidate, source)
    if authority is not None:
        identifier_info, authority_record = authority
        if identifier_info.get("status") == "hit" and authority_record is not None:
            results.append(authority_record)
        elif identifier_info.get("status") == "failed":
            detail = identifier_info.get("failure_detail")
            if detail:
                failure_details.append(detail)
                failed.append(str(detail.get("source", "")))
        if identifier_info.get("status") != "hit" and (candidate.doi or candidate.arxiv_id):
            # 权威未命中时保留原多源 lookup 兜底(含 try/except 原逻辑)
            ...原 lookup 段...
    # 原 search 段照旧
```

  4. 尾部构造 `ResolveOutcome(..., identifier_lookup=identifier_info, ambiguity_reason=...)`(两处)。
- [ ] **Step 4: 目标测试 PASS + 全量绿**(既有 resolve 测试若因"识别符命中后跳过 lookup"而变化,按新语义更新)。
- [ ] **Step 5: 提交**:`git commit -m "Enforce identifier-authority resolution before title matching"`

---

## Task 4: verify 层降级与透出(P0-1 收口)

**Files:** Modify `verify.py`、`models.py`;Test 追加到 `tests/test_identifier_authority.py`

- [ ] **Step 1: 追加失败测试**

```python
from citeguard.verification.models import Verdict
from citeguard.verification.verify import verify_citation


class IdentifierAuthorityVerifyTests(unittest.TestCase):
    def _candidate(self):
        return parse_citation(title="Attention Is All You Need", arxiv_id="1706.03762", year=2017)

    def test_id_hit_verifies_despite_junk_record(self):
        arxiv = _HitIdentifierSource([], "arxiv", AIAYN_TRUE)
        openalex = _NamedMemory([AIAYN_JUNK], "openalex")
        result = verify_citation(self._candidate(), MultiSourceMetadataSource([openalex, arxiv]))
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.canonical_record.year, 2017)
        self.assertEqual(result.to_dict()["identifier_lookup"]["status"], "hit")

    def test_id_failure_never_yields_title_only_mismatch(self):
        arxiv = _FailingIdentifierSource([], "arxiv")
        openalex = _NamedMemory([AIAYN_JUNK], "openalex")
        result = verify_citation(self._candidate(), MultiSourceMetadataSource([openalex, arxiv]))
        self.assertEqual(result.verdict, Verdict.AMBIGUOUS)
        self.assertTrue(result.outage_limited)
        self.assertEqual(result.suggested_citation, "")
        self.assertIn("identifier", result.explanation.lower())

    def test_arxiv_id_field_diff_added(self):
        # id miss + 标题命中无 id 的记录 → arxiv_id 差异被列出
        arxiv = _HitIdentifierSource([], "arxiv", None)
        arxiv.http_client = _ScriptedHTTP([("<feed xmlns=\\"http://www.w3.org/2005/Atom\\"></feed>", "")])
        plain = CitationRecord(citation_id="x", title="Attention Is All You Need",
                               authors=["Ashish Vaswani"], year=2017, source="openalex")
        openalex = _NamedMemory([plain], "openalex")
        result = verify_citation(self._candidate(), MultiSourceMetadataSource([openalex, arxiv]))
        diff_fields = [d.field for d in result.field_diffs]
        self.assertIn("arxiv_id", diff_fields)
```

- [ ] **Step 2: 确认失败。**
- [ ] **Step 3: 实现**
  - `models.py` `VerificationResult`:追加 `identifier_lookup: Optional[Dict[str, Any]] = None`(字段区末尾),`to_dict()` 增加 `"identifier_lookup": dict(self.identifier_lookup) if self.identifier_lookup else None`。
  - `verify.py`:
    1. `_field_diffs` 增加(镜像 doi 分支):

```python
    if candidate.arxiv_id:
        matches = normalize_arxiv_id(candidate.arxiv_id) == normalize_arxiv_id(canonical.arxiv_id)
        diffs.append(FieldDiff("arxiv_id", candidate.arxiv_id, canonical.arxiv_id, matches))
```

       (导入 `normalize_arxiv_id`。)
    2. `verify_citation` 中取 `identifier_info = outcome.identifier_lookup or {}`;`id_failed = identifier_info.get("status") == "failed"`;在 **ambiguous 分支之前**插入:

```python
    if id_failed and outcome.score < 1.0:
        return VerificationResult(
            verdict=Verdict.AMBIGUOUS,
            confidence=min(_confidence_with_source_failures(outcome.score, failure_mode), 0.6),
            input_citation=candidate,
            canonical_record=outcome.best,
            field_diffs=[],
            suggested_citation="",
            explanation=(
                f"The authoritative {identifier_info.get('kind', 'identifier')} lookup failed on "
                f"{identifier_info.get('source', 'its home source')}; a title-based match exists but cannot "
                "be confirmed against the provided identifier. Retry or check source health — this is not "
                "evidence of fabrication."
            ),
            sources_checked=checked, sources_responded=responded, sources_failed=failed,
            source_failure_details=failure_details, source_failure_mode=failure_mode,
            outage_limited=True, alternatives=outcome.alternatives,
            identifier_lookup=outcome.identifier_lookup,
        )
```

    3. 其余四个分支的 `VerificationResult(...)` 全部补传 `identifier_lookup=outcome.identifier_lookup`。
    4. id miss 时在 explanation 末尾追加一句:`" Note: the provided {kind} was not found at {source}."`(仅 miss 且有标题结果时)。
- [ ] **Step 4: 目标 PASS + 全量绿**——重点排查 MCP/CLI 契约测试对 `to_dict` 键的断言,连同 `docs/agent_output_contract.md` 一起补 `identifier_lookup` 字段说明(结构:`kind/value/source/status[/failure_detail]`)。
- [ ] **Step 5: 提交**:`git commit -m "Downgrade to ambiguous when identifier authority fails and expose identifier_lookup"`

---

## Task 5: 污染记录防御(P0-2)

**Files:** Modify `resolve.py`(可疑启发 + 年份共识)、`verify.py`(ambiguous 解释 + suggested 门禁);Test `tests/test_polluted_record_defense.py`

- [ ] **Step 1: 失败测试**

```python
# tests/test_polluted_record_defense.py
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
        rec = CitationRecord(citation_id="x", title="T", year=2026, source="s",
                             metadata={"cited_by_count": 5000})
        self.assertTrue(is_suspect_record(rec, now_year=2026))

    def test_normal_record_not_suspect(self):
        self.assertFalse(is_suspect_record(TRUE_2017, now_year=2026))


class YearConflictTests(unittest.TestCase):
    def test_cross_source_year_conflict_degrades_to_ambiguous(self):
        source = MultiSourceMetadataSource([_Named([TRUE_2017], "crossref"), _Named([JUNK_2025], "openalex")])
        candidate = parse_citation(title="Attention Is All You Need", year=2017)  # 无标识符
        outcome = resolve_citation(candidate, source)
        self.assertTrue(outcome.ambiguous)
        self.assertEqual(outcome.ambiguity_reason, "year_conflict")
        result = verify_citation(candidate, source)
        self.assertEqual(result.verdict, Verdict.AMBIGUOUS)
        self.assertEqual(result.suggested_citation, "")

    def test_suspect_only_best_degrades_to_ambiguous(self):
        source = MultiSourceMetadataSource([_Named([JUNK_2025], "openalex")])
        candidate = parse_citation(title="Attention Is All You Need", year=2017)
        result = verify_citation(candidate, source)
        self.assertNotEqual(result.verdict, Verdict.METADATA_MISMATCH)
        self.assertEqual(result.suggested_citation, "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 确认失败。**
- [ ] **Step 3: 实现 `resolve.py`**

```python
import os
from datetime import date

DEFAULT_SUSPECT_DOI_PREFIXES = ("10.65215",)


def _suspect_doi_prefixes() -> tuple:
    extra = os.environ.get("CITEGUARD_SUSPECT_DOI_PREFIXES", "")
    return DEFAULT_SUSPECT_DOI_PREFIXES + tuple(p.strip() for p in extra.split(",") if p.strip())


def is_suspect_record(record: CitationRecord, now_year: Optional[int] = None) -> bool:
    """Heuristic: hijacked/mirror records. Only ever downgrades to ambiguous, never accuses."""

    doi = normalize_doi(record.doi)
    if doi and any(doi.startswith(prefix) for prefix in _suspect_doi_prefixes()):
        return True
    cited = int(record.metadata.get("cited_by_count") or 0)
    year = record.year
    current = now_year if now_year is not None else date.today().year
    return bool(cited >= 1000 and year is not None and year >= current - 1)
```

在 `resolve_citation` 打分排序处:
  - 排序键加入非可疑优先:`scored.sort(key=lambda item: (item[0], 0 if is_suspect_record(item[1]) else 1), reverse=True)`
  - 计算 `identifier_hit = bool(identifier_info and identifier_info.get("status") == "hit")`
  - 追加降级逻辑(在现有 ambiguous 判定之后):

```python
    ambiguity_reason = "near_duplicate" if ambiguous else ""
    if not identifier_hit:
        strong = [record for score, record in scored if score >= STRONG_MATCH]
        years = {record.year for record in strong if record.year is not None}
        if len(years) >= 2 and (max(years) - min(years) > 1):
            ambiguous, ambiguity_reason = True, "year_conflict"
        elif is_suspect_record(best):
            ambiguous, ambiguity_reason = True, ambiguity_reason or "suspect_record"
```

  - `ResolveOutcome(..., ambiguity_reason=ambiguity_reason)`。
- [ ] **Step 3b: `verify.py` ambiguous 分支**:解释按 reason 细化——`year_conflict` → "Matching records disagree on the publication year across sources (likely a reprint or mirror record); provide a DOI/arXiv id to disambiguate.";`suspect_record` → "The best match shows signs of a hijacked or mirror record; provide a DOI/arXiv id."(默认保留原句)。mismatch 分支 suggested 门禁:`if identifier_hit or not is_suspect_record(outcome.best)` 才产出(导入 `is_suspect_record`;identifier_hit 从 `identifier_info.get("status")=="hit"` 取)。
- [ ] **Step 4: 目标 PASS + 全量绿**(留意既有"same-title 双胞胎 → ambiguous"测试仍过;`ambiguity_reason` 也补进 `to_dict`?——**不加**,M1 保持 ResolveOutcome 内部使用,解释文本已足够)。
- [ ] **Step 5: 提交**:`git commit -m "Degrade polluted or year-conflicted matches to ambiguous"`

---

## Task 6: 多源并发 + 时间预算 + 默认值统一(P0-4)

**Files:** Modify `multi_source.py`、`factory.py`、`runtime.py`;Test `tests/test_multi_source_concurrency.py`

- [ ] **Step 1: 失败测试**

```python
# tests/test_multi_source_concurrency.py
"""Multi-source fan-out must be concurrent and budget-bounded."""

import time
import unittest

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource


class _SlowSource(InMemoryMetadataSource):
    def __init__(self, records, name, delay):
        super().__init__(records)
        self.name = name
        self.delay = delay

    def search(self, query, top_k=5):
        time.sleep(self.delay)
        return super().search(query, top_k=top_k)

    def lookup(self, candidate):
        time.sleep(self.delay)
        return super().lookup(candidate)


REC_A = CitationRecord(citation_id="a", title="Parallel Fan Out Paper", year=2024, source="s1")
REC_B = CitationRecord(citation_id="b", title="Parallel Fan Out Paper Two", year=2024, source="s2")


class ConcurrencyTests(unittest.TestCase):
    def test_search_runs_sources_in_parallel(self):
        multi = MultiSourceMetadataSource(
            [_SlowSource([REC_A], "s1", 0.4), _SlowSource([REC_B], "s2", 0.4)]
        )
        start = time.perf_counter()
        results = multi.search("parallel fan out paper", top_k=5)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.7)          # 串行应为 ~0.8s
        self.assertEqual(len(results), 2)

    def test_budget_records_timeout_and_returns_fast_source(self):
        multi = MultiSourceMetadataSource(
            [_SlowSource([REC_A], "fast", 0.05), _SlowSource([REC_B], "slow", 1.5)],
            budget_seconds=0.3,
        )
        results = multi.search("parallel fan out paper", top_k=5)
        self.assertTrue(any(r.citation_id == "a" for r in results))
        self.assertIn("slow", multi.last_failures)
        codes = {d.get("code") for d in multi.last_failure_details}
        self.assertIn("budget_exceeded", codes)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 确认失败。**
- [ ] **Step 3: 实现 `multi_source.py`**
  - 构造器:`def __init__(self, sources, budget_seconds: float = 8.0)`,存 `self.budget_seconds`。
  - 新增私有扇出(注意:**不要用 `with ThreadPoolExecutor`**——其 `__exit__` 会等待超时线程,预算失效):

```python
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait


    def _fan_out(self, call):
        """Run `call(source)` across sources concurrently within budget.

        Returns {source_name: value}; failure details are appended to
        self.last_failures / self.last_failure_details (main thread only).
        """
        self.last_failures = []
        self.last_failure_details = []
        pool = ThreadPoolExecutor(max_workers=max(1, len(self.sources)))
        futures: Dict[Future, MetadataSource] = {}
        try:
            for source in self.sources:
                futures[pool.submit(self._probe, source, call)] = source
            done, not_done = wait(futures, timeout=self.budget_seconds)
            values: Dict[str, Any] = {}
            for future in done:
                name, value, detail = future.result()
                if detail is not None:
                    self._append_failure_detail(detail)
                values[name] = value
            for future in not_done:
                source = futures[future]
                self._append_failure_detail({
                    "source": source.name, "code": "budget_exceeded", "kind": "timeout",
                    "status_code": None, "url": "",
                    "error": f"source exceeded fan-out budget of {self.budget_seconds}s",
                })
            return values
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _probe(source, call):
        try:
            value = call(source)
        except Exception as exc:  # 与原串行逻辑同粒度
            return source.name, None, _source_failure_detail(source, exc)
        detail = _source_failure_detail(source)
        empty = value is None or value == []
        return source.name, value, (detail if (empty and detail.get("code")) else None)
```

  - `search` 重写为:`values = self._fan_out(lambda s: s.search(query, top_k=per_source))`,聚合非空列表 → `merge_record_list` → `_rank` → 截断(保持原返回语义与失败记录语义)。`lookup` 同法:聚合非 None matches → 原排序阈值逻辑。删除旧串行循环。
  - 线程安全说明(写进 docstring):每 source 独占一个工作线程,其 `http_client` 状态只被该线程读写;失败细节在**主线程**统一 append,无共享可变竞争。超预算线程会在后台自然结束(进程常驻的 MCP server 无碍;CLI 最多多等一个 HTTP 超时)。
- [ ] **Step 3b: `factory.py`**:`harvest_remote_evidence: bool = True` → `False`;新增参数 `source_budget: float = 8.0`,末尾 `MultiSourceMetadataSource(sources, budget_seconds=source_budget)`。
- [ ] **Step 3c: `runtime.py`**:新增

```python
def source_budget(env: Optional[Mapping[str, str]] = None) -> float:
    active = env if env is not None else os.environ
    try:
        return max(1.0, float(active.get("CITEGUARD_SOURCE_BUDGET", "8.0")))
    except ValueError:
        return 8.0
```

  并在 `:687` 的 `build_live_metadata_source(...)` 调用中加 `source_budget=source_budget(active_env)`(照现有参数风格)。
- [ ] **Step 4: 目标 PASS + 全量绿**;`CHANGELOG.md` 记录行为变更:"library default for landing-page evidence harvesting flipped to off (opt-in), aligning with the MCP runtime"。
- [ ] **Step 5: 提交**:`git commit -m "Fan out multi-source queries concurrently within a time budget"`

---

## Task 7: 金标 canary(P0-5)

**Files:** Create `data/eval/canary_golden.json`、`scripts/canary_live.py`、`.github/workflows/canary.yml`;Test `tests/test_canary_golden.py`(仅校验数据与断言逻辑,不联网)

- [ ] **Step 1: 金标数据**(注意期望写成**约束**而非精确值,容忍源漂移;`must_not` 是硬线)

```json
{
  "cases": [
    {"id": "g01", "fields": {"title": "Attention Is All You Need", "arxiv_id": "1706.03762", "year": 2017},
     "expect": {"verdict_in": ["verified"], "canonical_year": 2017}},
    {"id": "g02", "fields": {"title": "Attention Is All You Need", "authors": ["Ashish Vaswani"], "year": 2017},
     "expect": {"must_not": ["metadata_mismatch"]}},
    {"id": "g03", "fields": {"title": "OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented LMs", "arxiv_id": "2411.14199"},
     "expect": {"verdict_in": ["verified", "metadata_mismatch"], "canonical_year_in": [2024, 2025]}},
    {"id": "g04", "fields": {"title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks"},
     "expect": {"verdict_in": ["not_found"]}},
    {"id": "g05", "fields": {"title": "A Unified Theory of Phantom References That Was Never Written"},
     "expect": {"verdict_in": ["not_found"]}},
    {"id": "g06", "fields": {"title": "迈向第三代人工智能", "doi": "10.1360/SSI-2020-0204"},
     "expect": {"verdict_in": ["not_found", "verified", "metadata_mismatch"], "doi_registered": true}},
    {"id": "g07", "fields": {"doi": "10.48550/arXiv.2504.08066"},
     "expect": {"verdict_in": ["verified", "metadata_mismatch", "ambiguous"]}},
    {"id": "g08", "fields": {"title": "GhostCite: A Large-Scale Analysis of Citation Validity in the Age of Large Language Models", "year": 2026},
     "expect": {"must_not": ["metadata_mismatch"]}}
  ]
}
```

  (实现者按当前线上真实行为微调 g03/g07 的宽容集——先跑一遍再定,**g01/g02/g04/g05 的硬线不得放宽**。)
- [ ] **Step 2: 校验测试(离线)**:`tests/test_canary_golden.py` 校验 JSON 可加载、每条含 `id/fields/expect`、`expect` 只用受支持的键(`verdict_in/must_not/canonical_year/canonical_year_in/doi_registered`),并对 `scripts/canary_live.py` 的 `evaluate_case(result_dict, expect)` 纯函数做单测(构造假 result dict 断言通过/失败判定正确)。
- [ ] **Step 3: 实现 `scripts/canary_live.py`**:`_bootstrap` 模式;加载金标 → `build_live_metadata_source(["openalex","crossref","arxiv"], mailto=env)` + `verify_citation`(DOI 注册表按现有 CLI 的接线方式传入)→ `evaluate_case` 逐条断言 → 输出 JSON 报告(逐条 pass/fail + 实际 verdict)与 `--report-md` Markdown 摘要 → 任一 fail 退出码 1。**注意**:`outage_limited=true` 的结果按 "skip(源故障)" 计,不算 fail——canary 盯的是判定漂移,不是源可用性。
- [ ] **Step 4: workflow `.github/workflows/canary.yml`**:`schedule: cron "17 19 * * *"` + `workflow_dispatch`;install `-e .`;跑脚本(带 `CITEGUARD_MAILTO` 用 secrets 或默认);失败步骤:`gh issue create --title "Canary drift $(date +%F)" --body-file canary_report.md`(`GH_TOKEN: ${{ github.token }}`,加 `permissions: issues: write`)。
- [ ] **Step 5: 本地实跑一遍 live 脚本确认全绿**(允许 g03/g07 按实况调宽容集,记录在提交信息),全量单测绿。
- [ ] **Step 6: 提交**:`git commit -m "Add golden-case live canary with nightly drift alerting"`

---

## Task 8: 契约文档 / CHANGELOG / 收口

**Files:** Modify `docs/agent_output_contract.md`、`CHANGELOG.md`、`README.md`(如提及默认行为处)

- [ ] `agent_output_contract.md`:新增 `identifier_lookup` 字段说明(结构、四种 status 语义、agent 应如何呈现:failed → 建议重试而非改引用);ambiguous 新解释语料入表。
- [ ] `CHANGELOG.md`(0.1.2-dev 段):identifier authority;polluted-record defense;并发 + `CITEGUARD_SOURCE_BUDGET`;库路径 evidence 默认改 off(**breaking-ish**,注明);`_rank` 修复;canary。
- [ ] README 中文/英文两份中关于"证据抓取默认"的表述核对一致。
- [ ] 全量:`python3 -m unittest discover -s tests`、`python3 scripts/eval_verification.py`、`ruff check .`、`mypy citeguard/`(增量白名单不变)。
- [ ] 提交:`git commit -m "Document identifier authority and M1 behavior changes"`

---

## 收尾验证(合并前)

- [ ] 全量测试绿(含新增 4 个测试文件)。
- [ ] **线上复现案例回归**:`python3 - <<'PY' ...` 实跑 AIAYN(id + 2017,multi 三源)→ 必须 `verified`/`outage_limited-ambiguous`,**绝不** `metadata_mismatch`;记录耗时,应显著低于 106.6s 基线(目标:id 路径 ≤ 8s 冷)。
- [ ] `scripts/canary_live.py` 本地全绿。
- [ ] `scripts/eval_verification.py` 指标不退化(`false_accusation_rate=0`)。

## 自检对照(计划 vs 企划书 §3)

- P0-1 → T2(适配器)+ T3(resolve)+ T4(verify/models)✅ 含"hit 必胜 / failed 禁 mismatch / miss 记录"三条语义
- P0-2 → T5(年份共识、可疑启发、suggested 门禁、排序 tiebreak)✅
- P0-3 → T1 ✅
- P0-4 → T6(并发、预算、factory 默认、runtime env、CHANGELOG)✅
- P0-5 → T7(金标 + live 脚本 + 夜间 workflow + 漂移开 issue)✅
- 红线:全部降级措辞为"无法确认",无"伪造"断言 ✅
