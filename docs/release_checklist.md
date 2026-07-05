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
  ```

  This runs fresh-venv wheel and source-distribution install smokes, checks
  package archive cleanliness, verifies expected release files, runs the
  `project_metadata_contract` source-file gate, runs the
  `legacy_src_shim_contract` to keep the legacy `src` package thin and
  `citeguard.*`-forwarding, records `cache_replay_fixture` by exporting a
  deterministic cache fixture twice and replaying it offline, records
  `cli_error_contract` by running real `python -m citeguard` failures for
  `verify_missing_citation`, `audit_missing_file`, and
  `support_audit_invalid_jsonl`, records `source_outage_safety` so all-source
  failures stay `not_found`, low-confidence, `outage_limited`, and routed to
  `retry_or_check_source_health` instead of fabrication overclaims, records
  `agent_skill_contract` so the packaged skill keeps proactive triggers,
  forbidden behaviors, Codex/Claude Code/Cursor setup notes, response templates,
  MCP payload examples, and safe wording examples, records
  `batch_workflow_examples` by running the packaged extraction, citation-audit,
  claim-support audit, JSONL, citation-set, and high-risk-only example workflows
  against an offline fixture, runs the
  `support_label_sidecar_gate` provenance check, records its structured
  `thresholds`, `metrics`, and `failures`, records `support_review_queue` and
  `support_review_queue_annotation_packet` so the fixture queue and heuristic
  blinded packet path are release-smoked, checks the built artifact
  distribution metadata contract, and runs PEP 517 `python -m build` plus
  `python -m twine check` when release tools are installed. The MCP extra gate
  records `mcp_extra_wheel_install_smoke` in the release summary and should be
  run on Python 3.10+. The MCP stdio gate records `mcp_stdio_smoke` in the same
  machine-readable summary; with `--require-mcp-stdio-smoke`, missing MCP
  dependencies or Python <3.10 are release failures instead of local skips.
  The published-package plan gate records `published_package_smoke_plan` and
  `published_mcp_smoke_plan` as dry-run JSON summaries so the post-publish
  PyPI/TestPyPI install commands are checked before artifacts are uploaded.

- Inspect the wheel contents and verify `citeguard`, `src`, docs, examples, and
  skill files intended for distribution are present.

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
  python scripts/smoke_package.py --install-mode wheel --extra mcp --with-deps
  ```

  This installs the core package from the source tree and from a freshly built
  wheel and source distribution, checks that release artifacts contain the
  public package, MCP module, legacy compatibility shim, entry point metadata,
  PyPI-facing distribution metadata contract, docs, examples, eval fixtures,
  skill files, and scripts, checks public imports, rejects generated/local files
  such as `__pycache__`, `.pyc`, `.pyo`, `.DS_Store`, and `.venv` contents,
  and, for the MCP release path on Python 3.10+, verifies that the wheel's `mcp`
  extra installs the upstream MCP SDK and allows `citeguard.mcp.server` to import.
  verifies the `citeguard` and `citeguard-mcp` console entry points, and runs
  both `citeguard status` and `python -m citeguard status` without live
  scholarly queries.

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
  severity and recommended action, not a model-quality claim. The report should include `support_set_policy` so
  citation-set aggregation boundaries are checked alongside evidence-level
  cases. The baseline comparison table should include at least the deterministic
  `fixture` row and the zero-model `heuristic` row, with heuristic limitations
  visible in the diagnostics. The label-sidecar gate should report coverage
  `1.0`; keep `--min-human-reviewed`, `--min-high-risk-reviewed`, and
  `--min-dual-annotated` at `0` for the synthetic seed set, then raise them when
  a human-reviewed subset exists. Keep language-specific placeholders such as
  `--min-high-risk-reviewed-by-language zh=0` in CI/release commands, then raise
  them when claiming language-specific benchmark readiness. The gate metrics
  expose `high_risk_case_count_by_language`,
  `high_risk_reviewed_by_language`, and
  `high_risk_unreviewed_by_language` for release triage. Raise
  `--min-high-risk-reviewed` first for contradiction, hard-negative,
  full-text-required, and contradiction-set cases.
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
  audit report's `recommended_packets` entries to preserve the exact commands
  used for balanced first-review, language-specific high-risk, and second-reviewer
  packets in release evidence.

- Run production support eval when model dependencies and cached/downloadable
  weights are available:

  ```bash
  python scripts/eval_support.py --backend production --report --split test --quality-gate
  ```

- If releasing local PDF full-text evidence support, verify the optional extra
  installs cleanly in a fresh environment:

  ```bash
  python -m pip install -e ".[pdf]"
  citeguard support --help
  ```

- Run the MCP stdio smoke on Python 3.10+ with the MCP extra installed:

  ```bash
  python -m pip install -e ".[mcp]"
  python scripts/smoke_mcp.py --require-sdk
  ```

## Documentation

- Update `CHANGELOG.md`.
- Confirm `README.md` quick start works from a fresh editable install.
- Confirm `docs/cli_reference.md`, `docs/mcp_setup.md`,
  `docs/error_codes.md`, and `docs/security_compliance.md` match current CLI and
  MCP behavior.
- Check example files:
  - `examples/citations.json`
  - `examples/claim_citations.json`
  - `examples/claim_citations.jsonl`
  - `examples/references.md`
- Check cache replay:

  ```bash
  citeguard cache export --deterministic --output /tmp/citeguard-replay.json
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
  python scripts/smoke_published_package.py --version 0.1.0 --extra mcp --require-extra-import mcp --run
  ```

  The first command is a dry-run that prints the exact install command and
  post-publish checks as JSON without touching the network. Use `--run` only
  after the package is visible on the target index. For TestPyPI release
  rehearsal, include both indexes so CiteGuard can come from TestPyPI while
  dependencies come from PyPI:

  ```bash
  python scripts/smoke_published_package.py \
    --version 0.1.0 \
    --extra mcp \
    --require-extra-import mcp \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple \
    --run
  ```
