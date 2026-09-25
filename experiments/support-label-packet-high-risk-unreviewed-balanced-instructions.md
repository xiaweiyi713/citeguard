# CiteGuard Support Annotation Instructions

- Dataset: `support_eval.json`
- Packet type: `support_label_annotation_packet`
- Packet id: `support-packet-aff8707c70f09028`
- Case count: `2`
- Filters: `{"limit_per_case_type": 1, "limit_per_evidence_scope": 1, "limit_per_language": 1, "priority": ["high"], "unreviewed_only": true}`
- Review protocol: `{"adjudication_required_on_disagreement": true, "benchmark_target_annotator_count": 2, "cases_already_single_annotated": 0, "independent_labeling_required": true, "merge_policy": "single_annotator_until_second_review; dual_annotator_agreed_or_adjudicated_before_benchmark_claims", "packet_role": "first_review", "packet_target_annotator_count": 1, "reviewer_must_not_see_hidden_labels": true, "schema_version": 1, "second_review_required_after_first_review": true}`
- Packet summary: `{"case_count_by_case_type": {"contradiction": 1, "hard_negative": 1}, "case_count_by_evidence_scope": {"abstract": 1, "metadata_snippet": 1}, "case_count_by_language": {"en": 1, "zh": 1}, "case_count_by_priority": {"high": 2}, "case_count_by_review_status": {"not_human_reviewed": 2}, "case_count_by_split": {"dev": 1, "train": 1}, "case_ids": ["s04", "s35"]}`
- Hidden fields: `["gold", "predicted", "adjudicated_label", "annotator_labels", "label_notes"]`
- Review phase: `first_review_high_risk`
- Packet purpose: Assign a balanced first-review packet for unreviewed high-risk support cases.

## Task

Label each claim/evidence pair using only the evidence text and evidence_scope in the packet.
Each returned row is one independent annotation; do not discuss labels before submission.
Do not infer support from citation fame, venue prestige, source outage, or topical similarity alone.

## Allowed Labels

Use exactly one of: `supported`, `weakly_supported`, `insufficient_evidence`, `contradicted`.

- `supported`: the evidence directly entails the claim.
- `weakly_supported`: the evidence is relevant but weaker, narrower, or less precise than the claim.
- `insufficient_evidence`: the evidence does not justify the claim or the claim requires unavailable full text.
- `contradicted`: the evidence directly conflicts with the claim.

When unsure, choose the more conservative label. In particular, avoid `supported` unless the evidence is explicit.

## Fields To Fill

- `annotation.annotator_id`: required stable reviewer id.
- `annotation.annotator_label`: required label from the allowed set.
- `annotation.rationale`: short explanation citing the evidence text.
- `annotation.confidence`: optional low/medium/high or numeric confidence.
- `annotation.evidence_scope_assessed`: optional scope actually judged, such as abstract, full_text, mixed, or insufficient_scope.
- `annotation.full_text_needed`: optional yes/no/unclear flag for claims that require lawful full-text inspection.
- `annotation.notes`: optional ambiguity, scope, or full-text notes.
- `review_focus`: non-gold guidance about the support boundary to inspect; do not treat it as a label hint.
- `review_queue_rank`, when present, is assignment priority from eval triage; do not treat it as a label hint.
- `review_protocol`: machine-readable assignment protocol; do not edit it.

## Do Not Modify

Do not edit `case_id`, `claim`, `evidence`, `evidence_scope`, `case_type`, `split`, `priority`, `review_focus`, `review_phase`, `packet_purpose`, `review_protocol`, or `source_locator`.
Also do not edit `packet_id`, `packet_digest`, `packet_case_index`, or `review_queue_rank`; they tie returned annotations back to the archived reviewer batch.
The packet intentionally omits dataset gold labels and adjudicated labels; do not request or reconstruct them before labeling.

## Return Checklist

- Every returned row has `annotation.annotator_id`.
- Every returned row has one valid `annotation.annotator_label`.
- Rationale is present for every `supported`, `weakly_supported`, or `contradicted` label.
- Scope-sensitive cases record `annotation.evidence_scope_assessed` and `annotation.full_text_needed` when applicable.
- Claims needing unavailable full text are labeled `insufficient_evidence`, not guessed.
