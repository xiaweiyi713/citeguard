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
  provenance overclaims, source-outage-to-fabrication inferences, and
  abstract-only claims that require full-text methods evidence.
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
- `scripts/eval_support.py` reports precision, recall, F1, false-support rate,
  abstention rate, misjudged-support rate, contradiction recall, confusion
  matrices, case-type breakdowns, evidence-scope breakdowns, split breakdowns,
  per-case rows, `false_support_analysis` release-triage summaries,
  including grouped `false_support_case_ids` and
  `weak_false_support_case_ids`, diagnostics, a deterministic
  `support_set_policy` fixture, and conservative quality gates.
- `scripts/compare_support_baselines.py` compares deterministic fixture and
  heuristic support baselines, including total support-overcall counts and
  high-risk false support case ids, and writes reproducible artifacts when an
  output directory is provided.
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
  gold.
- Verification and support eval scripts can write `result.json`, `config.json`,
  and `manifest.json` artifacts under versioned `experiments/` run folders.

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
   high-risk claim/evidence pairs.
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
