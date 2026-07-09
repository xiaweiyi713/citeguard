# Release Checklist

Use this checklist before publishing CiteGuard as a PyPI package, MCP tool, or
agent skill bundle.

## Package Metadata

- Confirm `pyproject.toml` has the correct version, authors, license, Python
  requirement, classifiers, project URLs, optional extras, and console scripts.
- Build from a clean checkout:

  ```bash
  python -m pip install --upgrade build twine
  python -m build
  python -m twine check dist/*
  ```

- Run the consolidated release package gate:

  ```bash
  python scripts/release_package_gate.py --require-build-tools --min-high-risk-reviewed-by-language zh=0
  python scripts/release_package_gate.py --skip-install-smoke --include-mcp-extra-smoke --require-mcp-extra-smoke
  python scripts/release_package_gate.py --skip-install-smoke --include-mcp-stdio-smoke --require-mcp-stdio-smoke
  python scripts/release_package_gate.py --skip-install-smoke --include-published-smoke-plan --include-published-mcp-smoke-plan
  python scripts/release_package_gate.py --skip-install-smoke --include-testpypi-smoke-plan --include-testpypi-mcp-smoke-plan
  python scripts/release_package_gate.py --skip-install-smoke --include-testpypi-smoke-run --include-testpypi-mcp-smoke-run
  python scripts/release_package_gate.py --skip-install-smoke --include-published-smoke-run --include-published-mcp-smoke-run
  ```

  This runs fresh-venv wheel and source-distribution install smokes, checks
  package archive cleanliness, verifies expected release files, runs the
  `project_metadata_contract` source-file gate, including public-only package
  discovery so published artifacts discover `citeguard.*` without the legacy
  `src` namespace, runs the
  `legacy_src_shim_contract` to keep the legacy `src` package thin and
  `citeguard.*`-forwarding, records `public_api_contract` so README, tests,
  scripts, user-facing docs, and `citeguard.*` code stay free of legacy
  namespace imports, records `cache_replay_fixture` by exporting a
  deterministic records-only cache fixture twice, replaying it offline, exporting
  a manifest-wrapped replay fixture, exporting an operation-filtered lookup
  fixture, and confirming source/query/raw match score provenance survives
  timestamp stripping and replay loading while filtered manifests, inspect
  output, and clear output keep total and selected cache counts separate;
  filtered `cache inspect` / `cache clear` expose
  non-sensitive counts and preserve schema metadata, records
  `error_codes_contract` so `citeguard.errors`, `docs/error_codes.md`,
  recovery guidance, and `next_action` mappings remain synchronized for agents,
  records `configuration_contract` so `docs/configuration.md`, README, runtime
  status fields, environment variables, and cache/source/model configuration
  guidance stay synchronized,
  records `mcp_error_contract` so direct MCP tool errors use the shared
  `ok=false` schema with stable recovery and `next_action` fields, and records
  `cli_error_contract` by running real `python -m citeguard` failures for
  `verify_missing_citation`, `audit_missing_file`, and
  `support_audit_invalid_jsonl`, records `source_outage_safety` so all-source
  failures stay `not_found`, low-confidence, `outage_limited`, and routed to
  `retry_or_check_source_health` instead of fabrication overclaims, records
  `counterevidence_safety_contract` so counter-evidence search remains a
  review-lead workflow with `next_action=review_counterevidence_leads`, not a
  contradiction verdict or permission to rewrite citations, records
  `full_text_evidence_boundary_contract` so full-text support remains
  local/user-provided opt-in evidence and abstract-only results are not upgraded,
  records `support_set_aggregation_contract` so multiple weak citation-set
  evidence stays `multiple_weak_support` with
  `next_action=tighten_claim_or_inspect_full_text`, and records
  `live_source_health_contract` so OpenAlex, Crossref, arXiv, and Semantic
  Scholar health summaries keep `sources_checked`, `sources_responded`,
  `sources_failed`, failure-kind counts, `attempt_count` / `retry_count` /
  `retry_after_seconds` / `retry_delay_seconds` diagnostics, summary-level
  `retry_after_sources`, `retry_delay_sources`,
  `retry_guidance=wait_before_retry`, `confidence_effect`,
  `interpretation=source_outage_lowers_confidence_not_fabrication_evidence`,
  aliases, and Semantic Scholar API-key status stable for agents,
  records
  `security_compliance_contract` so security docs, `CITEGUARD_MAILTO` polite
  access states, fixture bypass status, blocked gated-source suffixes, and the
  disabled-by-default remote evidence policy remain machine-checkable, records
  `agent_skill_contract` so the packaged skill keeps proactive triggers,
  forbidden behaviors, Codex/Claude Code/Cursor setup notes, response templates,
  MCP payload examples, and safe wording examples, records
  `batch_workflow_examples` by running the packaged extraction, citation-audit,
  claim-support audit, caller-provided full-text support-audit, JSONL,
  citation-set, LaTeX `\input` to local `.bib`, generated `.bbl` extraction,
  DOCX reference extraction/audit/support-audit/support-set, and high-risk-only
  example workflows against an offline fixture,
  checking extracted reference-file `source_*` / `input_source_*` provenance,
  `review_summary.source_traceability`, and
  `filtered.omitted_review_summary.source_traceability`,
  runs the
  `support_label_sidecar_gate` provenance check, records its structured
  `thresholds`, `metrics`, and `failures`, including
  `full_text_required_unreviewed_by_language`,
  `full_text_required_unreviewed_case_ids`,
  `policy_boundary_unreviewed_by_language` and
  `policy_boundary_unreviewed_case_ids` for abstract/full-text and weak
  citation-set aggregation review readiness, records
  `sidecar_case_provenance.missing_count` and
  `sidecar_case_provenance.missing_case_ids` so dataset rows missing from the
  sidecar are visible before benchmark claims, verifies the audit `review_plan`
  via `review_plan_smoke` so first-review, second-review, adjudication, and
  release-gate tightening remain machine-checkable, generates the balanced
  `recommended_packets` first-review annotation packet, and checks that the
  blinded packet includes review phase, packet purpose, packet digest,
  review-status counts, plus a `hidden_fields` audit list without leaking hidden
  gold, adjudicated, or prediction fields as case keys; the same smoke also
  validates language-and-case-type slice packet counts and `--lang` /
  `--case-type` command arguments, then smoke-generates one slice packet and
  verifies its `packet_summary.case_count_by_language` and
  `packet_summary.case_count_by_case_type`, and records
  label-provenance
  metrics such as `label_source_counts`, `reviewed_by_label_source`,
  `unreviewed_by_label_source`, `reviewed_source_locator_count`, and
  `published_benchmark_source_locator_count` so seed-vs-human-review and source
  locator coverage stay explicit, records `benchmark_claim_safety` so
  release-facing docs cannot make unqualified human-reviewed benchmark claims
  while the sidecar still reports `human_reviewed: 0`, records
  `support_review_queue` and `support_review_queue_annotation_packet` so the
  fixture queue, heuristic blinded packet path, `review_protocol` assignment
  contract, and independent-review instructions are release-smoked, checks the built artifact
  distribution metadata contract, and runs PEP 517 `python -m build` plus
  `python -m twine check` when release tools are installed. The MCP extra gate
  records `mcp_extra_wheel_install_smoke` in the release summary, installs the
  wheel with `.[mcp]`, and runs the installed `citeguard-mcp` stdio smoke on
  Python 3.10+. The default `mcp_stdio_smoke_contract` gate checks that
  `scripts/smoke_mcp.py` still covers initialize, list_tools, fixture-backed
  verification, caller-provided full-text support evidence, full-text
  support-audit evidence, status, high-risk filtering, and structured errors.
  The `ci_mcp_smoke_contract` gate checks that `.github/workflows/ci.yml`
  contains a Python 3.10+ `mcp-smoke` job that installs `.[mcp]`, runs the MCP
  extra install smoke, runs the required MCP stdio release gate, and executes
  `python scripts/smoke_mcp.py --require-sdk`.
  The MCP stdio gate records
  `mcp_stdio_smoke` in the same machine-readable summary; with
  `--require-mcp-stdio-smoke`, missing MCP dependencies or Python <3.10 are
  release failures instead of local skips.
  The published-package plan gate records `published_package_smoke_plan` and
  `published_mcp_smoke_plan`, `testpypi_package_smoke_plan`, and
  `testpypi_mcp_smoke_plan` as dry-run JSON summaries so the post-publish
  PyPI/TestPyPI install commands are checked before artifacts are uploaded.
  After artifacts are visible on the target index, the optional
  `published_package_smoke_run`, `published_mcp_smoke_run`,
  `testpypi_package_smoke_run`, and `testpypi_mcp_smoke_run` gates execute the
  same installed-package smoke in a fresh venv and record `check_count`,
  `failed_checks`, `venv_dir`, and `smoke_cwd` in the release summary. The
  release summary includes `config_errors`. Non-empty `config_errors` fail the
  plan or run.

- Inspect the wheel contents and verify `citeguard`, docs, examples, and skill
  files intended for distribution are present, and that published artifacts do
  not include the legacy `src` compatibility namespace.

## Test Gates

- Run the standard library test suite:

  ```bash
  python -m unittest discover -s tests -v
  ```

  This includes release metadata guardrails that check public console scripts,
  package-distribution manifests, public docs/tests/scripts for accidental
  legacy internal package imports, public `citeguard.*` implementation files for
  accidental legacy-package dependencies, package archive cleanliness, and
  documented stable error codes.

- Run the package install smoke from a fresh virtual environment:

  ```bash
  python scripts/smoke_package.py
  python scripts/smoke_package.py --install-mode wheel
  python scripts/smoke_package.py --install-mode sdist
  python scripts/smoke_package.py --install-mode wheel --extra mcp --with-deps --mcp-stdio-smoke
  ```

  This installs the core package from the source tree and from a freshly built
  wheel and source distribution, checks that release artifacts contain the
  public package, MCP module, entry point metadata, PyPI-facing distribution
  metadata contract, docs, examples, eval fixtures, skill files, and scripts,
  checks public imports, rejects generated/local files such as `__pycache__`,
  `.pyc`, `.pyo`, `.DS_Store`, `.venv` contents, and the legacy `src`
  compatibility namespace, and confirms the MCP extra can launch the installed
  `citeguard-mcp` stdio entry point through the offline MCP client smoke.
  For the MCP release path on Python 3.10+, it verifies that the wheel's `mcp`
  extra installs the upstream MCP SDK, imports `citeguard.mcp.server`, verifies
  the `citeguard` and `citeguard-mcp` console entry points, runs both
  `citeguard status` and `python -m citeguard status` without live scholarly
  queries, and drives the installed stdio server through an offline MCP client.

- Run offline verification eval:

  ```bash
  python scripts/eval_verification.py
  python scripts/eval_verification.py --output-dir experiments --run-id verification-release-smoke
  ```

- Run deterministic support eval and schema/provenance validation:

  ```bash
  python scripts/eval_support.py
  python scripts/eval_support.py --report --split test --quality-gate
  python scripts/eval_support.py --split test --backend fixture --quality-gate --review-queue-only
  python scripts/eval_support.py --split test --backend heuristic --quality-gate --review-queue-only
  python scripts/eval_support.py --split test --backend heuristic --quality-gate --review-queue-only --review-queue-limit 5
  python scripts/eval_support.py --report --split test --quality-gate --output-dir experiments --run-id support-release-smoke
  python scripts/compare_support_baselines.py --split test --min-high-risk-reviewed-by-language zh=0 --output-dir experiments --run-id support-baselines-release
  python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --annotation-packet --priority high --split test --limit 3 --output experiments/support-label-packet-high-risk-test-batch1.json --instructions-output experiments/support-label-packet-high-risk-test-batch1-instructions.md
  python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --merge-annotation-packet experiments/completed-support-label-packet-high-risk-test-batch1.json --output data/eval/support_eval_label_sidecar.merged.json
  python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.merged.json --apply-adjudications experiments/resolved-support-label-adjudications.json --output data/eval/support_eval_label_sidecar.adjudicated.json
  python scripts/eval_support.py --validate-only --label-sidecar data/eval/support_eval_label_sidecar.json --min-sidecar-coverage 1.0 --min-human-reviewed 0 --min-high-risk-reviewed 0 --min-high-risk-reviewed-by-language zh=0 --min-dual-annotated 0 --max-unresolved-disagreements 0 --max-supported-disagreements 0
  ```

  The quality gate should stay conservative for release candidates: false
  support, weak false support, and missed contradictions must be reviewed before
  relaxing thresholds. The fixture `--review-queue-only` output should have an
  empty `review_queue` and `review_queue_summary.count=0`; the heuristic `--review-queue-only` output is a compact
  triage artifact for `quality_gate.review_queue_case_ids` and
  `quality_gate.critical_review_case_ids`, with `review_queue_summary` grouped by
  severity and recommended action. Use `--review-queue-limit` for concise agent
  handoff tables; `review_queue_filtered` must make clear that full queue counts
  remain in `review_queue_summary` and `quality_gate`. The compact payload also
  includes `false_support_analysis.risk_slices`
  / `false_support_analysis.top_risk_slice`,
  `release_blocker_summary.release_blocked`,
  `release_blocker_summary.benchmark_claim_safe`,
  `release_blocker_summary.blocking_case_ids`, and
  `release_blocker_summary.next_action`, and
  `acceptance_guard.ok_to_accept_supported`, not a model-quality claim. The
  release gate also writes a temporary support-eval artifact and fails if its
  `manifest.json` lacks compact fields such as
  `false_support_total_overcall_count`,
  `false_support_ok_to_accept_supported`,
  `false_support_block_acceptance_count`,
  `false_support_block_acceptance_case_ids`,
  `false_support_review_before_accepting_case_ids`, and
  `false_support_top_risk_slice_id`.
  It must also expose compact release-summary fields such as
  `support_release_status`, `support_release_next_action`,
  `support_release_quality_gate_ok`, `support_release_label_sidecar_gate_ok`,
  `support_release_benchmark_claim_safe`, `support_release_blocking_case_ids`,
  `support_release_review_required_case_ids`, `support_release_top_risk_slice_id`,
  and `support_release_label_high_risk_unreviewed` so release dashboards can
  decide from `manifest.json` without expanding the full result payload.
  The report should include `support_set_policy` so
  citation-set aggregation boundaries are checked alongside evidence-level
  cases. The release gate checks support-set case ids, explicit
  case-type/language coverage, and manifest fields such as `support_set_policy_case_count`,
  `support_set_policy_case_types`, `support_set_policy_languages`, and
  `support_set_policy_case_ids`. The baseline comparison table should include at least the deterministic
  `fixture` row and the zero-model `heuristic` row, with heuristic limitations
  visible in the diagnostics, plus `false_support_risk_slices` and
  `top_false_support_risk_slice` for prioritized false-support triage. The
  baseline comparison artifact should also carry `support_set_policy` and the
  same support-set manifest summary fields, so citation-set aggregation policy
  remains release-visible across baseline comparisons. The
  consolidated release gate records this as `support_baseline_comparison`, and
  fails if an active support overcall row lacks a top risk slice or if the saved
  experiment `manifest.json` lacks compact triage summary fields such as
  `false_support_overcall_backends`, `false_support_top_risk_slice_id`, or
  `support_set_policy_case_ids`. It also validates the manifest's
  `support_label_*` fields, including `support_label_human_reviewed`,
  `support_label_dual_annotated`, `support_label_raw_dual_agreement_rate`,
  `support_label_unresolved_disagreements`,
  `support_label_supported_disagreement_case_ids`,
  `support_label_high_risk_case_count_by_language_case_type`,
  `support_label_high_risk_reviewed_by_language_case_type`,
  `support_label_high_risk_unreviewed_by_language_case_type`,
  `support_label_label_source_counts`, and
  `support_label_sidecar_provenance_missing_count` /
  `support_label_sidecar_provenance_missing_case_ids`, and
  `support_label_published_benchmark_source_locator_count`, against
  `label_sidecar_gate.metrics`. The release gate also records
  `support_calibration_artifact` by running
  `scripts/calibrate_support.py --scored-dataset ... --output-dir ... --run-id ...`
  against deterministic cached component scores. This smoke verifies that
  support calibration can produce a standard `support_calibration` experiment
  folder with `result.json`, `config.json`, and `manifest.json`, and that the
  manifest summary exposes `support_calibration_top_f1`,
  `support_calibration_top_precision`, `support_calibration_top_recall`, and
  `support_calibration_top_false_support_rate` for release tables without
  loading local model weights. It also exposes
  `support_calibration_top_false_positive_case_ids` and
  `support_calibration_top_false_negative_case_ids`,
  `support_calibration_top_false_positive_decision_paths`, and
  `support_calibration_top_false_positive_score_summary` so release reviewers
  can jump directly to false-support and false-reject cases and see whether a
  top false support was driven by NLI entailment, a paired-reranker path, or a
  high neutral/low contradiction profile. For model-backed calibration against
  the seed benchmark, use `scripts/calibrate_support.py --support-eval-dataset
  data/eval/support_eval.json --split dev`; `dev` is the default split so
  threshold tuning does not touch held-out `test` results. The
  label-sidecar gate should report coverage
  `1.0`; keep `--min-human-reviewed`, `--min-high-risk-reviewed`, and
  `--min-dual-annotated` at `0` for the synthetic seed set, then raise them when
  a human-reviewed subset exists. Keep language-specific placeholders such as
  `--min-high-risk-reviewed-by-language zh=0` in CI/release commands, then raise
  them when claiming language-specific benchmark readiness. The gate metrics
  expose `high_risk_case_count_by_language`,
  `high_risk_reviewed_by_language`, and
  `high_risk_unreviewed_by_language`, plus
  `high_risk_case_count_by_language_case_type`,
  `high_risk_reviewed_by_language_case_type`, and
  `high_risk_unreviewed_by_language_case_type` so release reviewers can assign
  language-specific contradiction, hard-negative, and full-text-boundary work,
  plus
  `full_text_required_unreviewed_case_ids` and
  `policy_boundary_unreviewed_case_ids`, for release triage. Raise
  `--min-high-risk-reviewed` first for contradiction, hard-negative,
  full-text-required, and contradiction-set cases. The audit also emits
  `full_text_required_unreviewed` plus a matching recommended packet for
  abstract/full-text boundary review, and `policy_boundary_unreviewed` plus a
  matching recommended packet for weak citation-set aggregation cases that
  should be reviewed before claiming multi-citation support readiness. Use
  `--fail-on-full-text-required-unreviewed` before claiming full-text boundary
  readiness, and `--fail-on-policy-boundary-unreviewed` before claiming
  multi-citation support readiness. When annotation packet merge
  exits non-zero, inspect `merge_report.conflicts` and
  `merge_report.adjudication_queue`; the queue preserves reviewer rationales,
  `packet_id`, `packet_case_index`, and blank `adjudication_template` rows so
  supported-label disagreements are resolved explicitly instead of silently
  folded into benchmark labels. Adjudication templates carry
  `source_packet_ids` and `source_packet_metadata`; after
  `--apply-adjudications`, verify `adjudication_report.source_packet_ids`,
  `adjudication_report.source_packet_metadata`, and sidecar notes still identify
  the reviewer packet archive and review phase.
  Keep `--max-unresolved-disagreements 0`; add `--min-raw-dual-agreement-rate` for
  release evidence once dual annotation exists. Use
  `--max-supported-disagreements 0` for release-grade benchmark claims and inspect
  `dual_disagreement_label_pair_counts` and `supported_disagreement_case_ids`
  before publishing benchmark claims; supported-label disagreements require
  explicit adjudication because false support is the highest-risk error.
  Annotation packets must be
  blinded (`--annotation-packet`) and must not expose dataset `gold` or
  `adjudicated_label` fields to reviewers. Generate an annotator instruction
  sheet with `--instructions-output` for each reviewer batch so labeling rules,
  required fields, and immutable fields are documented beside the packet.
  Completed packets must include
  `annotation.annotator_id`; missing ids appear in `merge_report.skipped`, and
  repeated annotator ids for the same case appear as `duplicate_annotator`
  conflicts. Completed packets should be merged with `--merge-annotation-packet`;
  any `merge_report.conflicts` must be adjudicated before raising human-review gates. Apply resolved adjudications
  with `--apply-adjudications`; any `adjudication_report.conflicts` must be
  reviewed before changing dataset gold or provenance. When `--output-dir` is used,
  archive the generated `result.json`, `config.json`, and `manifest.json` with
  release evidence. When merging completed annotation packets, archive
  `merge_report.source_packet_ids` with the source `packet_id` values.

- Review support-label provenance maturity before making benchmark claims:

  ```bash
  python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --audit
  python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --annotation-packet --priority high --split test --output experiments/support-label-packet-high-risk-test.json --instructions-output experiments/support-label-packet-high-risk-test-instructions.md
  python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --annotation-packet --priority high --split test --limit 3 --output experiments/support-label-packet-high-risk-test-batch1.json --instructions-output experiments/support-label-packet-high-risk-test-batch1-instructions.md
  python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --annotation-packet --priority high --split test --unreviewed-only --limit-per-language 1 --limit-per-case-type 1 --limit-per-evidence-scope 1 --output experiments/support-label-packet-high-risk-test-balanced-batch1.json --instructions-output experiments/support-label-packet-high-risk-test-balanced-batch1-instructions.md
  python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --merge-annotation-packet experiments/completed-support-label-packet-high-risk-test-batch1.json --output data/eval/support_eval_label_sidecar.merged.json
  python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.merged.json --apply-adjudications experiments/resolved-support-label-adjudications.json --output data/eval/support_eval_label_sidecar.adjudicated.json
  python scripts/prepare_support_label_sidecar.py --existing-sidecar data/eval/support_eval_label_sidecar.json --audit --fail-on-high-risk-unreviewed --fail-on-high-risk-unreviewed-language zh
  ```

  The seed set is allowed to report `human_reviewed: 0`, but release notes
  should not call it a human-reviewed benchmark until this audit shows reviewed
  cases, the global and language-specific high-risk unreviewed gates pass, a
  filtered high-risk test annotation packet plus any unreviewed-only balanced
  language/case-type/evidence-scope reviewer batches have been archived with their
  deterministic `packet_id` and `packet_summary` coverage metadata, including
  `case_count_by_review_status`, any
  `--review-status single_annotator` second-reviewer batches have been archived, or
  intentionally skipped, and the sidecar gate is raised accordingly. Use the
  audit report's `review_plan.next_phase` and `recommended_packets` entries to
  preserve the exact commands used for balanced first-review,
  language-specific high-risk, language-and-case-type high-risk slices,
  adjudication, release-gate tightening, and second-reviewer packets in release
  evidence. The audit `review_plan` should
  repeat `high_risk_unreviewed_by_language_case_type`, and the
  `first_review_high_risk` phase should expose
  `candidate_case_count_by_language_case_type`, so release reviewers can split
  first-review batches by both language and support-risk category. The release
  gate's `review_plan_smoke.language_case_type_packet_ids` records the expected
  slice packet ids and fails when any nonzero language/case-type gap lacks a
  matching recommended packet. `review_plan_smoke.language_case_type_packet_smoke`
  archives the generated slice packet summary so release evidence proves the
  filter actually selected the intended language and risk category.

- Run production support eval when model dependencies and cached/downloadable
  weights are available:

  ```bash
  python scripts/eval_support.py --backend production --report --split test --quality-gate
  ```

- If releasing local PDF full-text evidence support, verify the optional extra
  installs cleanly from the package artifact and from the source checkout
  rehearsal path:

  ```bash
  python -m pip install "citationguard[pdf]"
  python -m pip install -e ".[pdf]"
  citeguard support --help
  ```

- Run the MCP stdio smoke on Python 3.10+ with the MCP extra installed. For a
  published package smoke, install the public extra; for local release
  rehearsal, keep the editable source-checkout path:

  ```bash
  python3.11 -m venv .venv-mcp-smoke  # or any Python 3.10+ interpreter
  . .venv-mcp-smoke/bin/activate
  python -m pip install "citationguard[mcp]"
  python -m pip install -e ".[mcp]"
  python scripts/smoke_mcp.py --require-sdk
  ```

## Documentation

- Update `CHANGELOG.md`.
- Confirm `README.md` quick start works from a fresh published-package install
  and from a fresh editable source-checkout install.
- Confirm `docs/configuration.md`, `docs/cli_reference.md`,
  `docs/mcp_setup.md`, `docs/error_codes.md`, and
  `docs/security_compliance.md` match current CLI, runtime, and MCP behavior.
- Check example files:
  - `examples/citations.json`
  - `examples/citations.jsonl`
  - `examples/claim_citations.json`
  - `examples/claim_citations.jsonl`
  - `examples/claim_citations_full_text.json`
  - `examples/claim_citations_full_text_file.json`
  - `examples/lawful_full_text_excerpt.txt`
  - `examples/references.md`
- Check cache replay:

  ```bash
  citeguard cache export --deterministic --output /tmp/citeguard-replay.json
  citeguard cache export --deterministic --operation lookup --output /tmp/citeguard-lookup-replay.json
  CITEGUARD_FIXTURE_CITATIONS=/tmp/citeguard-replay.json citeguard status
  ```

## MCP and Agent Skill

- Verify `citeguard-mcp` starts without importing heavy model dependencies.
- Call `citeguard_status_tool` before live verification.
- Confirm expected input errors return the machine-readable error contract.
- Review `skills/citeguard-verify/SKILL.md` for current tool names, trigger
  rules, safety wording, and progressive-disclosure references. Review
  `skills/citeguard-verify/agents/openai.yaml` so Codex-style skill lists show
  the current display name, default prompt, and MCP dependency.

## Safety and Compliance

- Confirm no example or test requires gated sources, paywall bypass, CNKI, or
  Wanfang access.
- Confirm default remote evidence harvesting remains disabled.
- Confirm docs say `not_found` is not proof of fabrication.
- Confirm docs say CiteGuard is not a legal or final research-integrity
  authority.

## Release

- Tag the release after tests pass.
- Publish PyPI artifacts.
- Create a GitHub release with changelog highlights, known limitations, and MCP
  setup notes.
- After publishing, test a fresh install in a new virtual environment:

  ```bash
  python scripts/smoke_published_package.py --version 0.1.0
  python scripts/smoke_published_package.py --version 0.1.0 --run
  python scripts/smoke_published_package.py --version 0.1.0 --extra mcp --require-extra-import mcp --mcp-stdio-smoke --run
  ```

  The first command is a dry-run that prints the exact install command and
  `planned_checks` as JSON without touching the network. The planned checks
  include public `citeguard` / `citeguard-mcp` console entry point metadata,
  installed-version checks against the requested `--version`, public package imports, root facade API checks such as
  `error_code_registry()`, PyPI-facing distribution metadata checks for the
  skeptical-auditor summary, keywords, classifiers, extras, project URLs, and
  `License-File: LICENSE`,
  installed package file checks that reject the legacy namespace, optional
  extra imports, installed `citeguard --help` / `python -m citeguard --help`
  command-shape checks, fixture-backed offline `verify` checks through both
  installed CLI launch paths, fixture-backed offline claim-support checks
  through both installed CLI launch paths, fixture-backed JSONL `audit` /
  `support-audit --high-risk-only` batch checks, Markdown extraction plus
  extracted-reference `audit --high-risk-only` traceability checks, CLI
  error-contract checks for `missing_citation_input` and `invalid_json`, status
  commands, and, when
  `--mcp-stdio-smoke` is set, an offline MCP client session against the
  installed `citeguard-mcp` entry point, including a fixture-backed
  `check_claim_support_set_tool` call that verifies `support_mode_details` and
  its conservative no-unstated-full-text policy. `--mcp-stdio-smoke` requires
  `--extra mcp`; the dry-run reports
  `mcp_stdio_smoke_requires_mcp_extra` as a machine-readable configuration error
  if that extra is missing. In `--run` mode, post-publish checks execute from an
  isolated `smoke-cwd` with `PYTHONPATH` removed so repository-local source files
  cannot mask a failed package install. `--require-extra-import` accepts only
  dotted Python module names; invalid values are reported as
  `invalid_required_extra_import` before any install runs. Use `--run` only after
  the package is visible on the target index. For TestPyPI release
  rehearsal, include both indexes so CiteGuard can come from TestPyPI while
  dependencies come from PyPI:

  ```bash
  python scripts/release_package_gate.py \
    --skip-install-smoke \
    --include-testpypi-smoke-plan \
    --include-testpypi-mcp-smoke-plan
  ```

  After the TestPyPI artifacts are visible, run the real installed-package gate:

  ```bash
  python scripts/release_package_gate.py \
    --skip-install-smoke \
    --include-testpypi-smoke-run \
    --include-testpypi-mcp-smoke-run
  ```

  After the PyPI artifacts are visible, run the real installed-package gate:

  ```bash
  python scripts/release_package_gate.py \
    --skip-install-smoke \
    --include-published-smoke-run \
    --include-published-mcp-smoke-run
  ```

  ```bash
  python scripts/smoke_published_package.py \
    --version 0.1.0 \
    --extra mcp \
    --require-extra-import mcp \
    --mcp-stdio-smoke \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple \
    --run
  ```
