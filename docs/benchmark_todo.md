# Benchmark Roadmap

This document tracks what is already implemented in the benchmark package and
what still has to happen before CiteGuard can make strong research-grade
benchmark claims.

## Implemented Seed Package

- `data/eval/support_eval.json` uses schema version 2 with stable case ids,
  `train` / `dev` / `test` splits, label source metadata, case types, evidence
  scopes, and a dataset-level label policy.
- The seed set covers direct support, weak support, unrelated negatives, hard
  negatives, full-text-required cases, explicit contradictions, and citation-set
  aggregation boundaries. Current high-risk seed cases include benchmark
  provenance overclaims, source-outage-to-fabrication inferences, multi-paper
  weak-evidence over-synthesis, model-availability-as-support overclaims,
  supplemental-material full-text boundaries, Semantic Scholar rate-limit
  non-existence overclaims, a Chinese citation-set weak aggregation boundary, a
  source-limited citation-set fabrication boundary, and abstract-only claims
  that require full-text methods evidence.
- Dataset validation requires high-risk support boundaries in the `test` split:
  weak support, hard negatives, contradictions, full-text-required cases, and
  every gold label must be present before final-report metrics are trusted.
- `data/eval/support_eval_label_sidecar.json` records adjudication status,
  annotator counts, adjudicated labels, disagreement state, source locators, and
  notes for every seed case. Sidecar validation also reports `label_maturity`
  with dual-annotation counts, raw agreement rate, adjudicated cases, and
  unresolved disagreement counts, plus label-pair disagreement diagnostics such
  as `dual_disagreement_label_pair_counts` and
  `supported_disagreement_case_ids`.
- `scripts/eval_support.py` reports supported, macro, weighted, and per-label
  precision/recall/F1, false-support rate,
  support-overcall count/rate, abstention rate, misjudged-support rate, contradiction recall, confusion
  matrices, case-type breakdowns, evidence-scope breakdowns, split breakdowns,
  per-case rows, compact `release_summary` status/next-action fields,
  `false_support_analysis` release-triage summaries,
  including grouped `false_support_case_ids`,
  `weak_false_support_case_ids`, `acceptance_guard` fields such as
  `ok_to_accept_supported`, `block_acceptance_case_ids`, and
  `review_before_accepting_case_ids`, `false_support_analysis.review_plan`
  fields such as `review_plan.status`, `supported_overcall_blockers`, and
  `weak_support_overcall_review`, manifest summary fields such as
  `false_support_review_plan_status` and `false_support_review_plan_phase_ids`,
  and risk slices for contradicted, hard-negative,
  full-text-boundary, test-split, and non-English support overcalls,
  `release_blocker_summary` fields such as
  `release_blocker_summary.release_blocked`,
  `release_blocker_summary.benchmark_claim_safe`,
  `release_blocker_summary.blocking_case_ids`,
  `release_blocker_summary.review_required_case_ids`, and
  `release_blocker_summary.next_action` so release tooling can distinguish
  blocking critical/high rows from medium rows that still need review before
  benchmark claims,
  fixed `acceptance_slices` for contradiction, hard-negative,
  full-text-boundary, heldout test split, and non-English cases so high-risk
  support coverage remains visible even when every slice is clear,
  plus `abstention_analysis` summaries that split correct conservative
  abstentions from incorrect abstentions that need recall or contradiction
  review,
  diagnostics, a deterministic
  `support_set_policy` fixture, and conservative quality gates.
- `scripts/compare_support_baselines.py` compares deterministic fixture and
  heuristic support baselines, including total support-overcall counts and
  high-risk false support case ids plus `false_support_risk_slices`, and writes
  reproducible artifacts when an output directory is provided. Artifact
  manifests include `support_label_*` provenance summary fields such as
  `support_label_gate_ok`, `support_label_label_source_counts`,
  `support_label_human_reviewed`, `support_label_high_risk_unreviewed`,
  `support_label_full_text_required_unreviewed`,
  `support_label_policy_boundary_unreviewed`, and
  `support_label_published_benchmark_source_locator_count`, so release tables
  can show seed-vs-human-review status without opening the full result payload.
- `scripts/prepare_support_label_sidecar.py --audit` checks label-sidecar
  coverage and human-review maturity, including `label_maturity`. Its optional
  `--fail-on-high-risk-unreviewed` gate exits non-zero while contradiction,
  hard-negative, or full-text-required cases still lack human review. Use
  `--priority high --split test --include-context` to produce a compact
  maintainer review draft, or `--annotation-packet --priority high --split test`
  with optional `--lang zh` to produce a blinded annotator packet for the
  riskiest held-out or Chinese cases without leaking dataset gold labels or
  claiming they have already been reviewed.
  Completed packets can be merged back with `--merge-annotation-packet`; label
  conflicts are reported instead of silently overwriting gold labels. Resolved
  conflicts can be applied with `--apply-adjudications`, which requires an
  adjudicator and refuses adjudicated labels that do not match current dataset
  gold. Annotation packets now carry a `packet_digest` content fingerprint, and
  merge/adjudication reports preserve it in `source_packet_metadata` so reviewer
  evidence can be traced to the exact archived packet.
- Verification and support eval scripts can write `result.json`, `config.json`,
  and `manifest.json` artifacts under versioned `experiments/` run folders.
- `scripts/calibrate_support.py` can run from raw examples when model backends
  are installed, from `data/eval/support_eval.json` with
  `--support-eval-dataset ... --split dev`, or from deterministic cached
  component scores with `--scored-dataset` for CI/release smoke. The support-eval
  path treats only `gold=supported` as a strong-support positive;
  `weakly_supported`, `insufficient_evidence`, and `contradicted` remain
  negatives so calibration stays false-support-sensitive. With `--output-dir`
  and `--run-id`, it writes a standard `support_calibration` artifact with
  `result.json`, `config.json`, and `manifest.json`; the manifest summary includes
  `support_calibration_top_f1`, `support_calibration_top_precision`,
  `support_calibration_top_recall`, and
  `support_calibration_top_false_support_rate` so threshold choices can be
  compared without parsing full grid-search output. It also exposes
  `support_calibration_top_false_positive_case_ids` and
  `support_calibration_top_false_negative_case_ids`,
  `support_calibration_top_false_positive_decision_paths`, and
  `support_calibration_top_false_positive_score_summary` so false-support and
  false-reject cases can be triaged directly from the manifest, including
  whether a false support came from NLI entailment, paired reranking, or another
  ensemble path and what the average NLI neutral/entailment scores looked like.

## Current Limitations

- The shipped seed set is maintainer-authored synthetic data, not a
  human-reviewed benchmark.
- The sidecar intentionally reports `human_reviewed: 0` until real annotation is
  performed.
- The deterministic fixture backend is useful for regression tests, but it is
  not evidence that a production model stack is calibrated.
- The benchmark is still small and does not support broad domain-general claims.

## Next Evaluation Milestones

1. Build a human-reviewed subset with at least two annotators for ambiguous and
   high-risk claim/evidence pairs. Start from
   `scripts/prepare_support_label_sidecar.py --audit` and follow
   `review_plan.next_phase` so first-review, second-review, adjudication, and
   release-gate tightening happen in a reproducible order.
2. Raise the release gate from `--min-high-risk-reviewed 0`,
   `--min-high-risk-reviewed-by-language zh=0`, and `--min-human-reviewed 0`
   once that subset exists.
3. Add reviewer disagreement examples instead of silently collapsing labels.
4. Expand domain coverage beyond the current synthetic seed set, especially for
   review-writing claims, CS systems papers, and biomedical abstracts.
5. Run production support evals with model dependencies installed and compare
   fixture, heuristic, reranker-only, NLI-only, and ensemble configurations.
6. Add retrieval-source ablations for in-memory fixtures, OpenAlex, Crossref,
   arXiv, Semantic Scholar, and multi-source merged evidence.
7. Publish compact benchmark tables only after label provenance and domain
   coverage are strong enough to support the claim being made.

For model-backed calibration against the seed benchmark, tune on `dev` rather
than held-out `test`:

```bash
python scripts/calibrate_support.py \
  --support-eval-dataset data/eval/support_eval.json \
  --split dev \
  --profile standard \
  --top-k 10 \
  --output-dir experiments \
  --run-id support-calibration-dev
```

For a deterministic calibration artifact that does not load local model weights:

```bash
python scripts/calibrate_support.py \
  --scored-dataset experiments/scored-support-dev.json \
  --profile quick \
  --top-k 5 \
  --output-dir experiments \
  --run-id support-calibration-dev
```

## Release Rule

Before any release note describes CiteGuard as having a human-reviewed benchmark,
run:

```bash
python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --audit
python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --annotation-packet --priority high --split test --limit 3 --output experiments/support-label-packet-high-risk-test-batch1.json
python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --annotation-packet --priority high --split test --unreviewed-only --limit-per-language 1 --limit-per-case-type 1 --limit-per-evidence-scope 1 --output experiments/support-label-packet-high-risk-test-balanced-batch1.json
python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.merged.json --annotation-packet --review-status single_annotator --priority high --limit 10 --output experiments/support-label-packet-high-risk-second-review-batch1.json
python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --annotation-packet --priority high --split test --lang zh --limit 3 --output experiments/support-label-packet-high-risk-test-zh-batch1.json
python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --merge-annotation-packet experiments/completed-support-label-packet-high-risk-test-batch1.json --output data/eval/support_eval_label_sidecar.merged.json
python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.merged.json --apply-adjudications experiments/resolved-support-label-adjudications.json --output data/eval/support_eval_label_sidecar.adjudicated.json
python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --audit --fail-on-high-risk-unreviewed --fail-on-high-risk-unreviewed-language zh
python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --audit --fail-on-full-text-required-unreviewed --fail-on-policy-boundary-unreviewed
python scripts/compare_support_baselines.py --split test --output-dir experiments --run-id support-baselines-release
python scripts/eval_support.py --validate-only \
  --label-sidecar data/eval/support_eval_label_sidecar.json \
  --min-sidecar-coverage 1.0 \
  --min-human-reviewed <required-count> \
  --min-high-risk-reviewed <required-high-risk-count> \
  --min-high-risk-reviewed-by-language zh=<required-zh-high-risk-count> \
  --min-dual-annotated <required-count> \
  --max-unresolved-disagreements 0 \
  --min-raw-dual-agreement-rate <threshold> \
  --max-supported-disagreements 0
```

If the gate reports zero human-reviewed cases, or if the high-risk audit gate
fails, describe the data as a deterministic synthetic seed set only.
