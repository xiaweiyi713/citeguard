# CiteGuard

[![CI](https://github.com/xiaweiyi713/citeguard/actions/workflows/ci.yml/badge.svg)](https://github.com/xiaweiyi713/citeguard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)
[![PyPI](https://img.shields.io/pypi/v/citationguard.svg)](https://pypi.org/project/citationguard/)

[中文(默认)](README.md) · English

**A skeptical citation auditor for agent writing workflows that checks citations — does the cited paper exist, is its metadata correct, and does it actually support the sentence? — against live scholarly sources, callable from Claude Code, Codex, Cursor, and any other MCP client.**

LLM writing assistants hallucinate references: they invent papers, stitch together wrong metadata, and cite real papers that don't support the claim. CiteGuard is the skeptical reviewer that catches this — the check an agent can't reliably do on its own. It treats every citation as a `claim → citation → evidence` problem and tries to *disprove* it; when it can't be sure, it says so instead of guessing.

> **Status:** Alpha (`v0.1.0`). The actively developed product surface is the `citeguard.*` auditor package, CLI, MCP server, batch workflows, cache replay, and release gates. Historical writing-agent experiments remain in source checkouts for context, but they are not part of the published package surface.

---

## See it work

![CiteGuard verifying two citations against OpenAlex and arXiv](docs/assets/demo_verify.svg)

From a source checkout, run the demo script yourself (hits live OpenAlex + arXiv):

```bash
python3 scripts/demo_verify.py
```

Installed-package users should use the stable `citeguard` CLI and
`citeguard-mcp` entry points shown in the quick start.

```text
Verifying 2 citations against OpenAlex + arXiv ...

[OK] VERIFIED           (confidence 0.7)
    Vaswani et al., "Attention Is All You Need", arXiv:1706.03762
    sources checked: openalex, arxiv
    Citation resolves to a real record and the provided metadata matches.

[X] NOT_FOUND          (confidence 0.8419)
    (LLM-fabricated) "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks"
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

Support results carry a machine-readable `evidence_scope` so agents never present
abstract-level evidence as a full-text conclusion. Full-text support is opt-in via
caller-provided lawful excerpts or local text/PDF files (`pip install "citationguard[pdf]"`
for PDF extraction); CiteGuard does not scrape gated sources, download remote full
text, or bypass paywalls.

Two guardrails keep it honest: a source being **unreachable is never escalated to "fabricated"** (it lowers confidence, sets `outage_limited=true` for outage-limited `not_found` results, and reports `sources_available`, `sources_failed`, and `source_failure_mode`), and `insufficient_evidence` / `not_found` are phrased as "could not confirm", leaving the final judgment to a human or the host agent.

---

## Quick start

The **core library has zero third-party dependencies** and runs on Python ≥ 3.9.

> ℹ️ **Package naming:** this project publishes on PyPI as **[`citationguard`](https://pypi.org/project/citationguard/)** — install with `pip install citationguard`, then `import citeguard` as usual (the `citeguard` / `citeguard-mcp` console commands are unchanged). The `citeguard` package on PyPI is an unrelated project by another organization.

For an installed or published package:

```bash
python -m pip install citationguard
python -m pip install "citationguard[mcp]"     # + MCP server (requires Python >= 3.10)
python -m pip install "citationguard[models]"  # + reranker/NLI stack for support deep mode (heavy)
python -m pip install "citationguard[api]"     # + FastAPI surface
```

From a local source checkout: `python -m pip install -e .` (plus the same extras).

Check your local configuration, then verify citations from the shell:

```bash
citeguard status                          # local readiness; add --check-sources for a live probe

citeguard verify \
  --title "Attention Is All You Need" \
  --author "Ashish Vaswani" \
  --year 2017 \
  --arxiv-id 1706.03762

citeguard audit examples/citations.json                  # batch: JSON array or .jsonl
citeguard audit examples/references.md --high-risk-only  # extract + audit a bibliography file

citeguard support \
  --claim "The Transformer relies entirely on attention." \
  --title "Attention Is All You Need" \
  --arxiv-id 1706.03762

citeguard support-audit examples/claim_citations.json    # batch claim/citation pairs
citeguard support-audit examples/claim_citations.jsonl --high-risk-only
citeguard support-set examples/citations.json \
  --claim "Citation auditing should verify existence, metadata, and claim support."

citeguard extract examples/references.md                 # pull citation candidates from a manuscript
citeguard counterevidence --claim "The Transformer relies entirely on attention."
```

Extraction reads Markdown/plain-text reference sections, LaTeX `\bibitem`, BibTeX,
compiled `.bbl`, LaTeX `\bibliography{refs}` / `\addbibresource{refs.bib}` links
(including `\input{...}` / `\include{...}` subfiles), and `.docx` — standard
library only. Extracted rows keep `source_path` / `source_locator` / line-range
provenance so audits can point back to the original bibliography item.

Every command prints JSON with stable `next_action` enums, risk rankings, and
machine-readable error payloads. The full CLI surface (including `cache`
inspect/export/clear and offline fixture replay) is in
[docs/cli_reference.md](docs/cli_reference.md); the complete agent-facing field
contract is in [docs/agent_output_contract.md](docs/agent_output_contract.md).

### As an agent tool (MCP) — the primary path

For an installed or published package:

```bash
python -m pip install "citationguard[mcp]"   # requires Python >= 3.10
citeguard-mcp                            # stdio transport
```

For a local source checkout:

```bash
python -m pip install -e ".[mcp]"
citeguard-mcp
```

Register it in any MCP-compatible client (Claude Code example):

```json
{
  "mcpServers": {
    "citeguard": { "command": "citeguard-mcp" }
  }
}
```

| tool | what it does |
|---|---|
| `citeguard_status_tool` | inspect MCP/Python readiness, cache readiness, source selection, and model dependency status without live queries |
| `verify_citation_tool` | verify one citation; returns verdict, canonical record, per-field diffs, suggested fix, sources checked |
| `audit_citations_tool` | verify a list of citations; returns a per-item report plus a verdict-count summary |
| `check_claim_support_tool` | judge whether a cited paper supports a claim sentence (deep mode) |
| `check_claim_support_set_tool` | judge whether one claim is supported by a set of cited papers |
| `search_counterevidence_tool` | search for possible counter-evidence candidates; review leads only, not a contradiction verdict |
| `audit_claim_support_tool` | judge a list of claim/citation pairs and summarize support verdicts |

After connecting, call `citeguard_status_tool` once — it reports source health,
cache status, and model readiness without live queries; see
[docs/mcp_setup.md](docs/mcp_setup.md) and
[docs/agent_output_contract.md](docs/agent_output_contract.md).

For agent clients that support skills, [`skills/citeguard-verify/SKILL.md`](skills/citeguard-verify/SKILL.md) makes CiteGuard **proactively** verify citations while you write (and present results without silently editing your text). It is written for MCP-compatible agents such as Codex, Claude Code, Cursor, and similar clients.

### As a Python library

```python
from citeguard.retrieval.scholarly_clients import build_live_metadata_source
from citeguard.verification import parse_citation, verify_citation, check_claim_support

source = build_live_metadata_source(["openalex", "arxiv"], mailto="you@example.com")

result = verify_citation(parse_citation(title="Attention Is All You Need", arxiv_id="1706.03762"), source)
print(result.verdict.value, result.confidence)          # -> verified 0.7

support = check_claim_support("The Transformer relies entirely on attention.",
                              parse_citation(title="Attention Is All You Need", arxiv_id="1706.03762"),
                              source)
print(support.verdict.value, support.engine)
```

---

## Configuration

| variable | default | purpose |
|---|---|---|
| `CITEGUARD_SOURCES` | `openalex,crossref,arxiv` | which sources to query (plus `semantic_scholar` / `s2`); unknown names fail fast |
| `CITEGUARD_MAILTO` | — | real contact email for polite OpenAlex/Crossref; unset values are not sent as `mailto` |
| `SEMANTIC_SCHOLAR_API_KEY` | — | optional, improves Semantic Scholar access |
| `CITEGUARD_CACHE` | `data/logs/verification_cache.sqlite` | local SQLite resolution cache |
| `CITEGUARD_FIXTURE_CITATIONS` | — | JSON/JSONL citation fixture for deterministic offline runs |
| `CITEGUARD_HTTP_TIMEOUT` | `10` | timeout, in seconds, for live scholarly API calls |
| `CITEGUARD_REMOTE_EVIDENCE` | `0` | set to `1` to fetch landing-page snippets in addition to title/abstract metadata |
| `CITEGUARD_RERANKER_MODEL` / `CITEGUARD_NLI_MODEL` | English models | support deep-mode models — set multilingual ones for non-English claims |

The full runtime contract (retry/backoff knobs, evidence timeouts, cache paths,
remote-evidence boundaries) is in [docs/configuration.md](docs/configuration.md).

Support deep mode downloads model weights on first use; pre-download with
`python3 scripts/warmup_support_models.py`. Without the `[models]` extra,
support runs a labelled `heuristic` engine which never emits `supported` or
`contradicted`; `citeguard status` reports this as
`support_models.engine=heuristic_fallback` with
`next_action=install_or_configure_dependency`.

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

**In scope today:** existence + metadata verification, abstract-level claim-support verification, user-provided local full-text evidence files, multi-citation claim checks, multi-source adapters, SQLite caching, Markdown/LaTeX/BibTeX/BBL/DOCX reference extraction, an MCP server, a Claude Code skill, and offline evals.

**Known limitations**

- **Identifiers are the reliable path.** With a DOI or arXiv id, resolution is definitive — provide one when you can.
- **Title-only matching is best-effort.** A title can map to several records (e.g. an original paper plus a later reprint with a different `publication_year`); without an identifier a correct citation can surface a same-title record and be reported as a `metadata_mismatch` on `year`/`venue`. Treat title-only year/venue mismatches as "needs confirmation".
- **Support is abstract-level unless you provide full-text evidence.** It judges the abstract, harvested metadata snippets, and any lawful local text/PDF evidence you provide; abstain (`insufficient_evidence`) is common and intentional.
- **The support eval is a synthetic seed fixture**, split into train/dev/test — a regression fixture, not a final human-reviewed benchmark.

**Not yet done:** automated full-text retrieval, full-text multi-hop synthesis across papers, counter-evidence verdicting, a large human-reviewed benchmark. See [ROADMAP.md](ROADMAP.md).

---

## Tests & reproducibility

```bash
python3 -m unittest discover -s tests -v   # full unittest suite; optional MCP stdio smoke skips without the MCP SDK
python3 scripts/smoke_mcp.py --require-sdk # MCP stdio smoke; the MCP SDK requires Python 3.10+
python3 scripts/eval_verification.py       # offline, deterministic existence/metadata eval
python3 scripts/eval_support.py --report --split test --quality-gate
python3 scripts/release_package_gate.py    # full release gate; add --require-build-tools before publishing
```

The unit suite and evals are network-free and run in CI. Eval datasets live in
[`data/eval/`](data/eval/). The support eval workflow — metrics, quality gates,
label-provenance sidecars, and blinded annotation packets — is documented in
[docs/support_eval.md](docs/support_eval.md); release smokes and publish flows
are in [docs/release_checklist.md](docs/release_checklist.md).

---

## Project layout

```text
citeguard/
  verification/   # the core: parse, resolve, verify, audit, cache, claim-support, evals
  cli.py          # zero-dependency `citeguard` command for status/verify/audit
  runtime.py      # shared environment, source, cache, and status configuration
  mcp/            # FastMCP server exposing status + verification tools
  retrieval/      # scholarly source adapters (OpenAlex/Crossref/arXiv/Semantic Scholar) + retrievers
  verifiers/      # existence/metadata + the reranker+NLI support ensemble
  citation/ graph/ audit/                 # shared models and helpers
  orchestrator/ planner/ writer/ benchmark/ api/   # source-checkout experiments and benchmark/API utilities
skills/citeguard-verify/   # reusable Codex/Claude/Cursor agent skill
scripts/                   # demo + eval + corpus/model utilities
data/eval/                 # offline benchmarks
docs/                      # release docs, architecture, benchmark notes, spike notes
tests/                     # unittest suite
```

New user code should import from `citeguard` or `citeguard.*`. The historical
root-package compatibility bridge has been removed; both source checkouts and
published packages expose the `citeguard.*` product
surface; see [`docs/public_api_migration.md`](docs/public_api_migration.md).

---

## Documents

- Setup/reference: [`docs/configuration.md`](docs/configuration.md) · [`docs/mcp_setup.md`](docs/mcp_setup.md) · [`docs/cli_reference.md`](docs/cli_reference.md) · [`docs/agent_output_contract.md`](docs/agent_output_contract.md) · [`docs/error_codes.md`](docs/error_codes.md) · [`docs/public_api_migration.md`](docs/public_api_migration.md)
- Benchmarks: [`docs/support_eval.md`](docs/support_eval.md) · [`docs/benchmark_design.md`](docs/benchmark_design.md) · [`docs/benchmark_todo.md`](docs/benchmark_todo.md) · [`docs/support_labeling_guidelines.md`](docs/support_labeling_guidelines.md)
- Release/safety: [`docs/release_checklist.md`](docs/release_checklist.md) · [`docs/security_compliance.md`](docs/security_compliance.md)
- Architecture: [`docs/architecture.md`](docs/architecture.md) · Roadmap: [`ROADMAP.md`](ROADMAP.md) · ChinaXiv spike: [`docs/chinaxiv_spike.md`](docs/chinaxiv_spike.md)

## Citation

If you use this repository in research, please cite the software record in [`CITATION.cff`](CITATION.cff).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Released under the [MIT License](LICENSE).
