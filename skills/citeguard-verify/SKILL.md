---
name: citeguard-verify
description: Use when checking, auditing, or fixing citations in scientific or technical writing — verifying that cited papers actually exist, their metadata (title, authors, year, venue, DOI) is correct, and cited papers support nearby claims when needed. Triggers when the user is writing related work / a literature review / a bibliography, pastes references, or asks to "check my citations".
---

# CiteGuard Citation Verification

You verify citations against real scholarly sources before trusting them. You do NOT invent or guess whether a paper exists — you call the CiteGuard MCP tools.

## Install / connect

Install CiteGuard with the MCP extra:

```bash
python -m pip install "citationguard[mcp]"
```

From a local source checkout, use `python -m pip install -e ".[mcp]"`.

Register the stdio server in the host agent:

```json
{
  "mcpServers": {
    "citeguard": {
      "command": "citeguard-mcp"
    }
  }
}
```

Codex, Claude Code, Cursor, and similar MCP clients can all use the same command.
For a source checkout without console scripts, use `"command": "python"` and
`"args": ["-m", "citeguard.mcp.server"]`.

Client notes:

- Codex: add the server to the workspace or user MCP configuration, then call
  `citeguard_status_tool` before the first citation check in a thread.
- Claude Code: add the same stdio server entry to the project's MCP
  configuration, then copy this skill into the project's skills directory if the
  client supports reusable skills.
- Cursor: add the server under MCP settings with command `citeguard-mcp`; keep
  this file as project instructions so the agent knows when to verify citations.

## When to use

- The user is drafting related work, a literature review, or a reference list.
- The user pasted citations / a bibliography and wants them checked.
- You are about to present citations you generated yourself — verify them first.
- The user asks for suggested references for a claim; verify existence before
  presenting the final bibliography.
- The user asks you to revise, format, or "clean up" references; audit before
  changing bibliographic content.
- The user gives a paragraph with citations attached to claims; check claim
  support, not just citation existence.

Proactive trigger checklist:

- Related work, literature review, survey, background, bibliography, references.
- "Find papers for this claim", "add citations", "is this citation real?",
  "check my references", "does this source support the sentence?"
- A pasted Markdown/LaTeX/Word-style reference section, compiled `.bbl`
  bibliography, or JSON/JSONL citation list.

## Never do this

- Do not silently change the user's references.
- Do not translate `not_found`, `source_unavailable`, or `timeout` into "fake".
- Do not claim full-text support from an abstract-level support result.
- Use `full_text`, `full_text_excerpt`, or `full_text_file` inputs only when the
  user supplies a short lawful excerpt, a local lawful text/PDF file, or an open
  source adapter provides one. Local PDF support may require the `citeguard[pdf]`
  extra. Never ask CiteGuard to download gated full text, bypass a paywall, or
  treat gated text as available evidence.
- Do not hide ambiguity; ask for a DOI/arXiv id when CiteGuard returns `ambiguous`.

## How to use

0. On first use in a session, call `citeguard_status_tool`. If it reports unknown
   sources, an unwritable cache directory, or missing model dependencies, mention
   the issue before running checks. Missing model dependencies only weaken deep
   claim-support checks; existence and metadata checks can still run. Read
   `support_models.engine`, `support_models.deep_models_available`,
   `support_models.missing_dependencies`, and `support_models.next_action`
   directly. If `support_models.next_action=install_or_configure_dependency`,
   say claim-support checks are in `heuristic_fallback` mode and suggest
   installing `citeguard[models]` (or `.[models]` from a source checkout) plus
   running `python3 scripts/warmup_support_models.py` before relying on deep
   reranker/NLI judgments. If `support_models.install_hint` is present, quote
   that package-first hint rather than inventing a local install command. If
   remote evidence harvesting is disabled, support checks still use
   title/abstract evidence; suggest enabling `CITEGUARD_REMOTE_EVIDENCE=1` only
   when the user wants slower, deeper landing-page snippet harvesting.
   To diagnose source outages, call `citeguard_status_tool` with
   `check_sources=true` and, when useful, a project-specific `health_query`.
   Do not run live probes repeatedly during normal citation checks. In the
   returned `source_health.summary`, branch first on `confidence_effect` and
   `interpretation`, then on `failure_kind_counts` and `failure_kind_sources` to
   distinguish timeouts, rate limits, HTTP errors, and network failures without
   parsing prose. Treat `confidence_effect=partial_source_limited` or
   `all_sources_unavailable` plus
   `interpretation=source_outage_lowers_confidence_not_fabrication_evidence` as
   an explicit instruction to lower confidence or retry, not to call a citation
   fabricated.
1. For a single citation, call the `verify_citation_tool` MCP tool with structured
   fields (`title`, `authors`, `year`, `doi`, `arxiv_id`) when you have them, or
   `raw_text` for a free-text reference. Identifiers (DOI/arXiv) give the most
   reliable result.
2. For a list, call `audit_citations_tool` with an array of citation objects.
3. For many claim/citation pairs, call `audit_claim_support_tool` with objects
   containing `claim` plus citation fields. If one batch item has a claim backed
   by multiple cited papers, put those papers in that item's `citations` array.
   Prefer this over many separate `check_claim_support_tool` calls when the user
   provides a paragraph, table, or bibliography with linked claims.
4. For one claim supported by multiple cited papers, call
   `check_claim_support_set_tool` with the single `claim` and a `citations`
   array, or use the same `citations` shape inside `audit_claim_support_tool`
   when auditing many claim rows. Treat this as abstract-level aggregation, not
   full-text multi-hop proof.
5. When a support result is weak, insufficient, contradicted, or otherwise marked
   with `counterevidence_review=true`, optionally call
   `search_counterevidence_tool` with the exact claim to find papers worth
   reviewing. Treat returned candidates as leads only, not as proof of
   contradiction or permission to silently rewrite the user's citation.
   If the counter-evidence report has
   `next_action=review_counterevidence_leads`, inspect the candidates or run
   support checks on them before recommending a rewrite.
   Use `review_summary.signal_counts`,
   `review_summary.matched_query_role_counts`, and
   `review_summary.top_candidate` to rank and display leads compactly. Prefer
   `review_summary.recommended_next_steps.first_queue`, `first_action`, and
   `steps`; common queues are `explicit_contradiction_candidate_indexes`,
   `source_outage_safety_candidate_indexes`, and `related_candidate_indexes`.
   Keep `review_summary.policy=review_leads_not_contradiction_verdicts` visible
   in your reasoning.
   For batch support tools, prefer setting `include_counterevidence=true` with a
   small `counterevidence_top_k` when the user explicitly asks for a skeptical
   audit or review-ready triage.
6. Read the `verdict` for each result:
   - `verified` — exists and metadata matches. Safe to keep.
   - `metadata_mismatch` — the paper exists but a field disagrees with the matched
     record. Show the wrong fields (`field_diffs`) and offer the `suggested_citation`.
     Caveat: when the citation had NO DOI/arXiv id and the only mismatch is `year`
     or `venue`, the matched record may be a same-title reprint/re-index and the
     user could be right. Present such cases as "possible mismatch — confirm or add
     a DOI/arXiv id", not as a definitive error.
   - `not_found` — could not be verified. Flag it clearly as high-risk and ask the
     user to confirm; do NOT assert it is fabricated.
     If `outage_limited=true` or `source_failure_mode=all_sources_failed`, present
     the result as inconclusive and recommend retrying or checking source health.
   - `ambiguous` — multiple plausible matches; ask the user to provide a DOI/arXiv id.
     Prefer `recovery_code=ambiguous_citation` when present instead of parsing prose.

Expected error recovery:

- `missing_citation_input`: ask for a title, DOI, arXiv id, or raw reference.
- `missing_claim`: ask for the exact claim sentence before running support tools.
- `invalid_json` / `invalid_input`: point to the malformed input and ask for a
  corrected JSON/JSONL item.
  When `error.details` includes `field`, `expected`, and `received`, name the
  broken field and the shape mismatch directly. For example, if
  `details.field=citations`, `details.expected=list`, and `details.received=str`,
  rebuild the MCP call with `citations` as an array of citation objects instead
  of asking the user to interpret the tool error.
- `source_unavailable` / `timeout`: say the check is inconclusive because a
  source was unavailable; do not call the citation fake.
- `model_unavailable`: continue existence/metadata checks, but label support
  checks as heuristic or unavailable.
- For every `ok=false` result, branch on `error.next_action`,
  `error.retryable`, and `error.category` instead of parsing `error.message`.
  Use `error.retryable=true` only for transient retry scheduling. Use
  `error.category=missing_input|input_repair|source_limited|dependency_limited|disambiguation`
  for compact UI grouping and queue labels.

## Checking claim support (deep mode)

After verifying a citation exists, you can check whether the paper actually supports
the sentence: call `check_claim_support_tool` with the `claim` sentence plus the
citation fields. When the sentence cites multiple papers together, call
`check_claim_support_set_tool` so the result can show per-citation evidence and a
single aggregate risk. Verdicts:
- `supported` / `weakly_supported` — the abstract entails (or partially supports) the claim.
- `insufficient_evidence` — the abstract does NOT address the claim. Present this as
  "the abstract can't confirm this — check the full text or a human", NOT as "the paper
  does not support it".
- `contradicted` — the abstract actively contradicts the claim; highlight as high-risk.

Notes: deep mode needs models (downloaded on first use; slow). If
`support_models.engine=heuristic_fallback`, say support checks are degraded
because deep models are missing or unconfigured, and never present heuristic
support results as final. For non-English claims, multilingual models can be
configured via environment variables.

## How to present results

- Use a compact table: `✓ verified` / `⚠ metadata` / `✗ not found` / `? ambiguous`.
- For `metadata_mismatch`, show what is wrong and the suggested correction.
- NEVER silently rewrite the user's citations. Propose changes and let them decide.
- Always mention which sources were checked (`sources_checked`).
- Use `sources_available` for checked sources that did not fail, and
  `sources_failed` for source outages. `sources_responded` only means a source
  returned candidate records, so an empty `sources_responded` is not by itself an
  outage.
- For status probes, read `source_health.summary.failure_kind_counts` and
  `failure_kind_sources`. If the dominant kind is `timeout`, recommend retrying
  or increasing timeouts; if it is `rate_limited`, recommend waiting, reducing
  batch size, or configuring credentials. If
  `source_health.summary.retry_guidance=wait_before_retry`, use summary
  `retry_after_seconds` and `retry_after_sources` as the wait hint instead of
  immediately probing again; individual failure details may also include
  `retry_after_seconds` for per-source context. Also read each
  `source_health.sources[]` item-level `next_action`, `confidence_effect`,
  `interpretation`, `recovery_code`, `retry_after_seconds`, and `retry_guidance`
  plus any failure `final_url` / `redirected` provenance from DOI or publisher
  redirects
  when only one source needs wait/retry/configuration handling. Also read
  `source_health.summary.confidence_effect` and
  `source_health.summary.interpretation`; if they say
  `partial_source_limited`, `all_sources_unavailable`, or
  `source_outage_lowers_confidence_not_fabrication_evidence`, say source health
  degraded confidence and is not evidence of fabrication.
- Use `next_action` when present for workflow branching instead of parsing
  `explanation`; use `recovery_code` as the underlying reason when it is present
  (`ambiguous_citation`, `timeout`, or `source_unavailable`).
- In batch `audit_citations_tool` and `audit_claim_support_tool` results, read
  `review_summary` first for full-batch high/medium/low risk counts,
  next-action counts, top risk indexes, `action_queues`, and
  `recommended_next_steps`. Prefer
  `review_summary.recommended_next_steps.first_queue`,
  `first_action`, and ordered `steps` for what to fix first. Use
  `review_summary.triage_plan.status`, stable `next_action`,
  `review_required_indexes`, and `policy` for the one-line batch decision:
  `review_required` means do not accept the batch without addressing queued
  rows, while `clear` means only low-risk rows remain. Its policy keeps source
  retry inconclusive; source retry inconclusive means retry/check health, not
  fabrication evidence. Use
  `rewrite_or_replace_indexes`, `identity_resolution_indexes`,
  `evidence_review_indexes`, `source_retry_indexes`, and
  `safe_to_keep_indexes` to make a compact review queue before expanding
  individual `risk_ranking` rows.
- In batch `risk_ranking`, also use `next_action` as the machine-readable action
  (`review_metadata`, `resolve_identifier_or_replace`,
  `disambiguate_identifier`, `retry_or_check_source_health`,
  `review_counterevidence_leads`, `inspect_full_text_or_find_stronger_citation`,
  `rewrite_or_replace_evidence`, etc.). Use `risk_reason` for the compact
  table's "why" column (`no_strong_match`, `metadata_fields_mismatch`,
  `citation_identity_unresolved`, `available_evidence_does_not_confirm_claim`,
  etc.). Use `suggested_fix.kind` and `suggested_fix.action` for the compact
  "next step" column, and obey `suggested_fix.requires_user_confirmation`
  before editing citations or claims. At batch level, use
  `review_summary.suggested_fix_summary.confirmation_required_indexes`,
  `no_confirmation_required_indexes`, and `auto_apply_allowed=false` to decide
  what must be proposed to the user; never silently apply suggested fixes. Treat
  `recommendation` as display text, not as the decision contract.
- For citation-audit and support-audit rows, read
  `source_metadata_missing_fields` and `source_metadata_confidence_effect`
  before presenting a compact table. Missing source fields mean incomplete
  source metadata, not fabrication or claim-support evidence.
- When input came from a Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text reference
  file, preserve `input_source_path`, `input_source_format`,
  `input_source_index`, and `input_source_locator` from results or
  `risk_ranking` rows. If `input_source_line_start` / `input_source_line_end`
  are present, show them as `path:line` or `path:start-end`. Use this as a
  compact "source item" column so users can find the original bibliography
  entry.
- For large MCP batches, pass `high_risk_only=true` when the user only wants
  risky items. Use `filtered.returned_indexes` and `filtered.omitted_indexes` to
  map filtered rows back to the original input list. Use
  `filtered.omitted_review_summary` to briefly say what was hidden by the filter
  including its `recommended_next_steps`, instead of implying omitted rows were
  unexamined.
- For support benchmark or release-readiness triage, prefer
  `python3 scripts/eval_support.py --split test --backend heuristic --quality-gate --review-queue-only`
  when the user wants the highest-risk support failures rather than a full
  report. Read `overall.macro_f1`, `overall.weighted_f1`,
  `overall.false_support_rate`, and `overall.abstention_rate` for the compact
  metric snapshot, then read `review_queue` and branch on
  `quality_gate.review_queue_case_ids` and
  `quality_gate.critical_review_case_ids`. Also read
  top-level `acceptance_guard` (or
  `false_support_analysis.acceptance_guard` in older compact payloads) before
  saying a support backend is acceptable. If
  `false_support_analysis.false_support_case_ids` is non-empty, those are strong
  `supported` overcalls and should block acceptance; if
  `false_support_analysis.weak_false_support_case_ids` is non-empty, those are
  weak support overcalls requiring review. Use
  `false_support_analysis.high_risk_overcall_case_ids` to build the first
  compact review queue because it includes high-risk weak overcalls as well as
  release-blocking supported overcalls.
  If
  `acceptance_guard.ok_to_accept_supported` is false, treat
  `acceptance_guard.block_acceptance_case_ids` as release-blocking supported
  overcalls. If `review_before_accepting_case_ids` is non-empty, describe those
  weak support overcalls as review-required, not accepted support. Then read
  `false_support_analysis.review_plan` and branch on `review_plan.status`:
  `blocked` means release-blocking supported overcalls, `review_required`
  means weak support overcalls need review before acceptance, and `clear` means
  continue while still reporting metrics. Use the phase ids
  `supported_overcall_blockers`, `weak_support_overcall_review`, and
  `highest_risk_slice_review` to name the next review queue. Then read
  `false_support_analysis.risk_slices` and
  `false_support_analysis.top_risk_slice` before summarizing support overcalls:
  prioritize `contradicted_overcalled`, `hard_negative_overcalled`, and
  `full_text_boundary_overcalled` ahead of lower-risk abstention or recall
  issues.
- When the user asks for human review, benchmark labeling, or adjudication of
  those failures, first run
  `python3 scripts/prepare_support_label_sidecar.py --audit` and branch on
  `review_plan.next_phase`. Use `review_plan.phases[*].recommended_packet_ids`
  and `command_template` when present so first review, second review,
  adjudication, and release-gate tightening follow the reproducible benchmark
  workflow. For quality-gate failures, generate a blinded annotation packet with
  `python3 scripts/prepare_support_label_sidecar.py --annotation-packet --from-review-queue --review-backend heuristic --split test`.
  Use `review_queue_rank` only as assignment priority; do not treat it as a
  label hint or expose hidden gold labels/model predictions. Archive
  `packet_id`, `packet_digest`, and `packet_summary` with the returned review
  evidence so merge/adjudication provenance points to the exact packet content.
  Tell reviewers to
  fill `annotation.evidence_scope_assessed` and
  `annotation.full_text_needed` for scope-sensitive cases so abstract-only,
  full-text-required, and mixed-evidence judgments remain auditable after merge
  or adjudication.
- For weak citation-set aggregation review, generate the policy-boundary packet
  with `--case-type weak_set_boundary --unreviewed-only`; these cases decide
  whether multiple individually weak citations stay tentative.
- For expected tool errors (`ok=false`), use `error.next_action` for branching,
  `error.retryable` for retry scheduling, `error.category` for compact grouping,
  and `error.recovery` as the concise next-step instruction instead of
  paraphrasing `error.message`.
- For MCP batch shape errors, prefer `error.details.field`,
  `error.details.expected`, `error.details.received`, and 1-based
  `error.details.index` / `error.details.citation_index` for repair guidance.
  Do not quote raw validation prose when structured details are available.
- For claim-support checks, mention `evidence_scope` when it is not `full_text`.
  Treat `abstract`, `metadata`, `metadata_snippet`, `title`, `mixed`, and `none`
  as limited evidence scopes. Treat `mixed_with_full_text` as partly full-text,
  not as wholly full-text support.
- If status reported heuristic-only support mode, label support results as weak
  and avoid wording that sounds final.
- If a support result includes `model_failure_details`, mention that deep model
  scoring failed or timed out and treat the verdict as degraded/fallback
  evidence. Do not treat model failure as evidence for or against the claim.
- If a matched citation record includes `metadata.evidence_harvest_failures`
  with `stage=remote_evidence`, say that optional publisher/DOI landing-page
  snippet harvesting failed while metadata resolution still succeeded. Do not
  turn this into `source_unavailable`, `not_found`, or a fabrication claim.
- Sort or summarize by risk first: `contradicted`, `not_found`,
  `metadata_mismatch`, `ambiguous`, `insufficient_evidence`,
  `weakly_supported`, then `verified` / `supported`.
- For claim-support output, prioritize any item with
  `counterevidence_review=true`. Treat `counterevidence_reason=contradicted` as
  active evidence against the claim; treat other reasons as a review request, not
  as proof that counter-evidence was found.
- If you call `search_counterevidence_tool`, show candidates separately from the
  support verdict and label them as "possible counter-evidence to review"; branch
  on `next_action=review_counterevidence_leads`, not on candidate prose.
  `signal=source_outage_safety_cue` means the lead may help rebut unsafe
  source-outage-to-fabrication wording, including Chinese "源不可达/未找到证明伪造"
  claims; it is still a review lead, not a verdict.
- For `check_claim_support_set_tool`, mention `support_mode` when it is not
  `single_strong_support`. In particular, `multiple_weak_support` means several
  citations are related or partial; it is still tentative, not full support.
  Read `support_mode_details.decision`, `support_mode_details.policy`,
  `support_mode_details.supported_indexes`,
  `support_mode_details.weakly_supported_indexes`, and
  `support_mode_details.contradicted_indexes` for machine-readable aggregation
  reasons. Use `evidence_scopes`, `evidence_source_names`, and
  `evidence_source_fields` to summarize set-level provenance without expanding
  every child result.
- Always include a next step. Good next steps include: add DOI/arXiv id, confirm
  venue/year, inspect full text, replace citation, weaken claim, or keep as-is.

## Pre-response Safety Checklist

Before sending audit results, check these points:

- No silent edits: any changed citation, claim wording, or bibliography entry is
  a proposed fix and waits for user confirmation.
- No fabrication overclaim: `not_found`, `source_unavailable`, `timeout`, sparse
  metadata, missing full-text files, and counter-evidence leads are never stated
  as proof that a citation is fake.
- Scope is explicit: abstract/title/metadata support is not described as
  full-text support; `mixed_with_full_text` is described as partial full-text
  evidence.
- Traceability is preserved: include `sources_checked`, source-health caveats,
  original indexes, `input_source_locator`, and source line ranges when they are
  present.
- Next action is machine-readable: prefer `next_action`, `error.next_action`,
  `error.retryable`, `error.category`, `review_summary.triage_plan.next_action`,
  and `suggested_fix.kind` over natural-language guesses.

## Response template

For multi-item audits, prefer this order:

1. One-sentence bottom line: say how many items are high-risk, whether confidence
   was degraded by source/model failures, and whether any `supported` result is
   limited to abstract/title/metadata evidence.
2. Review queue summary from `review_summary.action_queues`, preferably ordered
   by `review_summary.recommended_next_steps.steps`, using original item indexes
   and preserving the provided priority order. Include `source_retry_indexes`
   separately from `rewrite_or_replace_indexes`; source retry is inconclusive,
   not evidence that a citation is fabricated.
3. Compact risk table sorted by risk, with columns:
   `index`, `source item`, `citation/claim`, `verdict`, `risk`, `next_action`,
   `evidence source`, `why`, `next step`. Fill `source item` from
   `input_source_path` plus `input_source_line_start` / `input_source_line_end`
   when available, else `input_source_locator`. Use `evidence_source_name` for
   the evidence source column when present, falling back to
   `evidence_source_field` only for older payloads. Keep `why` short and reserve
   longer explanations for the riskiest rows.
4. If `high_risk_only=true`, explicitly say the response is filtered and cite
   `filtered.returned_indexes` / `filtered.omitted_indexes` so the user can map
   results back to the original batch. If `filtered.omitted_review_summary` is
   present, summarize any omitted recommended next steps in one sentence.
5. End with the safest next action: add identifiers, retry/check source health,
   inspect full text, weaken the claim, replace the citation, or keep as-is.

Template:

```text
Bottom line: CiteGuard found {high_risk_count} high-risk item(s). {confidence_note}

Review queues:
- rewrite/replace: {rewrite_or_replace_indexes}
- resolve identifier: {identity_resolution_indexes}
- metadata review: {metadata_review_indexes}
- evidence/full-text review: {evidence_review_indexes}
- retry/check source health: {source_retry_indexes}
- safe to keep: {safe_to_keep_indexes}

| index | source item | citation/claim | verdict | risk | next_action | evidence source | why | next step |
|---|---|---|---|---|---|---|---|---|
| 2 | `examples/references.md:6` | ... | `not_found` | high | `resolve_identifier_or_replace` | `none` | no strong match in checked sources | ask for DOI/arXiv id or replace |

Scope / limitations: {source_health_or_evidence_scope_note}
```

Do not fill empty queues with reassuring prose. If every row is low-risk, say
that directly and still mention checked sources and evidence scope.

For source-health limitations, fill `{source_health_or_evidence_scope_note}` from
`source_health.summary.confidence_effect` and `source_health.summary.interpretation`,
not from prose explanations. For example:
`source_health.summary.confidence_effect=partial_source_limited;
interpretation=source_outage_lowers_confidence_not_fabrication_evidence`.

## Scenario routing

Use this quick routing table before choosing a tool:

| user situation | tool path | output emphasis |
|---|---|---|
| User pasted a bibliography, reference list, Markdown references, LaTeX `\bibitem`, a `.tex` file with local `\bibliography{refs}` / `\addbibresource{refs.bib}`, or Word-style references | Extract candidates if needed, then `audit_citations_tool` | Risk-sorted existence/metadata table; do not rewrite references silently |
| User is writing related work and asks for citations you generated | `verify_citation_tool` for each proposed source before presenting it | Only show verified or clearly caveated citations; ask for identifiers when ambiguous |
| User gives a claim with one cited paper | `check_claim_support_tool` after/with citation fields | Mention `evidence_scope`; never upgrade abstract/title evidence to full-text support |
| User supplies a lawful excerpt or local full-text file for a claim | `check_claim_support_tool` / `audit_claim_support_tool` with `full_text` or `full_text_file` | Report `evidence_scope=full_text` only when returned; identify user-provided evidence and keep paywall boundaries explicit |
| User gives one claim backed by several papers | `check_claim_support_set_tool` or one `audit_claim_support_tool` item with `citations` | Preserve per-citation verdicts and aggregate risk; multiple weak sources remain tentative |
| User gives one claim plus a Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text reference file or pasted reference list | Extract candidates, or run `citeguard support-audit refs.md --claim "..."` when using the CLI; `.tex` inputs can follow local `.bib` bibliography links | Apply the same claim to every extracted citation; sort by support risk and keep unresolved citations inconclusive |
| User gives many claim/citation rows | `audit_claim_support_tool` | Start with `review_summary.action_queues`, then compact risk table |
| User asks for support benchmark or release-readiness triage | `scripts/prepare_support_label_sidecar.py --audit`, then `scripts/eval_support.py --review-queue-only` when model-error triage is needed | Start with `review_plan.next_phase` for label workflow and `false_support_analysis.review_plan.status` / phase ids for model overcall triage; call out macro/weighted F1, `acceptance_guard`, `false_support_analysis.top_risk_slice`, and support-overcall `risk_slices` |
| User asks whether multiple weak citations jointly support a claim | `scripts/prepare_support_label_sidecar.py --annotation-packet --case-type weak_set_boundary --unreviewed-only` | Assign policy-boundary review; do not present multiple weak citations as full support |
| Result is `ambiguous` | Ask for DOI/arXiv id, venue, full authors, or exact reference text | Do not choose a match silently |
| Result is `metadata_mismatch` | Show `field_diffs` and `suggested_citation` | Ask before editing the bibliography |
| Result is `not_found`, `source_unavailable`, or `timeout` | Use `next_action` / `recovery_code`; optionally run one source-health probe | Say inconclusive/high-risk, not fake or fabricated |

## Detailed examples

For concrete MCP call payloads and wording examples, read
[`references/examples.md`](references/examples.md) when:

- you need an exact JSON shape for a less common tool call,
- you are unsure how to phrase ambiguous, not-found, source-outage, or
  metadata-mismatch results, or
- you need a support benchmark / release-readiness metric summary, or
- you want a compact result-table example to mirror.
