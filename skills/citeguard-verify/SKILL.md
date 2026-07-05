---
name: citeguard-verify
description: Use when checking, auditing, or fixing citations in scientific or technical writing — verifying that cited papers actually exist, their metadata (title, authors, year, venue, DOI) is correct, and cited papers support nearby claims when needed. Triggers when the user is writing related work / a literature review / a bibliography, pastes references, or asks to "check my citations".
---

# CiteGuard Citation Verification

You verify citations against real scholarly sources before trusting them. You do NOT invent or guess whether a paper exists — you call the CiteGuard MCP tools.

## Install / connect

Install CiteGuard with the MCP extra:

```bash
python -m pip install -e ".[mcp]"
```

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
- A pasted Markdown/LaTeX/Word-style reference section or JSON/JSONL citation
  list.

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
   claim-support checks; existence and metadata checks can still run. If remote
   evidence harvesting is disabled, support checks still use title/abstract
   evidence; suggest enabling `CITEGUARD_REMOTE_EVIDENCE=1` only when the user
   wants slower, deeper landing-page snippet harvesting.
   To diagnose source outages, call `citeguard_status_tool` with
   `check_sources=true` and, when useful, a project-specific `health_query`.
   Do not run live probes repeatedly during normal citation checks. In the
   returned `source_health.summary`, branch on `failure_kind_counts` and
   `failure_kind_sources` to distinguish timeouts, rate limits, HTTP errors, and
   network failures without parsing prose.
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

Notes: deep mode needs models (downloaded on first use; slow). If `engine` is
`"heuristic"`, say the result is weak (deep models not loaded), and never report
`contradicted` in that mode. For non-English claims, multilingual models can be
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
  batch size, or configuring credentials. In every case, say source health
  degraded confidence but is not evidence of fabrication.
- Use `next_action` when present for workflow branching instead of parsing
  `explanation`; use `recovery_code` as the underlying reason when it is present
  (`ambiguous_citation`, `timeout`, or `source_unavailable`).
- In batch `audit_citations_tool` and `audit_claim_support_tool` results, read
  `review_summary` first for full-batch high/medium/low risk counts,
  next-action counts, top risk indexes, and `action_queues`. Use
  `rewrite_or_replace_indexes`, `identity_resolution_indexes`,
  `evidence_review_indexes`, `source_retry_indexes`, and
  `safe_to_keep_indexes` to make a compact review queue before expanding
  individual `risk_ranking` rows.
- In batch `risk_ranking`, also use `next_action` as the machine-readable action
  (`review_metadata`, `resolve_identifier_or_replace`,
  `disambiguate_identifier`, `retry_or_check_source_health`,
  `review_counterevidence_leads`, `inspect_full_text_or_find_stronger_citation`,
  `rewrite_or_replace_evidence`, etc.). Treat `recommendation` as display text,
  not as the decision contract.
- For large MCP batches, pass `high_risk_only=true` when the user only wants
  risky items. Use `filtered.returned_indexes` and `filtered.omitted_indexes` to
  map filtered rows back to the original input list. Use
  `filtered.omitted_review_summary` to briefly say what was hidden by the filter
  instead of implying omitted rows were unexamined.
- For support benchmark or release-readiness triage, prefer
  `python3 scripts/eval_support.py --split test --backend heuristic --quality-gate --review-queue-only`
  when the user wants the highest-risk support failures rather than a full
  report. Read `review_queue` first, then branch on
  `quality_gate.review_queue_case_ids` and
  `quality_gate.critical_review_case_ids`. Also read
  `false_support_analysis.risk_slices` and
  `false_support_analysis.top_risk_slice` before summarizing support overcalls:
  prioritize `contradicted_overcalled`, `hard_negative_overcalled`, and
  `full_text_boundary_overcalled` ahead of lower-risk abstention or recall
  issues.
- When the user asks for human review, benchmark labeling, or adjudication of
  those failures, generate a blinded annotation packet with
  `python3 scripts/prepare_support_label_sidecar.py --annotation-packet --from-review-queue --review-backend heuristic --split test`.
  Use `review_queue_rank` only as assignment priority; do not treat it as a
  label hint or expose hidden gold labels/model predictions.
- For expected tool errors (`ok=false`), use `error.next_action` for branching
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
- Always include a next step. Good next steps include: add DOI/arXiv id, confirm
  venue/year, inspect full text, replace citation, weaken claim, or keep as-is.

## Response template

For multi-item audits, prefer this order:

1. One-sentence bottom line: say how many items are high-risk, whether confidence
   was degraded by source/model failures, and whether any `supported` result is
   limited to abstract/title/metadata evidence.
2. Review queue summary from `review_summary.action_queues`: list only non-empty
   queues, using original item indexes. Include `source_retry_indexes` separately
   from `rewrite_or_replace_indexes`; source retry is inconclusive, not evidence
   that a citation is fabricated.
3. Compact risk table sorted by risk, with columns:
   `index`, `citation/claim`, `verdict`, `risk`, `next_action`, `why`, `next step`.
   Keep `why` short and reserve longer explanations for the riskiest rows.
4. If `high_risk_only=true`, explicitly say the response is filtered and cite
   `filtered.returned_indexes` / `filtered.omitted_indexes` so the user can map
   results back to the original batch. If `filtered.omitted_review_summary` is
   present, summarize any omitted next-action queues in one sentence.
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

| index | citation/claim | verdict | risk | next_action | why | next step |
|---|---|---|---|---|---|---|
| 2 | ... | `not_found` | high | `resolve_identifier_or_replace` | no strong match in checked sources | ask for DOI/arXiv id or replace |

Scope / limitations: {source_health_or_evidence_scope_note}
```

Do not fill empty queues with reassuring prose. If every row is low-risk, say
that directly and still mention checked sources and evidence scope.

## Scenario routing

Use this quick routing table before choosing a tool:

| user situation | tool path | output emphasis |
|---|---|---|
| User pasted a bibliography, reference list, Markdown references, LaTeX `\bibitem`, or Word-style references | Extract candidates if needed, then `audit_citations_tool` | Risk-sorted existence/metadata table; do not rewrite references silently |
| User is writing related work and asks for citations you generated | `verify_citation_tool` for each proposed source before presenting it | Only show verified or clearly caveated citations; ask for identifiers when ambiguous |
| User gives a claim with one cited paper | `check_claim_support_tool` after/with citation fields | Mention `evidence_scope`; never upgrade abstract/title evidence to full-text support |
| User gives one claim backed by several papers | `check_claim_support_set_tool` or one `audit_claim_support_tool` item with `citations` | Preserve per-citation verdicts and aggregate risk; multiple weak sources remain tentative |
| User gives many claim/citation rows | `audit_claim_support_tool` | Start with `review_summary.action_queues`, then compact risk table |
| User asks for support benchmark or release-readiness triage | `scripts/eval_support.py --review-queue-only` | Start with `review_queue`, then call out `false_support_analysis.top_risk_slice` and support-overcall `risk_slices` |
| Result is `ambiguous` | Ask for DOI/arXiv id, venue, full authors, or exact reference text | Do not choose a match silently |
| Result is `metadata_mismatch` | Show `field_diffs` and `suggested_citation` | Ask before editing the bibliography |
| Result is `not_found`, `source_unavailable`, or `timeout` | Use `next_action` / `recovery_code`; optionally run one source-health probe | Say inconclusive/high-risk, not fake or fabricated |

## Detailed examples

For concrete MCP call payloads and wording examples, read
[`references/examples.md`](references/examples.md) when:

- you need an exact JSON shape for a less common tool call,
- you are unsure how to phrase ambiguous, not-found, source-outage, or
  metadata-mismatch results, or
- you want a compact result-table example to mirror.
