# Support Labeling Guidelines

These guidelines define how to label claim-support examples for CiteGuard's
support benchmark. The benchmark should measure whether a cited paper supports a
nearby claim, not whether the paper merely exists or is topically related.

## Unit of Annotation

Each example is a `(claim, evidence, citation)` judgment.

- `claim`: the sentence or compact claim made by the writer or agent.
- `evidence`: the text available to the verifier, usually title, abstract, or
  extracted source metadata.
- `citation`: the cited paper record. A real paper can still fail to support the
  claim.

Do not label a claim as supported because the citation is famous, plausible, or
topically adjacent. Use only the evidence scope recorded for the example.

## Labels

Use exactly one gold label:

- `supported`: the evidence directly entails the claim at the stated strength.
- `weakly_supported`: the evidence is relevant and partially supports the claim,
  but the claim is broader, stronger, or less precise than the evidence.
- `insufficient_evidence`: the evidence does not justify the claim. This includes
  unrelated papers, related-but-noncommittal evidence, missing abstracts, and
  claims that require full text when only abstract-level evidence is available.
- `contradicted`: the evidence directly conflicts with the claim.

`supported` is the highest-risk label. When annotators are unsure between
`supported` and `weakly_supported`, prefer `weakly_supported`. When unsure
between `weakly_supported` and `insufficient_evidence`, prefer
`insufficient_evidence` and record the reason in `label_notes`.

## Evidence Scope

Record the strongest scope that was actually used:

- `title`: title-only evidence.
- `abstract`: abstract sentence evidence.
- `metadata`: structured metadata or source-provided snippets without a landing
  page URL.
- `metadata_snippet`: remote source or publisher landing-page snippet.
- `full_text`: full-text evidence that was lawfully available and explicitly
  captured.
- `mixed`: more than one non-full-text scope contributed.
- `mixed_with_full_text`: full text plus another scope contributed.
- `none`: no usable evidence was available.

Do not label abstract-level evidence as `full_text`. If the claim requires
methods, limitations, tables, quantitative details, or experimental setup not
present in the abstract, label it `insufficient_evidence` unless full-text
evidence is actually available.

## Case Types

Use `case_type` to make breakdowns useful:

- `direct_support`: evidence directly supports the claim.
- `weak_support`: evidence is related but not strong enough for `supported`.
- `hard_negative`: the paper is real and related but does not support the claim.
- `unrelated_negative`: the evidence is unrelated to the claim.
- `contradiction`: the evidence conflicts with the claim.
- `metadata_only`: the example tests title/venue/year existence rather than
  substantive support.
- `full_text_required`: abstract-level evidence is insufficient but full text may
  decide the claim.

Prefer adding hard negatives over easy unrelated negatives. CiteGuard's most
important failure mode is saying `supported` for a real but non-supporting paper.

## Provenance Fields

Every benchmark case should include:

- `id`: stable, unique identifier.
- `claim`: claim text.
- `evidence`: exact evidence text used for the label.
- `gold`: one of the labels above.
- `lang`: language code if known.
- `evidence_scope`: one of the scopes above.
- `label_source`: where the label came from, such as `maintainer_synthetic`,
  `single_annotator`, `dual_annotator_adjudicated`, or `published_benchmark`.
- `case_type`: one of the case types above.
- `split`: one of `train`, `dev`, or `test`.
- `label_notes`: short note explaining overclaims, contradiction cues, or why
  abstract-level evidence is insufficient.

Use splits conservatively:

- `train`: examples used while designing heuristics, prompts, or lightweight
  rules. Do not report final quality from this split.
- `dev`: examples used for threshold selection, model/backend choice, and error
  analysis during calibration.
- `test`: locked examples for final reporting. Do not tune thresholds after
  inspecting failures on this split.

Human-reviewed examples should also track annotator count, disagreement status,
adjudicator, and source URL or DOI in a sidecar file if that metadata should not
ship in the compact in-repo seed set.

## Label Provenance Sidecar

Use a sidecar when annotation metadata should be versioned but kept separate from
the compact benchmark cases. Each sidecar entry should include:

- `case_id`: stable id matching a case in the benchmark dataset.
- `adjudication_status`: one of `not_human_reviewed`, `single_annotator`,
  `dual_annotator_agreed`, `dual_annotator_adjudicated`, or
  `published_benchmark`.
- `annotator_count`: number of independent labels recorded.
- `annotator_labels`: labels before discussion or adjudication.
- `adjudicated_label`: final label; it must match the dataset `gold`.
- `disagreement`: `none`, `resolved`, `unresolved`, or `not_applicable`.
- `adjudicator`: required when `adjudication_status` is
  `dual_annotator_adjudicated`.
- `source_locator`: DOI, URL, corpus id, or blank for synthetic examples.
- `notes`: provenance or disagreement details.

`not_human_reviewed` is allowed for synthetic seed examples, but do not describe
such examples as a human-reviewed benchmark. Use `dual_annotator_adjudicated`
for high-stakes final benchmark cases with resolved reviewer disagreement.
Sidecar validation reports a `label_maturity` block with `reviewed_fraction`,
`dual_annotated_count`, `raw_dual_agreement_rate`, `adjudicated_count`,
`resolved_disagreement_count`, `unresolved_disagreement_count`,
`disagreement_case_ids`, `unresolved_disagreement_case_ids`,
`dual_label_pair_counts`, `dual_disagreement_label_pair_counts`, and
`supported_disagreement_case_ids`. Review these fields before claiming benchmark
maturity; coverage alone is not enough. Treat any supported-label disagreement
as high priority because a premature `supported` label is the most dangerous
benchmark error for a skeptical citation auditor.
Validation also checks status consistency so maturity cannot be inflated by
malformed rows: `not_human_reviewed` must have zero annotators and no labels,
`dual_annotator_agreed` must contain matching annotator labels,
`dual_annotator_adjudicated` must contain a resolved disagreement with an
adjudicator, and `published_benchmark` rows must include a source locator.
For release or paper-grade benchmark evidence, validate the completed sidecar
with explicit maturity gates, for example:

```bash
python3 scripts/eval_support.py --validate-only \
  --label-sidecar data/eval/support_eval_label_sidecar.draft.json \
  --min-sidecar-coverage 1.0 \
  --min-human-reviewed 10 \
  --min-high-risk-reviewed 5 \
  --min-high-risk-reviewed-by-language zh=2 \
  --min-dual-annotated 10 \
  --max-unresolved-disagreements 0 \
  --min-raw-dual-agreement-rate 0.8 \
  --max-supported-disagreements 0
```

Use `--min-high-risk-reviewed` to require human review for contradiction,
hard-negative, full-text-required, and contradiction-set cases before making
benchmark maturity claims. The sidecar validation `high_risk_review` block
reports `case_count_by_language`, `reviewed_by_language`, and
`unreviewed_by_language` so language-specific review gaps, such as unreviewed
Chinese high-risk cases, are visible before release. It also reports
`reviewed_case_ids_by_language` and `unreviewed_case_ids_by_language` so
annotation packets can target the exact remaining cases. Use repeated
`--min-high-risk-reviewed-by-language LANG=N` gates when a release claim depends
on language-specific coverage. Use
`--max-supported-disagreements 0` for release-grade benchmark claims. It fails with
`sidecar_supported_disagreements` when any dual-annotation disagreement includes
a `supported` label, forcing explicit adjudication before the benchmark can be
described as mature.
The corresponding `label_sidecar_gate.metrics` block includes
`high_risk_case_count_by_language`, `high_risk_reviewed_by_language`, and
`high_risk_unreviewed_by_language` for release triage.

Generate a complete sidecar template before an annotation pass:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --include-context \
  --output data/eval/support_eval_label_sidecar.draft.json
```

The script preserves existing reviewed entries and fills missing cases with
`not_human_reviewed` placeholders, so coverage gaps are visible before labels
are collected. Validate the completed sidecar with:

```bash
python3 scripts/eval_support.py --validate-only \
  --label-sidecar data/eval/support_eval_label_sidecar.draft.json
```

Do not send a sidecar draft with `adjudicated_label` or dataset `gold` fields to
independent annotators. For blinded annotation, generate a packet instead:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet \
  --priority high \
  --split test \
  --lang zh \
  --limit 10 \
  --output experiments/support-label-packet-high-risk-test.json \
  --instructions-output experiments/support-label-packet-high-risk-test-instructions.md
```

The annotation packet includes claim/evidence context, evidence scope, case
type, split, language, priority, source locator, a non-gold `review_focus`
boundary hint, and blank annotation fields. It omits `gold`, `adjudicated_label`,
`annotator_labels`, and `label_notes` so reviewers can label independently
before adjudication. `review_focus` tells reviewers what support boundary to
inspect, for example full-text gaps or topical overclaims, but it is not a
label hint. Use `--packet-format jsonl` when you want one case per line for
spreadsheets or lightweight annotation tools. Use repeated `--lang` values to
prepare language-specific review batches, such as Chinese high-risk cases.
Use `--instructions-output` to write a reviewer-facing Markdown instruction
sheet with the allowed labels, conservative labeling rule, required annotation
fields, and fields that must not be modified.
Reviewers must fill `annotation.annotator_id`; merge rejects missing annotator
identity, and the same annotator cannot count twice for one case.
After reviewers return completed packets, merge matching labels back into a
sidecar draft:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --merge-annotation-packet experiments/completed-support-label-packet.json \
  --output data/eval/support_eval_label_sidecar.merged.json
```

The merge is conservative. A single returned label matching the dataset gold is
recorded as `single_annotator`; two or more matching labels are recorded as
`dual_annotator_agreed`. Any annotator disagreement or label that conflicts with
the current dataset gold is reported in `merge_report.conflicts`, exits non-zero,
and is not silently applied. Resolve those cases by adjudication before raising
human-review gates or making benchmark claims. Missing annotator ids are reported
in `merge_report.skipped`; duplicate annotator ids for the same case are reported
as `duplicate_annotator` conflicts so duplicate rows cannot inflate
dual-annotation maturity.

After discussion, apply resolved adjudications explicitly:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.merged.json \
  --apply-adjudications experiments/resolved-support-label-adjudications.json \
  --output data/eval/support_eval_label_sidecar.adjudicated.json
```

Each adjudication row must include `case_id`, `annotator_labels`,
`adjudicated_label`, and `adjudicator`. The adjudicated label must match the
current dataset `gold`; otherwise the command reports
`adjudication_report.conflicts` and exits non-zero. Update the benchmark dataset
only after an explicit review, then rerun sidecar validation.

Before assigning reviewers, generate a review-readiness audit:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --audit
```

The audit reports coverage, human-reviewed count, unreviewed cases by split,
language, and case type, plus a risk-sorted `high_risk_unreviewed` list and
`high_risk_unreviewed_by_language`. Use
`--fail-on-high-risk-unreviewed-language LANG` when a language-specific review
batch, such as Chinese high-risk cases, must block release readiness. Use
`--unreviewed-only` when assigning reviewer packets from a sidecar that already
contains human-reviewed cases. Use `--review-status single_annotator` to assign
second-reviewer packets without exposing prior labels. Use `--limit-per-language`,
`--limit-per-case-type`, and `--limit-per-evidence-scope` on
`--annotation-packet` when assigning small reviewer batches that should cover
multiple languages, high-risk case families, and evidence scopes instead of only
the earliest filtered rows. Archive the
packet's deterministic `packet_id` and `packet_summary` with review evidence so
release notes can show exactly which case ids, languages, case types, and
evidence scopes were assigned. After `--merge-annotation-packet`, keep
`merge_report.source_packet_ids` with the merged sidecar so adjudication records
can be traced back to reviewer batches. Review
contradiction, hard-negative, and full-text-required cases first because those
most directly test false support and overclaiming.

## Disagreement Handling

Do not silently collapse disagreements.

1. Label independently first.
2. Record each annotator's label before discussion.
3. Resolve with an adjudicated final label.
4. Preserve disagreement notes for ambiguous cases.

For ambiguous examples, keep the final label conservative. A benchmark that
over-labels `supported` will reward the exact behavior CiteGuard is designed to
discourage.

## Exclusions

- Do not use paywalled or gated full text unless the text is lawfully available
  for the project and can be redistributed or replaced with a compliant excerpt.
- Do not crawl CNKI, Wanfang, or other gated sources.
- Do not infer support from citation count, venue prestige, or author reputation.
- Do not treat `not_found` or source outage as evidence that a claim is false.
