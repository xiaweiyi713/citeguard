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

Seed sidecar entries also copy read-only dataset context fields
(`label_source`, `case_type`, `evidence_scope`, `split`, and `lang`) so review
packets and release gates can verify provenance without rejoining by `case_id`.
Validation reports this as `sidecar_case_provenance`, including
`missing_count` and `missing_case_ids` so maintainers can distinguish incomplete
sidecar coverage from missing per-field provenance on otherwise present cases.

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
Validation also summarizes provenance with `label_source_counts`,
`reviewed_by_label_source`, `unreviewed_by_label_source`,
`reviewed_source_locator_count`, and
`published_benchmark_source_locator_count`, so maintainers can distinguish
synthetic seed coverage from human-reviewed labels and see whether published
benchmark rows have traceable source locators.
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
`high_risk_unreviewed_by_language` for release triage, plus the corresponding
`*_by_language_case_type` cross tables for assigning language-specific
contradiction, hard-negative, contradiction-set, and full-text-boundary review, plus
`dual_annotated`, `raw_dual_agreement_rate`, unresolved/supported disagreement
counts and case ids, and the label-source and source-locator provenance counts
needed to keep benchmark readiness claims auditable. Experiment manifests copy
these maturity fields into `result_summary` so archived support-eval artifacts
remain interpretable without reopening the sidecar.

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
boundary hint, and blank annotation fields. Reviewers can fill
`annotation.evidence_scope_assessed` and `annotation.full_text_needed` to record
whether the shown evidence scope was enough or lawful full-text inspection is
still required. It omits `gold`, `adjudicated_label`, `annotator_labels`, and
`label_notes` as case keys so reviewers can label
independently before adjudication. The top-level `hidden_fields` list records
those deliberately hidden keys for audit/release checks; it is a blindness
contract, not label data. `review_focus` tells reviewers what support boundary
to inspect, for example full-text gaps or topical overclaims, but it is not a
label hint. Each JSON packet also carries `review_protocol`, which records
`packet_role`, `independent_labeling_required`,
`packet_target_annotator_count`, `benchmark_target_annotator_count`,
`second_review_required_after_first_review`, and
`adjudication_required_on_disagreement`. Treat this as reviewer-assignment
protocol, not label evidence. Each JSON packet also carries a deterministic `packet_id`,
`packet_digest`, and `packet_summary` with `case_count_by_review_status` so
maintainers can tell whether the batch is for first review, second review, or
adjudication follow-up and verify the exact archived packet content. The digest
is a `sha256:` content fingerprint over packet fields excluding digest metadata;
JSONL packets include the same digest and `review_protocol` on each row so spreadsheet workflows keep
the provenance anchor.
Use `--packet-format jsonl` when you want one case per line for
spreadsheets or lightweight annotation tools. Use repeated `--lang` values to
prepare language-specific review batches, such as Chinese high-risk cases.
Use `--instructions-output` to write a reviewer-facing Markdown instruction
sheet with the allowed labels, conservative labeling rule, required annotation
fields, and fields that must not be modified.
Reviewers must fill `annotation.annotator_id`; merge rejects missing annotator
identity, and the same annotator cannot count twice for one case. When
reviewers return `annotation.evidence_scope_assessed` or
`annotation.full_text_needed`, merge preserves those scope notes in sidecar
provenance notes so abstract-only and full-text-needed judgments remain
auditable.
If a support backend fails the quality gate, convert its `review_queue` into a
blinded packet before changing thresholds:

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

This preserves eval triage order through `review_queue_rank`, but the packet
remains blinded: it does not include dataset gold labels, adjudicated labels,
previous annotator labels, or backend predictions.
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
and is not silently applied. Those conflicts also populate
`merge_report.adjudication_queue` with annotator ids, labels, rationales,
confidence notes, source packet ids, packet case indexes, and a blank
adjudication template with `source_packet_ids` and `source_packet_metadata`
so the disagreement can be reviewed without losing packet digest, review phase,
or packet purpose provenance. `--apply-adjudications` records those packet ids and
metadata in `adjudication_report.source_packet_ids`,
`adjudication_report.source_packet_metadata`, and sidecar notes. Resolve those
cases by adjudication before raising human-review
gates or making benchmark claims. Missing annotator ids are reported in
`merge_report.skipped`; duplicate annotator ids for the same case are reported
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
language, and case type, plus a risk-sorted `high_risk_unreviewed` list,
`high_risk_unreviewed_by_language`, and
`high_risk_unreviewed_by_language_case_type`. It also reports
`policy_boundary_unreviewed` for citation-set weak aggregation cases that are
medium priority but safety-sensitive because reviewers must keep multiple weak
citations tentative instead of upgrading them to full support. It also reports
`full_text_required_unreviewed` so abstract/full-text boundary cases can be
assigned without mixing them into broader contradiction triage. It emits machine-readable
`recommended_packets` entries with ready-to-run annotation-packet commands for
balanced high-risk first review, language-specific high-risk review,
language-and-case-type high-risk slices, full-text-boundary first review, and
policy-boundary first review, plus
second-reviewer batches when
`single_annotator` cases exist. The audit also emits a machine-readable
`review_plan` with phased statuses for first review, second review,
adjudication, and release-gate tightening. Agents should use
`review_plan.next_phase` and the phase `command_template`/`recommended_packet_ids`
instead of inventing their own benchmark-readiness sequence. The
`first_review_high_risk` phase repeats
`candidate_case_count_by_language_case_type` so annotation coordinators can
split the first pass by language and risk category without recomputing the
unreviewed list. The package release
gate smoke-generates the balanced first-review recommendation and verifies that
the blinded packet includes `review_phase`, `packet_purpose`, and
`case_count_by_review_status` plus `review_protocol` while omitting hidden gold, adjudicated, and
prediction fields. Use
`--fail-on-high-risk-unreviewed-language LANG` when a language-specific review
batch, such as Chinese high-risk cases, must block release readiness. Use
`--fail-on-full-text-required-unreviewed` before claiming full-text boundary
readiness, and `--fail-on-policy-boundary-unreviewed` before claiming
multi-citation support readiness. Use
`--unreviewed-only` when assigning reviewer packets from a sidecar that already
contains human-reviewed cases. Use `--review-status single_annotator` to assign
second-reviewer packets without exposing prior labels. Use `--limit-per-language`,
`--limit-per-case-type`, and `--limit-per-evidence-scope` on
`--annotation-packet` when assigning small reviewer batches that should cover
multiple languages, high-risk case families, and evidence scopes instead of only
the earliest filtered rows. Archive the
packet's deterministic `packet_id`, `packet_digest`, `review_protocol`, and `packet_summary` with
review evidence so release notes can show exactly which packet content, case ids,
languages, case types, and evidence scopes were assigned. After
`--merge-annotation-packet`, keep `merge_report.source_packet_ids` and
`merge_report.source_packet_metadata` with the merged sidecar so adjudication
records can be traced back to reviewer batches and their packet digests. Review
contradiction, hard-negative, and full-text-required cases first because those
most directly test false support and overclaiming.

## Human-Benchmark Review Packets

The ordinary software publish workflow now uses
`scripts/automated_release_review.py`; its model outputs are release checks,
not annotations, and must never be merged into this sidecar. If a future
release requests `--release-claim-mode human-benchmark`, the following
deterministic pair is a starting packet plan covering 20 independently reviewed
high-risk cases (including 3 Chinese cases) and a 10-case dual-review subset.
Generate both from the untouched sidecar so the reviewers cannot see one
another's decisions:

```bash
python scripts/prepare_support_label_sidecar.py \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet --priority high --unreviewed-only --limit 20 \
  --review-phase first_review \
  --packet-purpose "Independent first review for release-label gate" \
  --output experiments/support-label-release-first.json \
  --instructions-output experiments/support-label-release-first.md

python scripts/prepare_support_label_sidecar.py \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet --priority high --unreviewed-only --limit 10 \
  --review-phase second_review \
  --packet-purpose "Independent second review for release-label gate" \
  --output experiments/support-label-release-second.json \
  --instructions-output experiments/support-label-release-second.md
```

The second packet must be a subset of the first. Archive both packet IDs and
digests, merge the completed first packet, then merge the completed second
packet. Resolve every disagreement with a separate adjudicator. The raw
dual-agreement threshold remains an observed quality measure; do not rewrite
independent annotations merely to make it pass.

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
