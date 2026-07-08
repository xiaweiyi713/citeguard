# Support eval, labeling workflow, and release evidence

This document covers the claim-support evaluation datasets, report fields,
quality gates, label-provenance sidecars, and blinded annotation packet
workflow. The README keeps only the entry-point commands.

## Datasets and reports

The unit suite, verification eval, support fixture eval, and support dataset
validation are network-free and run in CI. Eval datasets live in
[`../data/eval/`](../data/eval/).
The claim-support seed eval includes 48 evidence-level cases plus 6 citation-set
policy cases. It reports accuracy, supported precision/recall/F1,
macro and weighted precision/recall/F1, per-label precision/recall/F1,
abstention rate, false-support rate, contradiction recall,
optional breakdowns by `case_type`, `evidence_scope`, language, and split, a confusion matrix,
high-risk error buckets such as false support and missed contradiction, and
provenance fields for each synthetic seed case. Reports also include
`release_summary`, a compact release/agent-facing block with `status`,
`next_action`, key precision/recall/F1, false-support, abstention, review-queue,
acceptance, and label-maturity fields so callers do not need to scrape the full
report to decide whether support claims are release-safe,
`support_overcall_count` / `support_overcall_rate`, which count both
`supported` and `weakly_supported` predictions on non-supporting gold cases so
agents can track total overconfidence pressure separately from strict
`false_support_rate`,
`review_queue`, which ranks the most dangerous support-eval failures first,
`review_queue_summary`, which groups that queue by severity, bucket, and
recommended action, plus
`false_support_analysis`, which summarizes total support overcalls, high-risk
false-support case ids, and breakdowns by case type, evidence scope, language,
and split for release triage, `acceptance_guard`, which states whether
`supported` predictions can be accepted and lists
`block_acceptance_case_ids` plus `review_before_accepting_case_ids`, and
`acceptance_slices`, a fixed set of high-risk slices (`contradiction`,
`hard_negative`, `full_text_boundary`, `test_split`, `non_english`) that stays
visible even when clear so release tooling can detect disappeared risk coverage,
and
`abstention_analysis`, which separates
correct abstentions from incorrect abstentions that may hide support recall or
missed-contradiction problems.

The latest seed expansion covers multi-paper weak-evidence over-synthesis,
deployed-agent hallucination-elimination overclaims, model-availability-as-support
overclaims, supplemental-material full-text boundaries, Semantic Scholar rate-limit non-existence overclaims,
a Chinese citation-set weak aggregation boundary, and a source-limited
citation-set fabrication boundary.

## Quality gates

`--quality-gate` turns the report into a conservative
release gate: by default, any false support, weak false support, or missed
contradiction fails the command with a machine-readable `quality_gate` block.
Failed gates include `quality_gate.review_queue_case_ids` and
`quality_gate.critical_review_case_ids` so agents can inspect the highest-risk
cases first. Use `--review-queue-only` when an agent or release script only
needs the compact support-failure triage payload instead of the full report;
add `--review-queue-limit N` to return only the first N risk-ordered
`review_queue` rows while preserving full queue counts in
`review_queue_summary`, `quality_gate`, and `review_queue_filtered`;
the compact payload includes `release_summary`,
`false_support_analysis.risk_slices` and
`false_support_analysis.top_risk_slice` for supported-overcall priorities plus
`acceptance_guard.ok_to_accept_supported` and `acceptance_slices` so agents can
block strong false-support acceptance and still show clear high-risk coverage
without parsing prose. When
`--label-sidecar` is provided, the compact payload also includes
`label_maturity` and `label_sidecar_gate.metrics` with human-reviewed counts,
dual-annotation counts, raw agreement rate, unresolved/supported disagreement
case ids, high-risk review coverage, and label-source/source-locator provenance
so agents can tell whether a report is still a synthetic seed fixture or a
benchmark-grade human-reviewed slice.

When `--output-dir` is used, experiment manifests also preserve compact
`support_release_*` fields such as `support_release_status`,
`support_release_next_action`, `support_release_blocking_case_ids`, and
`support_release_label_high_risk_unreviewed` for release dashboards without
loading the full result JSON.
False-support reports include `false_support_analysis.review_plan` with
`recommended_annotation_packets`, `recommended_annotation_case_ids`, and per-phase
`annotation_packet.command_template` / `command_template` fields, so agents can
turn supported-overcall blockers or weak-support overcalls into blinded review
packets without inventing commands. These packets are review assignments only;
they do not change labels or permit accepting `supported` predictions.
Reports also include `support_set_policy`, a deterministic fixture that checks
claim-level aggregation boundaries such as multiple weak citations remaining
tentative and contradictions dominating the aggregate. Release gates also check
support-set policy case ids, case-type/language coverage, and artifact manifest
summary fields so those aggregation boundaries cannot disappear silently.

The seed support data is split into `train`, `dev`, and
`test` so calibration and final reporting can be separated. It is a regression
fixture, not a final human-reviewed benchmark. The default support eval backend
is `fixture`, which checks deterministic report plumbing rather than model
quality; use `--backend production` for model-backed metrics.

## Label-provenance sidecars

Optional
label-provenance sidecars can record annotator counts, adjudication status,
disagreements, and source locators separately from the compact seed cases.
Sidecar gates can also require high-risk cases to be human-reviewed globally or
by language with `--min-high-risk-reviewed-by-language LANG=N`, require dual
annotation, cap unresolved disagreements, and enforce a minimum raw
dual-annotator agreement rate before a report is treated as benchmark-grade.
The gate metrics include `high_risk_case_count_by_language`,
`high_risk_reviewed_by_language`, `high_risk_unreviewed_by_language`, and
the language/case-type cross tables
`high_risk_case_count_by_language_case_type`,
`high_risk_reviewed_by_language_case_type`, and
`high_risk_unreviewed_by_language_case_type` so agents can assign review
packets for specific gaps such as Chinese contradictions or full-text
boundaries without re-parsing the sidecar summary.
They also include `full_text_required_case_count`,
`full_text_required_unreviewed_by_language`,
`full_text_required_unreviewed_case_ids`, `policy_boundary_case_count`,
`policy_boundary_unreviewed_by_language`, and
`policy_boundary_unreviewed_case_ids` for abstract/full-text and weak
citation-set aggregation boundaries, where limited evidence must not be
silently promoted to full claim support. Label provenance metrics such as
`label_source_counts`, `reviewed_by_label_source`,
`unreviewed_by_label_source`, `reviewed_source_locator_count`, and
`published_benchmark_source_locator_count` make the seed-vs-human-review and
source-locator coverage visible in release evidence.

Pass `--output-dir experiments --run-id <name>` to either eval script to save a
standardized experiment folder with `result.json`, `config.json`, and
`manifest.json` for reproducible tables and release evidence. Support eval
manifests summarize label-provenance gate fields under stable
`support_label_*` keys, including `support_label_gate_ok`,
`support_label_label_source_counts`, `support_label_human_reviewed`,
`support_label_dual_annotated`, `support_label_raw_dual_agreement_rate`,
`support_label_unresolved_disagreements`,
`support_label_supported_disagreement_case_ids`,
`support_label_high_risk_case_count_by_language_case_type`,
`support_label_high_risk_reviewed_by_language_case_type`,
`support_label_high_risk_unreviewed_by_language_case_type`,
`support_label_full_text_required_unreviewed`,
`support_label_policy_boundary_unreviewed`, and
`support_label_published_benchmark_source_locator_count`.
`scripts/compare_support_baselines.py` writes a compact comparison table for the
deterministic fixture row and the zero-model heuristic baseline, including
quality-gate status, high-risk error bucket counts, and
`false_support_risk_slices` / `top_false_support_risk_slice` for prioritizing
the most dangerous support overcalls. Support-review manifests also retain
`false_support_ok_to_accept_supported`,
`false_support_block_acceptance_count`,
`false_support_block_acceptance_case_ids`, and
`false_support_review_before_accepting_case_ids`. The comparison artifact also carries the
same `support_set_policy` fixture and manifest summary fields, so citation-set
aggregation regressions are visible beside evidence-level baseline regressions.

## Annotation packets

Generate or complete a provenance sidecar draft with:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --include-context \
  --output data/eval/support_eval_label_sidecar.draft.json
```

For independent human labeling, use a blinded annotation packet so reviewers do
not see dataset gold labels:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet \
  --priority high \
  --split test \
  --output experiments/support-label-packet-high-risk-test.json \
  --instructions-output experiments/support-label-packet-high-risk-test-instructions.md
```

Add `--unreviewed-only` to avoid assigning cases that already have human-review
provenance in the sidecar, or use `--review-status single_annotator` to assign
second-reviewer batches for cases that already have one label. Add
`--limit-per-language N`, `--limit-per-case-type N`, or
`--limit-per-evidence-scope N` when a small reviewer batch should stay balanced
across languages, high-risk families, or evidence scopes instead of only taking
the first filtered rows. Each packet includes a machine-readable deterministic
`packet_id` plus `packet_summary` with case ids and counts by language, case
type, evidence scope, split, priority, and current review status for release evidence. The summary uses
stable keys such as `case_count_by_language`, `case_count_by_case_type`, and
`case_count_by_evidence_scope`, plus `case_count_by_review_status` for assigning
single-reviewer, second-reviewer, and adjudication batches.
The `--audit` report also includes `recommended_packets` with ready-to-run
commands for balanced high-risk first review, language-specific high-risk
review, language-and-case-type high-risk slices, full-text-boundary first
review, citation-set policy-boundary first review, and second-reviewer batches
when `single_annotator` cases exist.

When an eval backend fails the support quality gate, turn its triage queue into
a blinded reviewer packet directly:

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

The packet follows `review_queue` order and adds `review_queue_rank` as an
assignment-priority field, but it still omits hidden gold labels, adjudicated
labels, prior annotator labels, and model predictions.

The instruction sheet tells reviewers how to label conservatively without
exposing hidden gold or adjudication fields. Merge completed packets back
conservatively; conflicts are reported instead of silently changing gold labels,
and `merge_report.source_packet_ids` records which reviewer packet ids supplied
the annotations:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --merge-annotation-packet experiments/completed-support-label-packet.json \
  --output data/eval/support_eval_label_sidecar.merged.json
```

Apply resolved adjudications explicitly after reviewer discussion:

```bash
python3 scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.merged.json \
  --apply-adjudications experiments/resolved-support-label-adjudications.json \
  --output data/eval/support_eval_label_sidecar.adjudicated.json
```

## Full command matrix

```bash
python3 scripts/eval_verification.py       # offline, deterministic existence/metadata eval
python3 scripts/eval_support.py            # deterministic support fixture eval, no model downloads
python3 scripts/eval_support.py --report   # fixture report with case-type/evidence-scope breakdowns
python3 scripts/eval_support.py --report --split test --quality-gate
python3 scripts/eval_support.py --split test --backend heuristic --quality-gate --review-queue-only
python3 scripts/eval_support.py --split test --backend heuristic --quality-gate --review-queue-only --review-queue-limit 5
python3 scripts/eval_support.py --backend heuristic --report --split test
python3 scripts/eval_support.py --backend production --report --split test  # requires [models] and cached/downloadable weights
python3 scripts/eval_support.py --validate-only  # dataset schema/provenance/coverage gate only
python3 scripts/eval_support.py --validate-only --label-sidecar data/eval/support_eval_label_sidecar.json --min-high-risk-reviewed-by-language zh=0
python3 scripts/eval_verification.py --output-dir experiments --run-id verification-smoke
python3 scripts/eval_support.py --report --split test --quality-gate --output-dir experiments --run-id support-smoke
python3 scripts/compare_support_baselines.py --split test --min-high-risk-reviewed-by-language zh=0 --output-dir experiments --run-id support-baselines-smoke
```

## Package and release smokes

```bash
python3 scripts/smoke_package.py           # fresh-venv source install smoke, including python -m citeguard
python3 scripts/smoke_package.py --install-mode wheel  # fresh-venv wheel install smoke
python3 scripts/smoke_package.py --install-mode sdist  # fresh-venv source distribution smoke
python3 scripts/smoke_package.py --install-mode wheel --extra mcp --with-deps --mcp-stdio-smoke  # verifies MCP extra deps and installed stdio entry point
python3 scripts/release_package_gate.py    # package + public-api + error-code + MCP stdio/error contracts + CLI error + source-outage + live-source-health + compliance + agent-skill + batch examples + support-label + benchmark-claim release gate; add --require-build-tools before publishing
python3 scripts/release_package_gate.py --skip-install-smoke --include-mcp-extra-smoke --require-mcp-extra-smoke
python3 scripts/release_package_gate.py --skip-install-smoke --include-mcp-stdio-smoke --require-mcp-stdio-smoke
python3 scripts/release_package_gate.py --skip-install-smoke --include-published-smoke-plan --include-published-mcp-smoke-plan
python3 scripts/release_package_gate.py --skip-install-smoke --include-testpypi-smoke-plan --include-testpypi-mcp-smoke-plan
python3 scripts/release_package_gate.py --skip-install-smoke --include-testpypi-smoke-run --include-testpypi-mcp-smoke-run  # after TestPyPI artifacts are visible
python3 scripts/release_package_gate.py --skip-install-smoke --include-published-smoke-run --include-published-mcp-smoke-run  # after PyPI artifacts are visible
python3 scripts/smoke_published_package.py --version 0.1.0  # dry-run post-publish PyPI/TestPyPI smoke, including version, CLI help/fixture verify/support/batch/extract, CLI error-contract, and License-File metadata
python3 scripts/smoke_published_package.py --version 0.1.0 --extra mcp --require-extra-import mcp --mcp-stdio-smoke  # dry-run installed MCP stdio smoke plan
```

## MCP stdio smoke

Run an offline end-to-end stdio smoke test when the MCP SDK is installed:

```bash
python3 scripts/smoke_mcp.py
python3 scripts/smoke_mcp.py --require-sdk  # CI/release: fail if the MCP SDK is missing
```

The smoke test starts the installed `citeguard-mcp` console entry point when
available, initializes an MCP client session, lists tools, calls
`citeguard_status_tool`, checks the fixture `source_health.sources[]` item
contract and `retry_delay_seconds` provenance, verifies a fixture citation, runs
one fixture-backed `verify_citation_tool` `not_found` safety check to ensure
unresolved citations remain high-risk without being called fake or fabricated,
runs one fixture-backed audit batch with `review_summary`, runs one
fixture-backed claim-support check plus one
citation-set support-audit check with `review_summary`, calls
`search_counterevidence_tool` for an offline review lead, and checks structured
expected-error payloads without contacting live scholarly sources. If the MCP
SDK is missing, the default command prints a clear skip message; `--require-sdk`
turns that into a failure for CI and release checks. The core package supports
Python 3.9+, but the MCP SDK requires Python 3.10+; run real MCP stdio
acceptance from a Python 3.10+ environment. If your system `python3` is still
3.9, create the smoke environment with a specific interpreter such as
`python3.11 -m venv .venv-mcp-smoke`.
