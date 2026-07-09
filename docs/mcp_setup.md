# MCP Setup

CiteGuard exposes citation verification through a stdio MCP server.

## Install

For an installed or published package:

```bash
python -m pip install "citationguard[mcp]"
```

For a local source checkout:

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
Do not claim full-text support from an abstract-level support result.
When the user has a lawful paper-body excerpt, MCP callers may pass `abstract`,
`evidence_text`, `full_text`, `full_text_file`, or structured `evidence_chunks`
on claim-support tools. Only `full_text` / `full_text_file` inputs are tagged as
full-text evidence; CiteGuard will not fetch or bypass gated full text for the
agent.

`search_counterevidence_tool` can be used after weak, insufficient, or
contradicted support results to find papers worth reviewing. It does not prove a
claim is contradicted, and an empty candidate list does not prove that no
counter-evidence exists. The response includes `query_plan`, `query_results`,
stable `next_action`, `review_summary`, and per-candidate
`matched_query_roles` so agents can explain why a candidate was surfaced
without treating the retrieval signal as a verdict. `review_summary` includes
`signal_counts`, `matched_query_role_counts`, `top_candidate`, and
`recommended_next_steps` queues such as
`explicit_contradiction_candidate_indexes`,
`source_outage_safety_candidate_indexes`, and `related_candidate_indexes`, plus
`policy=review_leads_not_contradiction_verdicts` for compact agent triage.
Claims that overinterpret source outages, timeouts, or `not_found` as
fabrication evidence, including Chinese source-outage/not-found overclaims, add
a `source_outage_safety` query role; candidates may use
`signal=source_outage_safety_cue` when they explicitly say source failures lower
confidence without proving fabrication. Candidate-bearing responses use
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
`safe_to_keep_indexes` before expanding individual rows. The same summary
includes `recommended_next_steps` with `first_queue`, `first_action`, ordered
`steps`, and `safe_to_keep_indexes` for a compact agent review plan. It also
includes `review_summary.triage_plan` with stable `status`, stable
`next_action`, `first_queue`, `review_required_indexes`, and the policy that
source retry is inconclusive, not fabrication evidence. Use
`triage_plan.next_action` for machine branching and
`recommended_next_steps.first_action` for the compact queue action to display.
Individual `risk_ranking` rows expose compact
`risk_reason` values and machine-readable `suggested_fix.kind`,
`suggested_fix.action`, and `suggested_fix.requires_user_confirmation`; agents
should use those fields for the "why" and next-step columns and must not
silently edit a user's references when confirmation is required.
For batch-level UI or automation, `review_summary.suggested_fix_summary`
aggregates `suggested_fix.kind` counts, `confirmation_required_indexes`,
`no_confirmation_required_indexes`, and `missing_suggested_fix_indexes`; its
`auto_apply_allowed=false` policy means MCP hosts can propose repairs but must
ask before changing user text or citations.
Both `audit_citations_tool` and `audit_claim_support_tool` accept
`high_risk_only=true`; filtered responses preserve full `review_summary` counts
and include `filtered.returned_indexes` / `filtered.omitted_indexes` using the
original batch indexes. They also include `filtered.omitted_review_summary`,
which preserves omitted rows' risk counts, `next_actions`, `action_queues`, and
`recommended_next_steps` so agents can explain what the high-risk filter hid.
`audit_claim_support_tool` items can be single-citation objects with `claim`
plus citation fields, or citation-set objects with `claim` plus `citations`, a
non-empty list of citation objects. Citation-set rows return
`input_mode=citation_set`, aggregate `support_mode`, `support_mode_details`,
supporting/contradicting counts, and per-citation child results.
`support_mode_details` exposes stable per-verdict indexes and the policy
`contradictions_dominate; multiple_weak_citations_remain_tentative;
no_unstated_multi_hop_or_full_text_support`, so agents can branch without
parsing explanation text.

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
`failure_details`, `failure_kind_counts`, `failure_kind_sources`,
`confidence_effect`, `interpretation`, a stable `recovery_code`, and a stable
`next_action` (`continue`, `inspect_source_health`,
`retry_or_check_source_health`, or `fix_configuration`) for retry or
configuration decisions. When `confidence_effect` is `partial_source_limited` or
`all_sources_unavailable`,
`interpretation=source_outage_lowers_confidence_not_fabrication_evidence`
tells the host agent to lower confidence or retry instead of presenting a
fabrication finding. HTTP-backed failures include `attempt_count`,
`retry_count`, `final_url` / `redirected` for DOI or publisher redirects,
optional `retry_after_seconds`, and optional
`retry_delay_seconds`, letting agents distinguish a first failure from a source
that already exhausted CiteGuard's short retry policy, actually slept before a
retry, or explicitly asked clients to wait.
Each `source_health.sources[]` item also has source-level `next_action`,
`confidence_effect`, `interpretation`, `recovery_code`, `retry_after_seconds`,
`retry_delay_seconds`, and `retry_guidance`, so a host agent can wait on one
rate-limited source, retry one unavailable source, or continue with available
sources without treating source failure as citation fabrication.
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
names, checks batch tool metadata descriptions for `review_summary.triage_plan`,
`review_summary.suggested_fix_summary`, `risk_reason`,
`suggested_fix.requires_user_confirmation`, and `auto_apply_allowed=false`, calls
`citeguard_status_tool`, verifies a fixture citation through
`verify_citation_tool`, checks a single `verify_citation_tool` `not_found`
response for `next_action=resolve_identifier_or_replace` and conservative
wording that does not call the citation fake or fabricated, checks the fixture
`source_health.sources[]`
source-level item contract and `retry_delay_seconds` provenance, runs one
fixture-backed `audit_citations_tool` batch and checks its `review_summary`,
runs one fixture-backed
`check_claim_support_tool` call, runs one fixture-backed full-text support call
that verifies `evidence_scope=full_text` for caller-provided lawful evidence,
runs a second full-text support call with `full_text_file` and verifies
`user_full_text_file_1` provenance,
runs a `check_claim_support_set_tool` citation-set call with `full_text_file`
and verifies aggregate/nested `evidence_scope=full_text` provenance,
runs one fixture-backed `check_claim_support_set_tool` call with
`include_counterevidence=true` so one-claim/multiple-citation audits keep
aggregate review leads, runs one fixture-backed
`audit_claim_support_tool` citation-set item (`input_mode=citation_set`) and
checks its `review_summary`, runs a nested citation-set support-audit call with
`full_text_file` and verifies the low-risk `safe_to_keep_indexes` queue,
checks an `audit_claim_support_tool`
`include_counterevidence=true` plus `high_risk_only=true` batch so filtered
high-risk rows keep counter-evidence leads and omitted-row summaries, calls
`search_counterevidence_tool` for an offline
review lead with `signal=explicit_contradiction_cue` and
`next_action=review_counterevidence_leads`, and confirms expected input failures
return the structured error contract (`ok=false`, `error.code`,
`error.recovery`, `error.next_action`, `error.details.tool`, and batch shape
`details.expected` / `details.received`) plus `full_text_file` read failures
with `details.filename` and OS-level missing-file `details.errno`. It sets
`CITEGUARD_FIXTURE_CITATIONS` so no live scholarly source is contacted.

If the MCP SDK is not installed, the default command prints a skip message and
exits 0 for local developer convenience. With `--require-sdk`, missing MCP dependencies are a failure.
The core package supports Python 3.9+, but the MCP SDK requires Python 3.10+; use a Python 3.10+ environment for real
`citeguard-mcp` stdio acceptance. On systems where `python3` is still Python
3.9, create the smoke environment explicitly, for example with
`python3.11 -m venv .venv-mcp-smoke` before installing `.[mcp]`.

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
| `CITEGUARD_MAILTO` | empty | Real contact email for polite OpenAlex/Crossref usage; unset or placeholder values are not sent as `mailto`. |
| `SEMANTIC_SCHOLAR_API_KEY` | empty | Optional Semantic Scholar key. |
| `CITEGUARD_CACHE` | `data/logs/verification_cache.sqlite` | SQLite cache path; use `:memory:` for ephemeral runs. |
| `CITEGUARD_FIXTURE_CITATIONS` | empty | JSON/JSONL citation fixture for offline deterministic runs. |
| `CITEGUARD_HTTP_TIMEOUT` | `10` | Live scholarly API timeout in seconds. |
| `CITEGUARD_HTTP_RETRIES` | `1` | Short retries for transient `429`/`5xx`/timeout failures. |
| `CITEGUARD_HTTP_RETRY_BACKOFF` | `0.2` | Base retry backoff in seconds; numeric or HTTP-date `Retry-After` is capped for interactive use. |
| `CITEGUARD_HTTP_MIN_INTERVAL` | `0` | Minimum interval in seconds between uncached live-source HTTP requests from one adapter. |
| `CITEGUARD_REMOTE_EVIDENCE` | `0` | Enable slower landing-page snippet harvesting. |
| `CITEGUARD_EVIDENCE_TIMEOUT` | `2` | Landing-page evidence timeout in seconds. |
| `CITEGUARD_RERANKER_MODEL` | built-in default | Claim-support reranker model. |
| `CITEGUARD_NLI_MODEL` | built-in default | Claim-support NLI model. |

`citeguard_status_tool` exposes `support_models.engine`,
`support_models.deep_models_available`, `support_models.missing_dependencies`,
and `support_models.next_action`. If `next_action=install_or_configure_dependency`,
tell the user that claim-support checks are running in `heuristic_fallback`
mode and suggest installing `citeguard[models]` first. For local development,
use `.[models]` from a source checkout, then run
`python3 scripts/warmup_support_models.py` before relying on deep reranker/NLI
support. If `support_models.install_hint` is present, quote that package-first
hint instead of inventing a local install command.

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
