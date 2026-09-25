# CiteGuard Support Annotation Instructions

- Dataset: `support_eval.json`
- Packet type: `support_label_annotation_packet`
- Packet id: `support-packet-bd24417582d0eff0`
- Case count: `35`
- Filters: `{"priority": ["high"], "unreviewed_only": true}`
- Review protocol: `{"adjudication_required_on_disagreement": true, "benchmark_target_annotator_count": 2, "cases_already_single_annotated": 0, "independent_labeling_required": true, "merge_policy": "single_annotator_until_second_review; dual_annotator_agreed_or_adjudicated_before_benchmark_claims", "packet_role": "first_review", "packet_target_annotator_count": 1, "reviewer_must_not_see_hidden_labels": true, "schema_version": 1, "second_review_required_after_first_review": true}`
- Packet summary: `{"case_count_by_case_type": {"contradiction": 15, "contradiction_set": 1, "full_text_required": 7, "hard_negative": 12}, "case_count_by_evidence_scope": {"abstract": 23, "metadata_snippet": 9, "mixed": 2, "mixed_with_full_text": 1}, "case_count_by_language": {"en": 26, "zh": 9}, "case_count_by_priority": {"high": 35}, "case_count_by_review_status": {"not_human_reviewed": 35}, "case_count_by_split": {"dev": 10, "test": 16, "train": 9}, "case_ids": ["s10", "s16", "s27", "s36", "s39", "s48", "s08", "s21", "s22", "s29", "s32", "s42", "s04", "s34", "s44", "s23", "s31", "s41", "s45", "s46", "s47", "s35", "s40", "s07", "s15", "s28", "s37", "s17", "s30", "s43", "s13", "s38", "s20", "s33", "ss03"]}`
- Hidden fields: `["gold", "predicted", "adjudicated_label", "annotator_labels", "label_notes"]`
- Review phase: `first_review_high_risk`
- Packet purpose: Full first-review packet for all unreviewed high-risk support cases.

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
