# CiteGuard

[![CI](https://github.com/xiaweiyi713/citeguard/actions/workflows/ci.yml/badge.svg)](https://github.com/xiaweiyi713/citeguard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

**A falsification-first toolkit that checks citations — does the cited paper exist, is its metadata correct, and does it actually support the sentence? — against live scholarly sources, callable from Claude Code, Codex, Cursor, and any other MCP client.**

LLM writing assistants hallucinate references: they invent papers, stitch together wrong metadata, and cite real papers that don't support the claim. CiteGuard is the skeptical reviewer that catches this — the check an agent can't reliably do on its own. It treats every citation as a `claim → citation → evidence` problem and tries to *disprove* it; when it can't be sure, it says so instead of guessing.

> **Status:** Alpha (`v0.1.0`). The verification toolkit below is the actively developed core. An earlier end-to-end "writing agent" prototype also lives in the repo (see [Project layout](#project-layout)) but is no longer the focus.

---

## See it work

![CiteGuard verifying two citations against OpenAlex and arXiv](docs/assets/demo_verify.svg)

Run it yourself (hits live OpenAlex + arXiv):

```bash
python3 scripts/demo_verify.py
```

```text
Verifying 2 citations against OpenAlex + arXiv ...

[OK] VERIFIED           (confidence 0.7)
    Vaswani et al., "Attention Is All You Need", arXiv:1706.03762
    sources checked: openalex, arxiv
    Citation resolves to a real record and the provided metadata matches.

[X] NOT_FOUND          (confidence 0.8419)
    (LLM-fabricated) "Quantum Teleportation of Citation Hallucinations in Alpacas"
    sources checked: openalex, arxiv
    Could not be verified in openalex, arxiv.
```

> Output is captured live, so exact confidence and matched-record details can drift with source data.

---

## What it does

CiteGuard answers two questions, against **OpenAlex, Crossref, arXiv, and Semantic Scholar**.

### 1. Does the paper exist, and is the metadata right?

`verify_citation` / `audit_citations` resolve a citation (identifier-first, else title) and compare each field you provided:

| verdict | meaning |
|---|---|
| `verified` | the paper exists and the provided metadata matches |
| `metadata_mismatch` | the paper exists but a field disagrees — comes with a **suggested corrected citation** |
| `not_found` | could not be verified in the queried sources (flagged high-risk, **not** declared fake) |
| `ambiguous` | several plausible matches — asks for a DOI/arXiv id to disambiguate |

### 2. Does the paper support the claim? (deep mode)

`check_claim_support` resolves the paper, then judges its abstract against your claim sentence using a reranker + NLI ensemble:

| verdict | meaning |
|---|---|
| `supported` | the abstract entails the claim |
| `weakly_supported` | partial / related evidence, but not strong enough |
| `insufficient_evidence` | the abstract does not address the claim — **abstain**, not "unsupported" |
| `contradicted` | the abstract actively contradicts the claim |

Two guardrails keep it honest: a source being **unreachable is never escalated to "fabricated"** (it lowers confidence, and the output lists which sources were checked), and `insufficient_evidence` / `not_found` are phrased as "could not confirm", leaving the final judgment to a human or the host agent.

---

## Quick start

The **core library has zero third-party dependencies** and runs on Python ≥ 3.9.

```bash
python -m pip install -e .            # core library
python -m pip install -e ".[mcp]"     # + MCP server (requires Python >= 3.10)
python -m pip install -e ".[models]"  # + reranker/NLI stack for support deep mode (heavy)
python -m pip install -e ".[api]"     # + FastAPI surface
```

### As an agent tool (MCP) — the primary path

```bash
python -m pip install -e ".[mcp]"
citeguard-mcp          # stdio transport
```

Register it in any MCP-compatible client (Claude Code example):

```json
{
  "mcpServers": {
    "citeguard": { "command": "citeguard-mcp" }
  }
}
```

For Claude Code specifically, [`skills/citeguard-verify/SKILL.md`](skills/citeguard-verify/SKILL.md) makes it **proactively** verify citations while you write (and present results without silently editing your text) — copy it into your project's `.claude/skills/`.

### As a Python library

```python
from src.retrieval.scholarly_clients import build_live_metadata_source
from src.verification import parse_citation, verify_citation, check_claim_support

source = build_live_metadata_source(["openalex", "arxiv"], mailto="you@example.com")

# Existence + metadata
result = verify_citation(parse_citation(title="Attention Is All You Need", arxiv_id="1706.03762"), source)
print(result.verdict.value, result.confidence)          # -> verified 0.7

# Claim support (deep mode needs the [models] extra; otherwise falls back to a labelled heuristic)
support = check_claim_support("The Transformer relies entirely on attention.",
                              parse_citation(title="Attention Is All You Need", arxiv_id="1706.03762"),
                              source)
print(support.verdict.value, support.engine)
```

---

## MCP tools

| tool | what it does |
|---|---|
| `verify_citation_tool` | verify one citation; returns verdict, canonical record, per-field diffs, suggested fix, sources checked |
| `audit_citations_tool` | verify a list of citations; returns a per-item report plus a verdict-count summary |
| `check_claim_support_tool` | judge whether a cited paper supports a claim sentence (deep mode) |

Configuration via environment variables:

| variable | default | purpose |
|---|---|---|
| `CITEGUARD_SOURCES` | `openalex,crossref,arxiv` | which sources to query |
| `CITEGUARD_MAILTO` | `research@example.com` | polite-pool contact for OpenAlex/Crossref |
| `SEMANTIC_SCHOLAR_API_KEY` | — | optional, improves Semantic Scholar access |
| `CITEGUARD_CACHE` | `data/logs/verification_cache.sqlite` | local SQLite resolution cache |
| `CITEGUARD_RERANKER_MODEL` | English cross-encoder | support reranker model — set a multilingual one for non-English claims |
| `CITEGUARD_NLI_MODEL` | English NLI | support NLI model — set a multilingual one for non-English claims |

Support deep mode downloads model weights on first use; pre-download with `python3 scripts/warmup_support_models.py`. Without the models installed, support runs a labelled `heuristic` engine (which never emits `supported` or `contradicted`).

---

## Chinese support

Text matching is CJK-aware (Chinese characters are preserved and tokenized into character bigrams, with **no extra dependencies**), so Chinese titles and claims can be verified against the many Chinese papers already indexed in OpenAlex/Crossref. For judging Chinese claim support, point `CITEGUARD_RERANKER_MODEL` / `CITEGUARD_NLI_MODEL` at multilingual models.

CNKI (知网) and Wanfang (万方) are **not** integrated: they have no open/free API and we do not scrape gated content. A ChinaXiv feasibility spike concluded NO-GO (its OAI endpoint is access-gated) — see [`docs/chinaxiv_spike.md`](docs/chinaxiv_spike.md); the pluggable source interface remains so an adapter can be added if an open endpoint appears.

---

## How resolution works

1. **Parse** the input; extract a DOI / arXiv id / year from free text when present.
2. **Identifier-first:** a DOI or arXiv id resolves the paper definitively.
3. **Otherwise search** by title across the selected sources and score candidates with a title-dominant match.
4. **Compare** only the fields you actually provided, field by field.
5. **Decide** the verdict (existence/metadata, or support over abstract-level evidence).

---

## Status, scope & known limitations

**In scope today:** existence + metadata verification, abstract-level claim-support verification, multi-source adapters, SQLite caching, an MCP server, a Claude Code skill, and offline evals.

**Known limitations**

- **Identifiers are the reliable path.** With a DOI or arXiv id, resolution is definitive — provide one when you can.
- **Title-only matching is best-effort.** A title can map to several records (e.g. an original paper plus a later reprint with a different `publication_year`); without an identifier a correct citation can surface a same-title record and be reported as a `metadata_mismatch` on `year`/`venue`. Treat title-only year/venue mismatches as "needs confirmation".
- **Support is abstract-level.** It judges the abstract (and any harvested snippets), not full text; abstain (`insufficient_evidence`) is common and intentional.

**Not yet done:** full-text support, multi-paper support for one claim, active counter-evidence retrieval, a large human-reviewed benchmark. See [ROADMAP.md](ROADMAP.md).

---

## Tests & reproducibility

```bash
python3 -m unittest discover -s tests -v   # full unit suite (63 tests; standard library only)
python3 scripts/eval_verification.py       # offline, deterministic existence/metadata eval
python3 scripts/eval_support.py            # claim-support eval (needs the [models] extra)
```

The unit suite and the verification eval are network-free and run in CI. Eval datasets live in [`data/eval/`](data/eval/).

---

## Project layout

```text
src/
  verification/   # the core: parse, resolve, verify, audit, cache, claim-support, evals
  mcp_server/     # FastMCP server exposing the three tools
  retrieval/      # scholarly source adapters (OpenAlex/Crossref/arXiv/Semantic Scholar) + retrievers
  verifiers/      # existence/metadata + the reranker+NLI support ensemble
  citation/ graph/ audit/                 # shared models and helpers
  orchestrator/ planner/ writer/ benchmark/ api/   # earlier "writing agent" prototype (legacy)
skills/citeguard-verify/   # Claude Code skill
scripts/                   # demo + eval + corpus/model utilities
data/eval/                 # offline benchmarks
docs/                      # design specs, plans, architecture, spike notes
tests/                     # unittest suite
```

---

## Documents

- Design specs & implementation plans: [`docs/superpowers/`](docs/superpowers/)
- Architecture: [`docs/architecture.md`](docs/architecture.md) · Roadmap: [`ROADMAP.md`](ROADMAP.md) · ChinaXiv spike: [`docs/chinaxiv_spike.md`](docs/chinaxiv_spike.md)
- Research framing / proposal: [`docs/proposal.md`](docs/proposal.md)

## Citation

If you use this repository in research, please cite the software record in [`CITATION.cff`](CITATION.cff).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Released under the [MIT License](LICENSE).

---

## 中文说明

**CiteGuard 是一个"证伪优先"的引用核验工具**:在你或 AI 写完综述、参考文献后,它去 **OpenAlex / Crossref / arXiv / Semantic Scholar** 等真实学术库里核对三件事——这篇论文**存不存在**、**元数据(标题/作者/年份/venue/DOI)对不对**、以及**到底支不支持你这句话**。可作为 **MCP 工具**被 Claude Code、Codex、Cursor 等主流 agent 直接调用。

- **存在性 / 元数据**:返回 `verified` / `metadata_mismatch`(附改正建议) / `not_found` / `ambiguous`。
- **支撑性(深度模式)**:返回 `supported` / `weakly_supported` / `insufficient_evidence`(弃权,不等于"不支持") / `contradicted`,复用 reranker + NLI 集成。
- **核心原则**:宁可说"查不准",也不乱指控;源不可达只降置信度,绝不升级成"伪造"。
- **中文**:文本匹配已支持中文(CJK 分词,零依赖);判定中文支撑性时用环境变量配置多语模型。知网/万方无开放 API,不直连、不爬取受限内容。

最快上手:`python -m pip install -e ".[mcp]"`(需 Python ≥ 3.10)后运行 `citeguard-mcp`,在 MCP 客户端里配置 `"command": "citeguard-mcp"`;或直接 `python3 scripts/demo_verify.py` 看实时效果。核心库与测试在 Python ≥ 3.9 下零依赖运行。
