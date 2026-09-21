# Agent output contract

This document is the field-level reference for the machine-readable output
CiteGuard returns to agents from the CLI and MCP tools. The README keeps only
the high-level surface; everything an agent needs to parse lives here.

## Contract version and JSON Schema

Every public CLI and MCP response has a root `contract_version: "v1"`. Batch
rows inherit the enclosing response contract and do not repeat the marker. The
schema shipped with the installed package is
`citeguard/contracts/v1/agent-output.schema.json`; callers can locate and load
it with `citeguard.contract_schema_path()` and `citeguard.load_contract_schema()`.

The v1 schema freezes the citation `verdict`, support `verdict`, `risk`,
`evidence_scope`, and `next_action` vocabularies. Adding optional fields is
compatible. Removing a field, changing a field type, adding a required field,
or changing any frozen enum requires a new `contract_version`. Clients should
branch on structured fields rather than prose, and retain the root marker when
storing a response for later replay.

## Single-result and batch `next_action`

Single verification/support results and batch `risk_ranking` rows include a
stable `next_action` enum plus human-readable context, so agents can triage
`not_found`, `ambiguous`, `metadata_mismatch`, contradicted, and unresolved
support checks without parsing prose. Batch risk rows also include
`risk_reason` for compact "why" columns, such as `no_strong_match`,
`metadata_fields_mismatch`, `citation_identity_unresolved`, or
`available_evidence_does_not_confirm_claim`. They also include `suggested_fix`
objects for stable next-step UI, with `requires_user_confirmation` marking
changes an agent must propose rather than apply silently. Citation-audit risk rows also include
`mismatched_fields`, `suggested_citation`, and canonical identifiers when a
metadata correction is available, so agents can propose repairs from the
risk-sorted list without re-parsing full result rows.

Common `next_action` values include
`keep`, `keep_claim`,
`review_metadata`,
`resolve_identifier_or_replace`, `disambiguate_identifier`,
`retry_or_check_source_health`, `review_counterevidence_leads`,
`inspect_full_text_or_find_stronger_citation`, and
`rewrite_or_replace_evidence`.

## Score semantics (`scores`)

Public citation and support results keep the legacy `confidence` number for
compatibility. That number is **not** a calibrated probability. The additive
`scores` block says what it is:

- `confidence_meaning=uncalibrated_score` and `not_a_probability=true`
- `calibration_status=uncalibrated` until a labeled slice is large enough
- `identity_match.score`: is the retrieved record the cited paper?
- `support_judgment.score`: does the inspected evidence support the claim?
  Null on citation-only verification.
- `evidence_coverage.scope`: `none`, `metadata`, `abstract`, `full_text`, or
  mixed. `complete_paper_reviewed` is false unless a later contract says a
  full-paper review actually happened. Finding one supporting span is not that.

Do not mix model logits, lexical overlap, and statistical probability. A value
of `0.85` is an uncalibrated score, not "85% likely correct."

Support results also include `supporting_spans` and `conflicting_spans`. These
are the evidence windows inspected for the claim. A non-empty supporting span
list is not a complete-paper review; `scores.evidence_coverage.complete_paper_reviewed`
stays false unless a later contract says otherwise.

## Identifier authority (`identifier_lookup`)

Single verification results include `identifier_lookup` (`null` when the input
carries no DOI/arXiv id): an object with `kind` (`arxiv_id` or `doi`), `value`,
`source` (the identifier's home source, `arxiv` or `crossref`), `status`, and
`failure_detail` when the lookup failed. `status` is `hit` (id confirmed at its
home source), `miss` (home source answered but the id was not found), `failed`
(authority lookup errored; the result is source-limited, not fabrication
evidence), or `unavailable` (home source not configured).

## Batch `review_summary`

Batch `audit` and `support-audit` reports
include `review_summary` with full-batch risk counts, next-action counts,
top risk indexes, and `action_queues` grouped into stable index lists such as
`identity_resolution_indexes`, `evidence_review_indexes`,
`rewrite_or_replace_indexes`, `source_retry_indexes`, and
`safe_to_keep_indexes`. `review_summary.recommended_next_steps` adds
`first_queue`, `first_action`, ordered `steps`, and `safe_to_keep_indexes`, so
agents can report the highest-priority fix before lower-risk review work.
`review_summary.suggested_fix_summary` aggregates `suggested_fix.kind` counts,
`confirmation_required_indexes`, `no_confirmation_required_indexes`, and
`missing_suggested_fix_indexes`; its `auto_apply_allowed=false` policy reminds
agents that even machine-readable fixes must be proposed, not silently applied.
`review_summary.triage_plan` adds a compact `status`, `next_action`,
`first_queue`, `review_required_indexes`, and policy string; `next_action`
comes from the stable action registry, while `recommended_next_steps.first_action`
is the compact queue action to display. `source_retry_indexes` remain
inconclusive retry work, not evidence of fabrication.
`review_summary.source_traceability` summarizes extracted source-backed rows
with source paths, formats, original source indexes, review-required locators,
and high-risk source indexes, so agents can route fixes back to bibliography
items without expanding every result row.

## Claim-support provenance fields

Claim-support outputs include
`counterevidence_review`; when it is `true`, treat the item as needing
human/full-text review for contradiction, weak support, insufficient evidence, or
unresolved citation identity. Support-audit risk rows carry compact provenance
too: `support_confidence`, `support_engine`, `resolution_verdict`,
`resolved_title`, `evidence_source_name`, `evidence_source_field`, and
`evidence_source_url`, so agents can show the evidence source without guessing
from field-name prefixes. When a row came from an extracted reference file,
risk rows and support resolutions also carry `input_source_path`,
`input_source_format`, `input_source_index`, `input_source_locator`, and, when
available, `input_source_line_start` / `input_source_line_end` for traceability
back to the original bibliography item.

Citation-audit and support-audit rows also carry `canonical_metadata_quality`,
`source_metadata_missing_fields`, and `source_metadata_confidence_effect` when a
live source returned sparse metadata, so compact tables can flag incomplete
source metadata without calling the citation fake or treating missing fields as
claim-support evidence.

## Evidence object

Every claim-support result now keeps its legacy `evidence.text`,
`source_field`, `source_url`, and `evidence_scope` fields and also includes a
versioned `evidence.evidence_object`. Citation-set `evidence[]` entries carry
the same nested object. It is an additive v1 field, so existing clients can
continue reading the legacy fields while new clients use one provenance shape:

- `source`: source name, URL, input field, and local path when known.
- `fragment`: the exact returned text fragment plus its `sha256` digest.
- `locator`: an exact line/paragraph range when supplied, otherwise an explicit
  file, URL, chunk, or source-field locator with its available granularity.
- `retrieval`: the retrieval method and `retrieved_at`. `retrieved_at=null`
  means CiteGuard did not fetch or read the source itself, rather than inventing
  a provenance time for a user-pasted excerpt.
- `license`: source-reported or caller-context status, value, and rights basis.
`user_provided_not_verified` means the caller supplied the text; it is not a
  license determination. `open_access_license_*` records only that a source
  marked the fetched location as open access.

The digest is for `fragment.text` after CiteGuard's text normalization. It is a
stable integrity handle for the returned snippet, not a hash of the entire PDF,
web page, or paper and not a claim that the text is licensed for redistribution.
An OA body that exceeds CiteGuard's fetch budget is rejected as unavailable
instead of being silently truncated and labelled `full_text` evidence.

## Document-audit snapshot

The `audit_document` CLI/MCP response is defined by the v1
`document_audit_response` schema. In addition to extracted candidates and the
suggestion-only queue, `document.snapshot` contains a digest over the resolved
file paths, byte counts, content hashes, and read modes used by that call.
`document.snapshot.files[]` makes included LaTeX and BibTeX dependencies
visible. A client must treat a queue as stale when that digest no longer
describes the current files and request a fresh audit before proposing a change.
This is an input-integrity handle, not a publication hash or a license claim.
`document.dependencies.missing` lists in-root `\input`/`\include` or
`\bibliography` files that were referenced but unavailable; such a partial
read sets `review_status.incomplete=true` and `next_action=repair_input` even
when the citation queue itself is empty.
The additive `review_status` block gives agents one branch point: `state` is
`clear` or `review_required`, `next_action` is from the frozen v1 action
vocabulary, and `snapshot_digest` binds that status to the exact input version.
Re-run the audit when the current snapshot digest differs before acting on the
queue.

Markdown and LaTeX audits also emit `body_links`, `unlinked_markers`, and
`claim_reviews`, tracing citing sentence → marker → bibliography entry →
identity result → available evidence → a suggestion-only rewrite. Unlinked
markers remain in the payload instead of disappearing. `--html` writes a local
HTML view of the same model.
An empty in-scope document is valid and returns a clear audit with
`document.read.total_bytes=0`; it is not treated as a file error.

## High-risk filtering (`--high-risk-only`)

When using `--high-risk-only`, the `filtered` block includes
`returned_indexes` and `omitted_indexes` so the compact result list can still be
mapped back to the original batch input. It also includes
`omitted_review_summary`, preserving the omitted items' next-action counts and
review queues, source traceability, plus recommended next steps so agents can
report what was hidden by the high-risk filter.

## Counter-evidence leads (`--with-counterevidence`)

Use `--with-counterevidence` on support batch commands when you want CiteGuard to
attach possible counter-evidence candidates to review-worthy items; these
are leads to inspect, not contradiction verdicts. Counter-evidence reports
include `next_action`, `query_plan`, `query_results`, `review_summary`, and
per-candidate `matched_query_roles` / `sources` so agents can explain whether a lead came
from the original claim search, a negation probe, an exception probe, or a
`source_outage_safety` probe for overclaims that treat source failures as
fabrication evidence, including Chinese claims such as "源不可达/未找到证明引用伪造".
`review_summary.signal_counts`, `review_summary.matched_query_role_counts`, and
`review_summary.top_candidate` support compact risk tables without parsing
candidate prose. `review_summary.recommended_next_steps` gives stable queues
such as `explicit_contradiction_candidate_indexes`,
`source_outage_safety_candidate_indexes`, and `related_candidate_indexes` so an
agent can show the safest review order without treating candidates as verdicts.
`signal=source_outage_safety_cue` is still only a review lead, not a
contradiction verdict.
Use each query row's `sources_responded` / `sources_failed` for query-level
diagnostics. Top-level `sources_responded` covers the full retrieved pool before
`top_k` truncation and preserves all sources represented by merged records.

## Citation-set support (`support-set`)

Support-set reports include `support_mode` and per-evidence citation `index` so
agents can distinguish a single strong citation from multiple weak citations
without overstating tentative corroboration. They also include aggregate
`support_mode_details` with stable per-verdict indexes, a decision code, and the
policy `contradictions_dominate; multiple_weak_citations_remain_tentative;
no_unstated_multi_hop_or_full_text_support`. Aggregate `evidence_scopes`,
`evidence_source_names`, and `evidence_source_fields` let an agent show
set-level evidence provenance without expanding every child result.

## Evidence scope

Support results include a machine-readable `evidence_scope` (`title`,
`abstract`, `metadata`, `metadata_snippet`, `full_text`, `mixed`,
`mixed_with_full_text`, `unknown`, or `none`) so agents can avoid presenting abstract-level
evidence as a full-text conclusion. Full-text support is opt-in: callers can
provide short lawful excerpts via CLI/MCP/JSON inputs or local text/PDF
`--full-text-file` / JSON `full_text_file` paths. PDF extraction uses optional
`pypdf`/`PyPDF2` when installed (`pip install "citationguard[pdf]"`). With
`CITEGUARD_OA_FULLTEXT=1`, CiteGuard can also fetch the paper body itself, but
only from locations the source marks as open access; the fetch report appears
as `resolution.oa_fulltext` with `status`, `source_url`, `content_type`, and
`chunk_count`, and a failed fetch never changes a verdict. CiteGuard still does
not scrape gated sources or bypass paywalls. If deep support models are installed
but fail to load or time out, support outputs include `model_failure_details`
with `error_code=model_unavailable` and fall back to available weaker scoring.

## `citeguard_status_tool` / `citeguard status`

After connecting the MCP server, call `citeguard_status_tool` once. It reports the
configured scholarly sources, cache path and non-sensitive `cache_status`,
MCP/Python readiness, contact-email status, Semantic Scholar key presence, and
the configured support profile. `support_models.requested_engine` is `auto`,
`heuristic`, or `production`; `model_loading_enabled=false` means the user chose
the low-resource heuristic profile, so do not call it a missing-model failure.
The status call itself does not query live sources or load model weights. It also includes `remote_evidence_policy`
and a source-level
`source_health` block that says which sources are configured, whether a fixture
is bypassing live sources, whether gated-source host suffixes are blocked, and
whether source-specific credentials such as `CITEGUARD_MAILTO` or
`SEMANTIC_SCHOLAR_API_KEY` are configured. `source_health.summary` gives agents a
compact `degraded` flag, status counts, available/failed source lists, stable
`failure_count`, summary-level `failure_details`, `failure_kind_counts`,
`failure_kind_sources`, summary-level `retry_after_seconds`,
`retry_after_sources`, summary-level `retry_delay_seconds`,
`retry_delay_sources`, `retry_guidance`, `confidence_effect`, `interpretation`,
`recovery_code`, and stable `next_action` for retry/configuration decisions.
Each `source_health.sources[]` item carries its own source-level `next_action`,
`confidence_effect`, `interpretation`, `recovery_code`, `retry_after_seconds`,
`retry_delay_seconds`, and `retry_guidance`, so agents can wait on a
rate-limited Semantic Scholar probe or retry one failed source without treating
the whole citation as fake.

`confidence_effect=partial_source_limited` or `all_sources_unavailable` and
`interpretation=source_outage_lowers_confidence_not_fabrication_evidence` mean
the result is source-limited, not proof that a citation is fabricated. Each
HTTP-backed failure detail also includes
`attempt_count`, `retry_count`, `final_url` / `redirected` when a DOI resolver
or publisher landing page moved the request, optional `retry_after_seconds`
parsed from numeric or HTTP-date `Retry-After`, and optional `retry_delay_seconds` for the
actual capped client wait used before a retry, so agents can tell whether a
timeout or rate-limit was already retried and whether the source asked clients
to wait before recommending another live probe. When summary
`retry_guidance=wait_before_retry`, use summary `retry_after_seconds` as the
minimum wait hint before probing those `retry_after_sources` again. A
`retry_after_seconds=0.0` hint is preserved for provenance but does not require a
wait; follow the ordinary retry/source-health guidance. Malformed JSON
from a live scholarly source is reported as `code=source_unavailable`,
`kind=invalid_json`, so agents retry or inspect source health instead of treating
an empty parse result as missing evidence.

Resolved records also carry `metadata.metadata_quality` when a live adapter
returns sparse fields. It lists `present_fields`, `missing_fields`, identifier
provenance, and
`confidence_effect=missing_metadata_lowers_confidence_not_fabrication_evidence`
so agents can call out incomplete metadata without calling the citation fake.
`cache_status` gives agents cache schema version, entry counts, timestamp
bounds, `inspect_ok`, and stable `next_action` without exposing raw cache
queries.

## Expected-error payloads

CLI commands print JSON on success. Expected usage, input, file, and JSON-parse
errors are also machine-readable on stderr. MCP tools use the same shape for
expected tool-input errors, returned as the tool result instead of a transport
exception:

```json
{"ok": false, "schema_version": 1, "error": {"code": "missing_citation_input", "message": "...", "details": {}, "recovery": "Ask for a DOI, arXiv id, title, or pasted reference.", "next_action": "provide_missing_input"}, "exit_code": 2}
```

See [`error_codes.md`](error_codes.md) for the stable error-code
contract, `error.next_action` mapping, and agent recovery policy.
