# CiteGuard Skill Examples

Use these examples when you need exact MCP payload shapes or safe wording for
edge cases. Keep the main `SKILL.md` workflow authoritative.

## Tool Examples

Single citation:

```json
{
  "tool": "verify_citation_tool",
  "arguments": {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani"],
    "year": 2017,
    "arxiv_id": "1706.03762"
  }
}
```

Source health probe:

```json
{
  "tool": "citeguard_status_tool",
  "arguments": {
    "check_sources": true,
    "health_query": "Attention Is All You Need"
  }
}
```

If `source_health.summary.degraded=true`, summarize `sources_available`,
`sources_failed`, `failure_kind_counts`, `failure_kind_sources`, and any
summary `retry_guidance=wait_before_retry`, `retry_after_seconds`, and
`retry_after_sources` values; then branch on
`source_health.summary.confidence_effect`,
`source_health.summary.interpretation`, and `source_health.summary.next_action`.

Source-health confidence contract:

```json
{
  "source_health": {
    "schema_version": 8,
    "mode": "live",
    "summary": {
      "sources_checked": ["openalex", "crossref"],
      "sources_available": ["crossref"],
      "sources_failed": ["openalex"],
      "failure_kind_counts": {"timeout": 1},
      "failure_kind_sources": {"timeout": ["openalex"]},
      "confidence_effect": "partial_source_limited",
      "interpretation": "source_outage_lowers_confidence_not_fabrication_evidence",
      "next_action": "retry_or_check_source_health"
    },
    "sources": [
      {
        "name": "openalex",
        "status": "unavailable",
        "next_action": "retry_or_check_source_health",
        "confidence_effect": "source_unavailable",
        "interpretation": "source_outage_lowers_confidence_not_fabrication_evidence",
        "recovery_code": "timeout",
        "retry_guidance": "retry_or_check_source_health"
      },
      {
        "name": "crossref",
        "status": "available",
        "next_action": "continue",
        "confidence_effect": "none",
        "interpretation": "source_health_ok",
        "recovery_code": "",
        "retry_guidance": "continue"
      }
    ]
  }
}
```

Safe wording: "OpenAlex timed out, while Crossref responded. This limits confidence and should trigger retry or source-health inspection; it is not evidence that the citation is fabricated."

Support model status:

```json
{
  "support_models": {
    "engine": "heuristic_fallback",
    "deep_models_available": false,
    "missing_dependencies": ["sentence_transformers", "torch", "transformers"],
    "next_action": "install_or_configure_dependency"
  }
}
```

Safe wording: "Existence and metadata checks can continue. Claim-support checks are degraded because deep support models are missing; install `citeguard[models]` (or `.[models]` from a source checkout) and run `python3 scripts/warmup_support_models.py` before relying on deep reranker/NLI judgments."

Batch citation audit:

```json
{
  "tool": "audit_citations_tool",
  "arguments": {
    "citations": [
      {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani"],
        "year": 2017,
        "arxiv_id": "1706.03762"
      },
      {
        "raw_text": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks. Journal of Imaginary Methods, 2024."
      }
    ]
  }
}
```

High-risk-only batch citation audit:

```json
{
  "tool": "audit_citations_tool",
  "arguments": {
    "high_risk_only": true,
    "citations": [
      {
        "title": "Attention Is All You Need",
        "arxiv_id": "1706.03762"
      },
      {
        "raw_text": "A Missing Paper About Citation Teleportation. Imaginary Proceedings, 2024."
      }
    ]
  }
}
```

When `high_risk_only=true`, use `filtered.returned_indexes`,
`filtered.omitted_indexes`, and `filtered.omitted_review_summary` to tell the
user which original rows are shown, which rows were hidden, and what review
queues or recommended next steps were omitted.

Claim support:

```json
{
  "tool": "check_claim_support_tool",
  "arguments": {
    "claim": "The Transformer relies entirely on attention mechanisms.",
    "title": "Attention Is All You Need",
    "arxiv_id": "1706.03762",
    "lang": "en"
  }
}
```

Claim support with a user-provided lawful full-text excerpt:

```json
{
  "tool": "check_claim_support_tool",
  "arguments": {
    "claim": "Sparse retrieval improves citation audit recall.",
    "title": "Citation Auditing with Metadata Checks",
    "full_text": [
      "The lawful full-text excerpt shows sparse retrieval improves citation audit recall."
    ],
    "lang": "en"
  }
}
```

Use `full_text` only for caller-provided lawful excerpts, local lawful files, or
open source-adapter evidence. If CiteGuard returns `evidence_scope=full_text`
with `evidence.source_field=user_full_text_excerpt_1`, say the support check used
the user's supplied excerpt. Do not fetch gated full text, bypass paywalls, or
upgrade abstract-only evidence to full-text support.

Claim support with a user-provided lawful local file:

```json
{
  "tool": "check_claim_support_tool",
  "arguments": {
    "claim": "Sparse retrieval improves citation audit recall.",
    "title": "Citation Auditing with Metadata Checks",
    "full_text_file": "/path/to/lawful-full-text-excerpt.txt",
    "lang": "en"
  }
}
```

If CiteGuard returns `evidence_scope=full_text` with
`evidence.source_field=user_full_text_file_1`, say the evidence came from the
user-provided local file. If the file is missing or unreadable and the result is
`ok=false` with `error.code=file_error`, use `error.details.field=full_text_file`,
`error.details.filename`, and `error.next_action=repair_input` to ask for a
readable local text/PDF file or a pasted lawful excerpt. Do not retry by
fetching remote or gated full text.

One claim, multiple citations:

```json
{
  "tool": "check_claim_support_set_tool",
  "arguments": {
    "claim": "Citation auditing should verify existence, metadata, and claim support.",
    "citations": [
      {"title": "GhostCite: A Large-Scale Analysis of Citation Validity"},
      {"raw_text": "Another citation string from the bibliography."}
    ],
    "lang": "en"
  }
}
```

One claim, multiple citations with one user-provided full-text file:

```json
{
  "tool": "check_claim_support_set_tool",
  "arguments": {
    "claim": "Sparse retrieval improves citation audit recall.",
    "citations": [
      {
        "title": "Citation Auditing with Metadata Checks",
        "full_text_file": "/path/to/lawful-full-text-excerpt.txt"
      },
      {
        "title": "A related abstract-only citation"
      }
    ],
    "lang": "en"
  }
}
```

Read `evidence_scopes`, `evidence_source_fields`, and
`support_mode_details.full_text_evidence_present` before presenting the set as
full-text-supported. If only one citation has `user_full_text_file_1`, say that
the set includes one user-provided full-text evidence file plus any abstract or
metadata evidence from the remaining citations. Do not imply that every cited
paper was checked at full-text scope.

Nested claim-support audit with a full-text file:

```json
{
  "tool": "audit_claim_support_tool",
  "arguments": {
    "items": [
      {
        "claim": "Sparse retrieval improves citation audit recall.",
        "citations": [
          {
            "title": "Citation Auditing with Metadata Checks",
            "full_text_file": "/path/to/lawful-full-text-excerpt.txt"
          }
        ]
      }
    ]
  }
}
```

For nested citation-set audits, preserve both the outer item index and any
`error.details.citation_index` when repairing input. This lets the user find the
exact citation object whose `full_text_file` path needs repair.

One claim against an extracted reference file, using the CLI fallback when the
agent has local project access:

```bash
citeguard support-audit examples/references.md \
  --claim "The Transformer relies entirely on attention mechanisms." \
  --compact
```

Use this when the user supplies one claim plus a Markdown/LaTeX/BibTeX/BBL/DOCX
or plain-text reference list. The command applies the same claim to every extracted
citation candidate. Sort the response by `risk_ranking`, keep
`insufficient_evidence` rows tentative, and do not call unresolved references
fake.

LaTeX project with an external local `.bib` file:

```bash
citeguard extract paper.tex --compact
citeguard audit paper.tex --compact
```

When `paper.tex` contains `\bibliography{refs}` or
`\addbibresource{refs.bib}`, CiteGuard follows the local `.bib` file. Report
the returned `source_path` and `source_locator`; they should point to the
referenced `.bib` citation item, not just the `.tex` manuscript.

Compiled LaTeX bibliography (`.bbl`) fallback:

```bash
citeguard extract paper.bbl --compact
citeguard audit paper.bbl --compact
```

Use this when the project has a generated `.bbl` but not the original `.bib`.
Report `source_format=bbl`, `source_path`, and `source_locator` so the user can
find the compiled `\bibitem`; do not treat the `.bbl` as proof that the paper
exists.

When the user asks for a more skeptical review pass, attach reference-file
counter-evidence review leads without treating them as contradiction verdicts:

```bash
citeguard support-audit examples/references.md \
  --claim "The Transformer relies entirely on attention mechanisms." \
  --with-counterevidence \
  --compact
```

Ambiguous citation:

```json
{
  "tool": "verify_citation_tool",
  "arguments": {
    "title": "Deep Learning",
    "year": 2015
  }
}
```

If this returns `ambiguous`, do not choose one match. Ask for a DOI, arXiv id,
venue, complete author list, or exact reference text.

Metadata mismatch:

```json
{
  "tool": "verify_citation_tool",
  "arguments": {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani"],
    "year": 2018,
    "arxiv_id": "1706.03762"
  }
}
```

If this returns `metadata_mismatch`, show `field_diffs`, quote the
`suggested_citation` if present, and ask before editing the user's bibliography.

Claim/citation batch:

```json
{
  "tool": "audit_claim_support_tool",
  "arguments": {
    "items": [
      {
        "claim": "The Transformer relies entirely on attention mechanisms.",
        "title": "Attention Is All You Need",
        "arxiv_id": "1706.03762"
      },
      {
        "claim": "Citation auditing should verify existence, metadata, and claim support.",
        "citations": [
          {"title": "A citation auditing paper"},
          {"title": "A second related paper"}
        ]
      }
    ],
    "lang": "en"
  }
}
```

High-risk claim-support audit with counter-evidence leads:

```json
{
  "tool": "audit_claim_support_tool",
  "arguments": {
    "include_counterevidence": true,
    "counterevidence_top_k": 1,
    "high_risk_only": true,
    "items": [
      {
        "claim": "The Transformer relies entirely on attention mechanisms.",
        "title": "Attention Is All You Need",
        "arxiv_id": "1706.03762"
      },
      {
        "claim": "Method M improves task T.",
        "title": "A Fixture Paper That Does Not Exist"
      }
    ]
  }
}
```

When `include_counterevidence=true` and `high_risk_only=true` are combined,
show `filtered.returned_indexes` and `filtered.omitted_indexes` so the user can
map the compact result back to the original batch. Also summarize
`filtered.omitted_review_summary`; hidden rows were checked, not skipped. If a
returned row has `counterevidence`, call it a review lead to inspect, not a contradiction verdict
or permission to silently rewrite the claim.

Malformed batch shape repair:

```json
{
  "tool": "audit_claim_support_tool",
  "arguments": {
    "items": "not a list"
  }
}
```

If this returns `ok=false` with `error.code=invalid_input`,
`error.details.field=items`, `error.details.expected=list`, and
`error.details.received=str`, plus `error.retryable=false` and
`error.category=input_repair`, repair the MCP call by rebuilding `items` as an
array of claim/citation objects. Do not ask the user to interpret validation
prose when `error.details` gives a machine-readable repair path.

Full-text file error repair:

```json
{
  "ok": false,
  "schema_version": 1,
  "error": {
    "code": "file_error",
    "message": "Could not read full-text evidence file '/path/to/missing.txt'",
    "details": {
      "tool": "audit_claim_support_tool",
      "index": 1,
      "citation_index": 2,
      "field": "full_text_file",
      "filename": "/path/to/missing.txt",
      "errno": 2
    },
    "recovery": "Check the path and permissions.",
    "next_action": "repair_input",
    "retryable": false,
    "category": "input_repair"
  }
}
```

Safe wording: "The support audit could not read the local full-text evidence
file for item 1, citation 2. The OS reported `errno=2`, so the path likely does
not exist. Please provide a readable local text/PDF file or paste a lawful
excerpt; I will not fetch gated full text or infer full-text support from the
missing file."

Prefer `error.retryable` and `error.category` for retry scheduling and compact
UI grouping. For example, `error.retryable=false` and
`error.category=input_repair` means repair the input rather than retrying the
same call; `source_limited` is the category for retryable source outages and
timeouts.

Counter-evidence lead search:

```json
{
  "tool": "search_counterevidence_tool",
  "arguments": {
    "claim": "Method M improves task T.",
    "top_k": 5
  }
}
```

When the report has `next_action=review_counterevidence_leads`, present the
candidates as possible counter-evidence to inspect. Do not treat the retrieval
result as a contradiction verdict.

Support eval review queue:

```bash
python3 scripts/eval_support.py --split test --backend heuristic --quality-gate --review-queue-only
```

When this exits non-zero, read `quality_gate.review_queue_case_ids` before
expanding full report rows. First summarize `overall.macro_f1`,
`overall.weighted_f1`, `overall.false_support_rate`, and
`overall.abstention_rate` as the compact metric snapshot; do not use accuracy alone.
Also read top-level `acceptance_guard` before summarizing model
acceptability: `block_acceptance_case_ids` are strong
`supported` overcalls and block acceptance, while
`review_before_accepting_case_ids` are weak support overcalls that require
human or stronger-model review before being treated as support. Also read
`false_support_analysis.false_support_case_ids`,
`false_support_analysis.weak_false_support_case_ids`, and
`false_support_analysis.high_risk_overcall_case_ids` before writing the compact
review queue; the high-risk list includes review-required weak overcalls as well
as release-blocking supported overcalls. Then read
`false_support_analysis.review_plan.status` and
`false_support_analysis.review_plan.phases[*].id` before deciding whether the
queue is blocked, review-required, or clear. Then read
`false_support_analysis.top_risk_slice` and
`false_support_analysis.risk_slices` before summarizing support overcalls.
Present `review_queue` in order, but call out the top supported-overcall slice
first when it is present; do not treat heuristic missed contradictions as final
scientific judgments.

Compact false-support triage:

```json
{
  "overall": {
    "accuracy": 0.5263,
    "macro_f1": 0.2875,
    "weighted_f1": 0.3763,
    "false_support_rate": 0.0,
    "abstention_rate": 0.7895
  },
  "acceptance_guard": {
    "ok_to_accept_supported": true,
    "block_acceptance_case_ids": [],
    "review_before_accepting_case_ids": ["s39", "s48"],
    "next_action": "review_before_accepting_weak_support",
    "policy": "supported_overcalls_block_acceptance; weak_overcalls_require_review"
  },
  "false_support_analysis": {
    "total_overcall_count": 2,
    "false_support_case_ids": [],
    "weak_false_support_case_ids": ["s39", "s48"],
    "high_risk_overcall_case_ids": ["s39", "s48"],
    "acceptance_guard": {
      "ok_to_accept_supported": true,
      "block_acceptance_case_ids": [],
      "review_before_accepting_case_ids": ["s39", "s48"]
    },
    "risk_slices": [
      {
        "id": "contradicted_overcalled",
        "severity": "critical",
        "recommended_action": "inspect_contradiction_before_accepting_support",
        "case_ids": ["s39", "s48"]
      }
    ],
    "top_risk_slice": {
      "id": "contradicted_overcalled",
      "case_ids": ["s39", "s48"]
    },
    "review_plan": {
      "schema_version": 1,
      "status": "review_required",
      "next_action": "review_weak_support_overcalls_before_acceptance",
      "block_acceptance_case_ids": [],
      "review_before_accepting_case_ids": ["s39", "s48"],
      "top_risk_slice_id": "contradicted_overcalled",
      "top_risk_slice_case_ids": ["s39", "s48"],
      "phases": [
        {
          "id": "supported_overcall_blockers",
          "status": "clear",
          "case_ids": [],
          "next_action": "inspect_or_relabel_before_release"
        },
        {
          "id": "weak_support_overcall_review",
          "status": "review_required",
          "case_ids": ["s39", "s48"],
          "next_action": "review_before_accepting_supported"
        },
        {
          "id": "highest_risk_slice_review",
          "status": "review_required",
          "case_ids": ["s39", "s48"],
          "next_action": "triage_top_false_support_slice"
        }
      ],
      "policy": "supported_overcalls_block_release; weak_overcalls_require_review; top_risk_slice_sets_triage_order"
    }
  }
}
```

Safe wording:

> The heuristic support baseline has
> `false_support_analysis.review_plan.status=review_required`: there are no
> strong `supported_overcall_blockers` in this test-split snapshot, but `s39`
> and `s48` are in `weak_support_overcall_review` and still need human or
> stronger-model review before being treated as support. Macro F1 is 0.2875 and
> weighted F1 is 0.3763, so inspect the evidence before accepting this backend's
> supported verdicts. Treat this as review-required triage, not proof that either
> source is fabricated.

If a future snapshot has `review_plan.status=blocked`, treat that as
release-blocking triage and inspect `supported_overcall_blockers` first.

Baseline comparison rows and manifests expose the same review-plan fields in
flat form. When comparing backends, rank any backend with
`false_support_review_plan_status=blocked` ahead of merely low-score rows, and
read manifest fields such as
`false_support_top_overcall_review_plan_status`,
`false_support_top_overcall_review_plan_next_action`, and
`false_support_top_overcall_review_plan_phase_ids` before calling a backend
release-ready:

```json
{
  "backend": "heuristic",
  "false_support_review_plan_status": "review_required",
  "false_support_review_plan_next_action": "review_weak_support_overcalls_before_acceptance",
  "false_support_review_plan_phase_ids": [
    "supported_overcall_blockers",
    "weak_support_overcall_review",
    "highest_risk_slice_review"
  ],
  "false_support_review_plan_block_case_ids": [],
  "false_support_review_plan_review_case_ids": ["s39", "s48"]
}
```

Turn that queue into a blinded human annotation packet:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet \
  --from-review-queue \
  --review-backend heuristic \
  --split test \
  --output experiments/support-label-packet-review-queue-test.json \
  --instructions-output experiments/support-label-packet-review-queue-test-instructions.md
```

Use `review_queue_rank` as assignment priority only; it is not a label hint and
does not expose gold labels or backend predictions.
Ask reviewers to fill the packet's scope provenance fields when they label
support boundaries:

```json
{
  "annotation": {
    "annotator_id": "reviewer-a",
    "annotator_label": "insufficient_evidence",
    "rationale": "The abstract does not state the claimed subgroup method.",
    "confidence": "medium",
    "evidence_scope_assessed": "abstract",
    "full_text_needed": "yes",
    "notes": "Needs lawful full-text methods inspection."
  }
}
```

Safe wording:

> This annotation should record `annotation.evidence_scope_assessed=abstract`
> and `annotation.full_text_needed=yes`, so the merged sidecar preserves that
> the label is an abstract-level judgment and not a final full-text conclusion.

Review-plan audit for benchmark labeling:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --audit
```

Compact response example:

```text
Bottom line: the benchmark labels are not human-reviewed yet. The next
machine-readable phase is `review_plan.next_phase=first_review_high_risk`.

Review plan:
- first review: 37 candidate case(s), including high-risk and policy-boundary rows
- second review: waiting for first-review packets
- adjudication: waiting for dual annotation
- release gates: blocked until human-reviewed coverage is nonzero and
  high-risk/support-disagreement gates can be raised

Use `recommended_packets` for assignment commands:
- `high_risk_unreviewed_balanced`
- `full_text_required_unreviewed`
- `policy_boundary_unreviewed`

Do not describe this seed set as a human-reviewed benchmark.
```

Use `false_support_analysis.review_plan.recommended_annotation_packets` first,
then `review_plan.phases[*].annotation_packet.command_template` or
`review_plan.phases[*].command_template` for adjudication and release-gate
tightening instead of improvising commands. Treat those packets as review
assignments only: they do not change labels, silently accept supported
predictions, or make the benchmark publication-ready. If
`review_plan.status=blocked`, say exactly which phase is next.

Generate a full-text-boundary packet for claims that abstract-level evidence
cannot safely resolve:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet \
  --case-type full_text_required \
  --unreviewed-only \
  --limit 10 \
  --output experiments/support-label-packet-full-text-required-unreviewed.json \
  --instructions-output experiments/support-label-packet-full-text-required-unreviewed-instructions.md
```

Safe wording:

> These cases need lawful full-text evidence before making a final support
> claim. Keep abstract-only results as insufficient evidence until full-text boundary review is complete.

Generate a policy-boundary packet for weak citation-set aggregation cases:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet \
  --case-type weak_set_boundary \
  --unreviewed-only \
  --limit 10 \
  --output experiments/support-label-packet-policy-boundary-unreviewed.json \
  --instructions-output experiments/support-label-packet-policy-boundary-unreviewed-instructions.md
```

Safe wording:

> These citation-set cases test whether several individually weak citations
> remain tentative instead of being promoted to full claim support. Assign human
> policy-boundary review before claiming multi-citation support readiness.

Support-set aggregation detail:

```json
{
  "support_mode": "multiple_weak_support",
  "support_mode_details": {
    "decision": "multiple_weak_citations_remain_tentative",
    "policy": "contradictions_dominate; multiple_weak_citations_remain_tentative; no_unstated_multi_hop_or_full_text_support",
    "weakly_supported_indexes": [0, 1],
    "supported_indexes": [],
    "contradicted_indexes": [],
    "full_text_evidence_present": false
  }
}
```

Safe wording:

> The cited papers are related, but `support_mode_details.decision` says this is
> still tentative. Do not turn multiple weak citations into strong support
> without lawful full-text evidence or a stronger citation.

Suggested compact result table:

| item | verdict | risk | source metadata | next step |
|---|---|---|---|---|
| Attention Is All You Need | `verified` | low | complete enough | keep citation |
| Title-only same-name record | `metadata_mismatch` | medium | missing venue/year | confirm DOI/arXiv id before editing |
| Sparse live-source record | `verified` | low | missing abstract/url | keep citation, mention incomplete source metadata |
| Unknown reference | `not_found` | high | no matched record | ask user for source or replacement |
| Claim support check | `insufficient_evidence` | medium | abstract only | inspect full text or rewrite claim |

Filtered high-risk response example:

```text
Bottom line: CiteGuard found 1 high-risk item. Two lower-risk rows were checked
and hidden by `high_risk_only=true`.

Review queues:
- rewrite/replace: [2]
- resolve identifier: [2]
- metadata review: []
- evidence/full-text review: []
- retry/check source health: []
- safe to keep: [1]

Triage plan: `review_summary.triage_plan.status=review_required`;
`review_required_indexes=[2]`; policy includes
`source_retry_is_inconclusive_not_fabrication`.

| index | source item | citation/claim | verdict | risk | next_action | evidence source | why | next step |
|---|---|---|---|---|---|---|---|---|
| 2 | `examples/references.md:6` | Unknown reference | `not_found` | high | `resolve_identifier_or_replace` | `none` | `risk_reason=no_strong_match` | `suggested_fix.kind=add_identifier_or_replace` |

Filtered rows: `filtered.returned_indexes=[2]`;
`filtered.omitted_indexes=[1, 3]`. The hidden rows are summarized in
`filtered.omitted_review_summary`; they were examined, not skipped.
The `source item` column comes from `input_source_path` plus
`input_source_line_start` / `input_source_line_end` when available; otherwise
use `input_source_locator`.

Scope / limitations: `not_found` means CiteGuard could not verify the reference
in the checked sources. It is high-risk, not proof of fabrication.
```

Ambiguous compact response example:

```text
Bottom line: CiteGuard found 1 ambiguous citation. I should not choose one
match silently because several records are plausible.

| index | source item | citation/claim | verdict | risk | next_action | evidence source | why | next step |
|---|---|---|---|---|---|---|---|---|
| 4 | `paper.tex:42` | Deep Learning (2015) | `ambiguous` | medium | `disambiguate_identifier` | `openalex,crossref` | multiple plausible matches | ask for DOI/arXiv id, venue, full authors, or exact reference text |

Scope / limitations: ambiguity means CiteGuard found multiple plausible
matches, not that any one record is correct. Do not choose one match without
user confirmation.
```

Metadata mismatch compact response example:

```text
Bottom line: CiteGuard found 1 metadata mismatch. The paper appears to exist,
but the bibliography fields need user confirmation before editing.

| index | source item | citation/claim | verdict | risk | next_action | evidence source | why | next step |
|---|---|---|---|---|---|---|---|---|
| 7 | `refs.bib:@vaswani2018attention` | Attention Is All You Need | `metadata_mismatch` | medium | `review_metadata` | `crossref` | `risk_reason=metadata_fields_mismatch`; `field_diffs=year,venue` | show `suggested_citation`; apply only after `suggested_fix.requires_user_confirmation=true` is accepted |

Scope / limitations: `metadata_mismatch` is a review request, not permission to
silently rewrite the user's bibliography. If the original citation lacks a
DOI/arXiv id, ask the user to confirm the identifier before changing year,
venue, or author fields.
```

## Result Wording Examples

Metadata mismatch:

> CiteGuard found a likely real paper, but the year differs from your reference:
> your citation says 2021, the matched record says 2020. Because there is no DOI
> or arXiv id, treat this as a possible mismatch and confirm the identifier
> before editing.

Ambiguous citation:

> CiteGuard found multiple plausible matches for this title. I should not choose
> one silently; please provide a DOI, arXiv id, or venue/year confirmation.

Not found:

> CiteGuard could not verify this reference in the checked sources. That makes it
> high-risk, but it is not proof that the paper is fabricated.

Source outage:

> CiteGuard could not reach one or more sources, so this result is inconclusive.
> I will not treat source failure as evidence that the citation is fake. If
> `outage_limited=true`, I should retry or ask for stronger identifiers.

Rate-limited source health:

> CiteGuard reached the status probe, but Semantic Scholar is rate-limited
> (`failure_kind_counts.rate_limited=1`,
> `retry_guidance=wait_before_retry`, `retry_after_seconds=2.0`). I should wait,
> reduce batch size, or configure credentials; this does not make any unresolved
> citation fake.

Remote evidence harvest failure:

> CiteGuard resolved the citation metadata, but optional publisher/DOI landing
> page snippet harvesting failed (`metadata.evidence_harvest_failures`,
> `stage=remote_evidence`). I can keep the metadata result, but I should not
> claim full-text or landing-page support from the missing snippet.

Claim support with limited scope:

> The citation exists, but the support check only used abstract-level evidence.
> The abstract does not confirm the stronger claim; inspect the full text or
> weaken the sentence.

Contradiction:

> CiteGuard found evidence that contradicts the claim. Treat this as high-risk:
> revise the claim, replace the citation, or inspect the source manually before
> keeping it.
