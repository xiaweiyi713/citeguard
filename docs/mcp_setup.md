# MCP Setup

CiteGuard exposes citation verification through a stdio MCP server.

## Install

```bash
python -m pip install -e ".[mcp]"
```

The MCP server requires Python 3.10 or newer because the upstream MCP SDK does.
The core CLI/library still supports Python 3.9.

## Run

```bash
citeguard-mcp
```

MCP client configuration:

```json
{
  "mcpServers": {
    "citeguard": {
      "command": "citeguard-mcp"
    }
  }
}
```

For local source checkout testing without an editable install:

```json
{
  "mcpServers": {
    "citeguard": {
      "command": "python",
      "args": ["-m", "citeguard.mcp.server"]
    }
  }
}
```

## First Call

Call `citeguard_status_tool` before verification. It reports:

- Python/MCP readiness
- configured source names
- source-level readiness in `source_health`
- cache path, writability, and non-sensitive `cache_status`
- remote evidence policy, including blocked gated-source host suffixes
- live-source HTTP User-Agent and contact configuration
- machine-readable `polite_access` status for OpenAlex/Crossref contact-email readiness
- whether a contact email is configured
- whether Semantic Scholar API key is configured
- whether deep support model dependencies are installed

## Tools

| tool | use it for |
|---|---|
| `citeguard_status_tool` | configuration and dependency readiness; optionally run source probes |
| `verify_citation_tool` | one citation existence/metadata check |
| `audit_citations_tool` | batch existence/metadata checks |
| `check_claim_support_tool` | one claim against one cited paper |
| `check_claim_support_set_tool` | one claim against a set of cited papers |
| `search_counterevidence_tool` | possible counter-evidence candidates; review leads only |
| `audit_claim_support_tool` | many claim/citation pairs, including per-claim citation sets |

Claim-support tool results include `evidence_scope`. Treat `title`, `abstract`,
`metadata`, and `metadata_snippet` as limited evidence, not full-text support.
When the user has a lawful paper-body excerpt, MCP callers may pass `abstract`,
`evidence_text`, `full_text`, or structured `evidence_chunks` on claim-support
tools. Only `full_text` is tagged as full-text evidence; CiteGuard will not fetch
or bypass gated full text for the agent.

`search_counterevidence_tool` can be used after weak, insufficient, or
contradicted support results to find papers worth reviewing. It does not prove a
claim is contradicted, and an empty candidate list does not prove that no
counter-evidence exists. The response includes `query_plan`, `query_results`,
stable `next_action`, and per-candidate `matched_query_roles` so agents can
explain why a candidate was surfaced without treating the retrieval signal as a
verdict. Candidate-bearing responses use
`next_action=review_counterevidence_leads`; source-limited empty responses use
`next_action=retry_or_check_source_health`.
For batch workflows, `audit_claim_support_tool` and
`check_claim_support_set_tool` also accept `include_counterevidence=true` and
`counterevidence_top_k` to attach those candidate reports directly to
review-worthy results.
Batch tools return `review_summary` alongside `summary` and `risk_ranking`.
Use it as the agent entry point for high/medium/low risk counts,
`next_action` counts, top risk indexes, and `action_queues` such as
`identity_resolution_indexes`, `evidence_review_indexes`,
`rewrite_or_replace_indexes`, `source_retry_indexes`, and
`safe_to_keep_indexes` before expanding individual rows.
Both `audit_citations_tool` and `audit_claim_support_tool` accept
`high_risk_only=true`; filtered responses preserve full `review_summary` counts
and include `filtered.returned_indexes` / `filtered.omitted_indexes` using the
original batch indexes. They also include `filtered.omitted_review_summary`,
which preserves omitted rows' risk counts, `next_actions`, and `action_queues`
so agents can explain what the high-risk filter hid.
`audit_claim_support_tool` items can be single-citation objects with `claim`
plus citation fields, or citation-set objects with `claim` plus `citations`, a
non-empty list of citation objects. Citation-set rows return
`input_mode=citation_set`, aggregate `support_mode`, supporting/contradicting
counts, and per-citation child results.

`citeguard_status_tool` defaults to no live source queries. Pass
`check_sources=true` to run a lightweight per-source health probe, and optionally
set `health_query` to a known paper title for the project. Probe results include
the same `available` / `empty` / `unavailable`, structured failure detail, and
`cache_hit` fields as the CLI status command. The top-level `schema_version` and
nested `source_health.schema_version` fields version the machine-readable status
contract. The `source_health.summary` block is the agent-friendly entry point:
it reports status counts, configured/checked/responded/unchecked sources,
available/failed sources, invalid source names, `degraded`,
`all_checked_sources_failed`, summary-level `failure_count` and
`failure_details`, `failure_kind_counts`, `failure_kind_sources`, a stable
`recovery_code`, and a stable `next_action` (`continue`, `inspect_source_health`,
`retry_or_check_source_health`, or `fix_configuration`) for retry or
configuration decisions.
`cache_status` reports cache schema version, entry counts, entry-prefix counts,
timestamp bounds, size, `inspect_ok`, and stable `next_action` without exposing
raw cache queries.
`polite_access` reports whether live scholarly-source access is compliant with
the configured source set, which sources require `CITEGUARD_MAILTO`, and the
stable `next_action` (`continue` or `fix_configuration`). Per-source
`polite_access.status` lets agents distinguish missing contact configuration
from source availability; it is a setup concern, not evidence that a citation is
missing or fabricated.

## Offline Smoke Test

```bash
python scripts/smoke_mcp.py
```

Use the strict form in CI or release checks:

```bash
python scripts/smoke_mcp.py --require-sdk
```

The smoke test starts the installed `citeguard-mcp` stdio server when the console
script is available (falling back to `python -m citeguard.mcp.server` for local
development), initializes an MCP client, lists tools, checks the public tool
names, calls `citeguard_status_tool`, verifies a fixture citation through
`verify_citation_tool`, runs one fixture-backed `audit_citations_tool` batch and
checks its `review_summary`, runs one fixture-backed
`check_claim_support_tool` call, runs one fixture-backed
`audit_claim_support_tool` citation-set item (`input_mode=citation_set`) and
checks its `review_summary`, calls `search_counterevidence_tool` for an offline
review lead with `signal=explicit_contradiction_cue` and
`next_action=review_counterevidence_leads`, and confirms expected input failures
return the structured error contract (`ok=false`, `error.code`,
`error.recovery`, `error.next_action`, `error.details.tool`, and batch shape
`details.expected` / `details.received`). It sets
`CITEGUARD_FIXTURE_CITATIONS` so no live scholarly source is contacted.

If the MCP SDK is not installed, the default command prints a skip message and
exits 0 for local developer convenience. With `--require-sdk`, missing MCP dependencies are a failure.
The core package supports Python 3.9+, but the MCP SDK requires Python 3.10+; use a Python 3.10+ environment for real
`citeguard-mcp` stdio acceptance.

## Tool Input Contract

MCP tools return stable `invalid_input` payloads for malformed citation fields
instead of transport exceptions. String fields such as `title`, `doi`, and
`arxiv_id` must be strings; `authors` must be a list of strings; `year` may be
an integer or digit string. Errors include `details.tool`, `details.field`, and
`details.index` for batch inputs. Top-level batch shape errors also include
`details.expected` and `details.received`; for example,
`audit_citations_tool(citations=...)` reports `details.field=citations`,
`audit_claim_support_tool(items=...)` reports `details.field=items`, and
`check_claim_support_set_tool(citations=...)` reports
`details.expected=non_empty_list` when the set input is missing or malformed.

## Environment

| variable | default | purpose |
|---|---|---|
| `CITEGUARD_SOURCES` | `openalex,crossref,arxiv` | Live scholarly sources to query. |
| `CITEGUARD_MAILTO` | `research@example.com` | Contact email for polite OpenAlex/Crossref usage. |
| `SEMANTIC_SCHOLAR_API_KEY` | empty | Optional Semantic Scholar key. |
| `CITEGUARD_CACHE` | `data/logs/verification_cache.sqlite` | SQLite cache path; use `:memory:` for ephemeral runs. |
| `CITEGUARD_FIXTURE_CITATIONS` | empty | JSON/JSONL citation fixture for offline deterministic runs. |
| `CITEGUARD_HTTP_TIMEOUT` | `10` | Live scholarly API timeout in seconds. |
| `CITEGUARD_HTTP_RETRIES` | `1` | Short retries for transient `429`/`5xx`/timeout failures. |
| `CITEGUARD_HTTP_RETRY_BACKOFF` | `0.2` | Base retry backoff in seconds; `Retry-After` is capped for interactive use. |
| `CITEGUARD_REMOTE_EVIDENCE` | `0` | Enable slower landing-page snippet harvesting. |
| `CITEGUARD_EVIDENCE_TIMEOUT` | `2` | Landing-page evidence timeout in seconds. |
| `CITEGUARD_RERANKER_MODEL` | built-in default | Claim-support reranker model. |
| `CITEGUARD_NLI_MODEL` | built-in default | Claim-support NLI model. |

## Offline Replay

To turn live cache results into a deterministic fixture:

```bash
citeguard cache export --deterministic --output replay_fixture.json
CITEGUARD_FIXTURE_CITATIONS=replay_fixture.json citeguard verify --title "Attention Is All You Need"
```

`--deterministic` strips timestamp-only record provenance and timestamp-only
manifest fields while preserving source, query, and raw match score metadata, so
the replay fixture and export manifest can be compared across runs.

When `CITEGUARD_FIXTURE_CITATIONS` is set, `citeguard_status_tool` reports
fixture mode and live scholarly sources are bypassed.

## Agent Safety

- Do not describe `not_found` as fake or fabricated.
- When tool output includes `outage_limited=true` or
  `source_failure_mode=all_sources_failed`, treat `not_found` as inconclusive
  and retry later, check source health, or ask for a DOI/arXiv id.
- Use `sources_available` for sources that were checked and did not fail;
  `sources_responded` only means a source returned candidate records.
- Do not silently rewrite user citations.
- Prefer DOI/arXiv ids when a citation is ambiguous.
- Treat heuristic support checks as weak evidence.
