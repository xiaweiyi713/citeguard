# Agent output contract

This document is the field-level reference for the machine-readable output
CiteGuard returns to agents from the CLI and MCP tools. The README keeps only
the high-level surface; everything an agent needs to parse lives here.

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
per-candidate `matched_query_roles` so agents can explain whether a lead came
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
`mixed_with_full_text`, or `none`) so agents can avoid presenting abstract-level
evidence as a full-text conclusion. Full-text support is opt-in: callers can
provide short lawful excerpts via CLI/MCP/JSON inputs or local text/PDF
`--full-text-file` / JSON `full_text_file` paths. PDF extraction uses optional
`pypdf`/`PyPDF2` when installed (`pip install "citeguard[pdf]"`); CiteGuard
still does not scrape gated sources, download remote full text, or bypass
paywalls. If deep support models are installed
but fail to load or time out, support outputs include `model_failure_details`
with `error_code=model_unavailable` and fall back to available weaker scoring.

## `citeguard_status_tool` / `citeguard status`

After connecting the MCP server, call `citeguard_status_tool` once. It reports the
configured scholarly sources, cache path and non-sensitive `cache_status`,
MCP/Python readiness, contact-email status, Semantic Scholar key presence, and
whether deep claim-support model dependencies are installed, without querying
live sources or loading model weights. It also includes `remote_evidence_policy`
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
