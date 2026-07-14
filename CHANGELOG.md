# Changelog

## Unreleased

- BEHAVIOR CHANGE: `verify_citation_tool` no longer accepts claim-support
  inputs (`abstract`, `evidence_chunks`, `evidence_text`, `full_text`,
  `full_text_file`); those belong to the claim-support tools. Existence and
  metadata verification never used them.
- Identifier-authority resolution: when a citation carries a DOI/arXiv id, the
  id is now resolved strictly at its home source (Crossref/arXiv) first, with
  one retry. A hit is definitive and beats any title match; a failed authority
  lookup downgrades the verdict to `ambiguous` with `outage_limited=true`
  instead of risking a title-only `metadata_mismatch`. Results expose the new
  `identifier_lookup` field (`kind`/`value`/`source`/`status`).
- Polluted-record defense: same-title candidates that disagree on publication
  year across sources, or best matches that look like hijacked/mirror records
  (greylisted DOI prefixes via `CITEGUARD_SUSPECT_DOI_PREFIXES`, implausible
  citation counts on brand-new years), now degrade to `ambiguous` instead of a
  confident mismatch, and never produce a `suggested_citation`.
- arXiv ids are compared by their version-less base id, so a cited
  `1706.03762` matches a source record carrying `1706.03762v7`.
- Fixed multi-source search ranking: raw source relevance scores (unbounded,
  e.g. OpenAlex values in the thousands) are now squashed to 0-1 so they can
  no longer dominate title similarity.
- Added a golden-case live canary (`scripts/canary_live.py` +
  `data/eval/canary_golden.json`) with a nightly GitHub Actions run that opens
  an issue on verdict drift.
- Multi-source queries now fan out concurrently within a total time budget
  (`CITEGUARD_SOURCE_BUDGET`, default 8 seconds); sources that exceed the
  budget are recorded as `budget_exceeded` failures instead of blocking the
  whole verification.
- BEHAVIOR CHANGE: `build_live_metadata_source` no longer enables landing-page
  evidence harvesting by default (opt in via `harvest_remote_evidence=True` /
  `CITEGUARD_REMOTE_EVIDENCE=1`), aligning the library default with the MCP
  runtime.
- Added opt-in open-access full-text support (`CITEGUARD_OA_FULLTEXT=1`):
  claim-support checks can now fetch the paper body from source-declared OA
  locations (with an official arXiv PDF fallback) and judge claims at
  `evidence_scope=full_text`; gated hosts stay blocked and paywalls are never
  bypassed. Fetch outcomes are reported as `resolution.oa_fulltext` and a
  failed fetch never changes a verdict.
- Added a tag-triggered PyPI trusted-publishing workflow that builds, tests,
  publishes, and attaches artifacts to the GitHub release automatically.

## 0.1.1 - 2026-07-09

- Added GB/T 7714 (Chinese national standard) reference parsing: `[J]/[M]/[C]/[D]`
  style references are now parsed into structured title/authors/venue fields in
  free-text parsing and file extraction, making Chinese bibliographies verifiable.
- Crossref search now skips predominantly-CJK queries (its bibliographic search
  cannot match them); DOI lookups are unaffected.
- Added a registrar-agnostic DOI existence probe: `not_found` results with a
  DOI now include `doi_registration` from the global doi.org Handle registry,
  so papers whose DOIs live outside open sources (e.g. China DOI/ISTIC) can be
  confirmed as real without ever escalating missing metadata to fabrication.
  Disable with `CITEGUARD_DOI_REGISTRY=0`; skipped in offline fixture mode.
- Removed the legacy root-package compatibility shims and `setup.py`; the
  project now builds exclusively from `pyproject.toml` (PEP 517) and both
  source checkouts and release artifacts expose only the `citeguard.*`
  surface.
- Modernized the sdist install smoke to build with `python -m build` instead
  of the removed `setup.py sdist` path.
- Made Chinese the primary `README.md` with a full English companion in
  `README.en.md`; release gates now check the bilingual documentation set.
- Renamed the PyPI distribution to `citationguard` (the `citeguard` name on
  PyPI belongs to an unrelated project). The import package stays `citeguard`
  and the `citeguard` / `citeguard-mcp` console commands are unchanged; README
  warnings explain the mapping.
- Added ruff linting (CI job + config) and relaxed the `[models]` extra pins
  to compatible ranges instead of exact versions.
- Added incremental mypy type checking to CI: four core modules were cleaned
  up and the remaining typed debt is tracked as an explicit override list in
  `pyproject.toml`.
- Fixed `--review-queue-only` output missing the documented `release_summary`
  block.
- Added public `citeguard.cli` and `citeguard.mcp.server` entry points.
- Added JSONL support for `citeguard audit` and `citeguard support-audit`.
- Added `examples/citations.jsonl` plus release-gated audit JSONL smoke coverage.
- Added `citeguard extract` plus direct `citeguard audit` support for Markdown,
  LaTeX/BibTeX, DOCX, and plain text reference extraction.
- Added `citeguard support-audit refs.md --claim "..."` so one claim can be
  checked against citations extracted from Markdown, LaTeX/BibTeX, DOCX, or
  plain text reference files.
- Added release-gated `support-audit refs.md --claim "..." --with-counterevidence`
  coverage so extracted reference-file audits can attach counter-evidence review
  leads while preserving risk-sorted citation indexes.
- Added release-gated `support-set --with-counterevidence` coverage so
  multi-citation claim checks keep aggregate review leads and safe interpretation
  wording in offline package gates.
- Added MCP helper and stdio smoke coverage for
  `check_claim_support_set_tool(include_counterevidence=true)` so agent clients
  verify one-claim/multiple-citation counter-evidence review leads end to end.
- Added post-publish smoke `planned_checks` plus public console entry point
  validation for `citeguard` and `citeguard-mcp` so PyPI/TestPyPI release
  rehearsals protect the installed command surface.
- Added optional post-publish MCP stdio smoke coverage that starts the installed
  `citeguard-mcp` entry point against an offline fixture after installing the
  `mcp` extra from PyPI/TestPyPI.
- Extended post-publish MCP stdio smoke coverage to call
  `check_claim_support_set_tool` and verify `support_mode_details`, including
  conservative no-unstated-full-text support policy fields, from the installed
  package.
- Made post-publish smoke configuration and venv setup failures machine-readable,
  including `mcp_stdio_smoke_requires_mcp_extra` when
  `--mcp-stdio-smoke` is used without `--extra mcp`.
- Made post-publish smoke run installed-package checks from an isolated
  `smoke-cwd` with `PYTHONPATH` removed so repository-local sources cannot hide
  a failed PyPI/TestPyPI install.
- Added post-publish smoke validation for `--require-extra-import`, accepting
  only dotted Python module names and reporting `invalid_required_extra_import`
  before any install runs.
- Added local wheel MCP stdio package smoke coverage so
  `scripts/smoke_package.py --install-mode wheel --extra mcp --with-deps
  --mcp-stdio-smoke` installs the built wheel and drives the installed
  `citeguard-mcp` entry point through an offline MCP client before release.
- Added an agent-skill example for `audit_claim_support_tool` with both
  `include_counterevidence=true` and `high_risk_only=true`, including safe
  wording for omitted-row summaries and review leads.
- Added batch `risk_ranking`, recommendations, and `--high-risk-only` filtering
  for citation and claim-support audits.
- Added batch `review_summary.action_queues` so agents can route identity,
  metadata, evidence, source retry, rewrite/replace, and keep decisions without
  parsing prose.
- Added `filtered.returned_indexes` and `filtered.omitted_indexes` to
  `--high-risk-only` / MCP `high_risk_only` batch outputs for traceability back
  to original inputs.
- Added `filtered.omitted_review_summary` to high-risk filtered batch outputs so
  agents can summarize hidden low/medium-risk queues without expanding every row.
- Added `citeguard support-set` and `check_claim_support_set_tool` for
  abstract-level checks of one claim against multiple cited papers.
- Added machine-readable `evidence_scope` to claim-support outputs so agents can
  distinguish title/abstract/metadata/full-text evidence.
- Expanded the synthetic support eval seed set with provenance fields, hard
  negatives, contradiction examples, supported precision/recall/F1, abstention
  rate, false-support rate, confusion matrices, high-risk support error buckets,
  optional case-type/evidence-scope breakdown reports, and title/metadata/full-text
  scope examples.
- Added a hard-negative support seed for real citation-auditing papers that do
  not support overstrong deployed-agent hallucination-elimination claims.
- Added offline MCP stdio smoke coverage through `scripts/smoke_mcp.py`.
- Added `CITEGUARD_FIXTURE_CITATIONS` for deterministic offline citation fixtures.
- Added cache schema versioning plus `citeguard cache inspect` and `citeguard cache clear`.
- Added `citeguard cache export` for deterministic offline replay fixtures.
- Added cache export provenance for source, query, timestamp, operation, and raw
  match score.
- Made deterministic cache exports strip timestamp-only manifest fields as well
  as record provenance so full JSON payloads are reproducible.
- Added source-level readiness reporting in `citeguard status` / `citeguard_status_tool`.
- Added summary-level source health failure counts and failure details for agent
  retry/configuration decisions.
- Added source health `failure_kind_counts` and `failure_kind_sources` summaries
  so agents can branch on timeout, rate-limit, HTTP, and network failure modes
  without parsing per-source detail lists.
- Added short HTTP retries for transient scholarly source failures plus
  `CITEGUARD_HTTP_RETRIES` and `CITEGUARD_HTTP_RETRY_BACKOFF` status fields.
- Added machine-readable HTTP/source failure diagnostics for timeouts, rate
  limits, HTTP errors, and network failures, surfaced through verification
  result `source_failure_details`.
- Added stable error-code documentation and CLI/MCP setup references.
- Added a public stable error-code registry in `citeguard.errors`, with tests
  keeping the registry and docs synchronized.
- Added structured `file_error` details for cache export output-path failures,
  including `details.field=output` and `details.cache_command=export`.
- Added `details.field`, `details.expected`, and `details.received` to MCP
  batch shape errors so agents can repair malformed `citations` / `items`
  payloads without parsing prose, and extended the MCP stdio smoke to verify
  those details through the real server transport.
- Added support-labeling guidelines for future human-reviewed claim-support
  benchmark expansion.
- Added support-label sidecar maturity diagnostics for dual-label disagreement
  pairs and supported-label disagreement case ids.
- Added a release gate option for blocking benchmark claims when supported-label
  disagreements remain unresolved.
- Added high-risk support-label review coverage metrics and a
  `--min-high-risk-reviewed` sidecar gate for release readiness checks.
- Added support-eval validation for high-risk `test` split coverage so final
  support reports cannot omit weak-support, hard-negative, contradiction, or
  full-text-required boundaries.
- Added grouped `false_support_case_ids` and `weak_false_support_case_ids` in
  support false-overcall analysis for split/case-type/evidence-scope triage.
- Added `false_support_analysis.risk_slices` / `top_risk_slice` and baseline
  comparison `false_support_risk_slices` so contradicted, hard-negative,
  full-text-boundary, test-split, and non-English support overcalls have a
  stable machine-readable review priority.
- Added a default release-gate `support_baseline_comparison` contract so
  baseline rows keep `false_support_risk_slices` / `top_false_support_risk_slice`
  whenever support overcalls are present.
- Added compact `false_support_analysis` to `scripts/eval_support.py
  --review-queue-only` and the release-gate `support_review_queue` contract so
  agent triage payloads expose supported-overcall priority slices without
  expanding the full per-case report.
- Added compact false-support overcall triage fields to experiment
  `manifest.json` summaries so saved support eval and baseline runs expose the
  top risk slice without loading full result payloads.
- Extended the release gate to verify support review-queue and baseline
  artifact manifest summaries keep false-support overcall counts, backend, and
  top risk-slice fields.
- Updated the packaged `citeguard-verify` skill examples to read
  `false_support_analysis.risk_slices` / `top_risk_slice` during support
  benchmark triage and to treat contradicted supported-overcalls as
  release-blocking review items.
- Documented support-eval review-queue and baseline-comparison JSON contracts in
  the CLI reference, including compact `false_support_analysis` and
  `top_false_support_risk_slice` fields for agent triage.
- Added support-eval `review_queue` plus baseline comparison
  `review_queue_case_ids` / `critical_review_case_ids` so agents and
  maintainers can inspect the highest-risk support failures first.
- Added `quality_gate.review_queue_case_ids` and
  `quality_gate.critical_review_case_ids` to support-eval gate failures.
- Added `scripts/eval_support.py --review-queue-only` for compact
  support-failure triage payloads.
- Added a default `support_review_queue` step to the release package gate so
  compact support triage output is checked before release.
- Added `prepare_support_label_sidecar.py --from-review-queue` so support eval
  failure queues can be converted directly into blinded human annotation
  packets without exposing gold labels or backend predictions.
- Added a release-gate smoke for review-queue annotation packets so release
  summaries prove the blinded packet path works and does not expose hidden
  labels or backend predictions.
- Added support-set policy coverage to baseline comparison artifacts and release
  gate manifest checks, keeping citation-set aggregation boundaries visible
  beside evidence-level false-support triage.
- Added support-label audit `policy_boundary_unreviewed` output and a
  release-gated policy-boundary annotation packet smoke for weak citation-set
  cases that must remain tentative instead of being upgraded to full support.
- Added support-label audit `full_text_required_unreviewed` output and a
  release-gated full-text-boundary annotation packet smoke so abstract-level
  support gaps can be reviewed separately before full-text readiness claims.
- Added support-label audit gates
  `--fail-on-full-text-required-unreviewed` and
  `--fail-on-policy-boundary-unreviewed` so release checks can block premature
  full-text or multi-citation support readiness claims.
- Added label-source and source-locator provenance metrics to support sidecar
  validation and the release gate, keeping synthetic seed coverage distinct
  from human-reviewed benchmark evidence.
- Added support-label provenance summaries to experiment `manifest.json`
  artifacts so release tables can show sidecar maturity without opening the
  full result payload.
- Extended the support-baseline release gate to validate those manifest
  `support_label_*` summaries against `label_sidecar_gate.metrics`.
- Added agent-skill guidance and release-gate checks for policy-boundary
  annotation packets, keeping multiple weak citations tentative until reviewed.
- Added an agent-skill full-text-boundary annotation packet example so agents
  keep abstract-only support gaps as insufficient evidence until review.
- Added HTTP attempt/retry diagnostics to live-source failure details and bumped
  the source-health schema so agents can see when CiteGuard already exhausted
  its short retry policy.
- Added a counter-evidence safety release gate so retrieval candidates remain
  review leads, not contradiction verdicts or silent rewrite permission.
- Added a release-gate contract that keeps the legacy `src` package limited to
  thin `citeguard.*` compatibility shims.
- Added a default release-gate public API contract so README, tests, scripts,
  user-facing docs, and `citeguard.*` package code stay on stable public imports
  instead of the legacy namespace.
- Added a release-gate cache replay fixture smoke that exports deterministic
  cache fixtures twice and verifies offline replay without timestamp-only
  provenance leaks.
- Added a default release-gate error-code contract so `citeguard.errors`,
  `docs/error_codes.md`, recovery guidance, `next_action` mappings, and sample
  payload shape stay synchronized for agents.
- Extended the shared error contract with machine-readable `error.retryable`
  and `error.category` fields, and updated the agent skill to branch on those
  fields instead of parsing natural-language error messages.
- Added a default release-gate CLI error contract smoke that runs real
  `python -m citeguard` failures for missing citation input, missing audit
  files, and invalid JSONL support-audit input, then verifies stable
  `schema_version`, `error.code`, `error.recovery`, `error.next_action`, and
  `details` fields.
- Added a default release-gate source-outage safety contract so all-source
  failures stay low-confidence, `outage_limited` `not_found` results with
  `next_action=retry_or_check_source_health`, while source-health summaries keep
  `sources_checked`, `sources_responded`, `sources_failed`, and timeout failure
  kinds separate for agents.
- Added a default release-gate live-source health contract so OpenAlex,
  Crossref, arXiv, and Semantic Scholar aliases, checks, responded/failed
  source lists, timeout/rate-limit failure-kind summaries, and Semantic Scholar
  API-key status stay stable for agent integrations.
- Extended the security/compliance release gate to include Semantic Scholar
  source-health polite-access state, keeping optional API-key configuration
  separate from OpenAlex/Crossref mailto requirements.
- Added a default release-gate security/compliance contract so docs, polite
  `CITEGUARD_MAILTO` status, fixture bypass behavior, gated-source host blocks,
  and disabled-by-default remote evidence policy stay machine-checkable.
- Added a default release-gate agent skill contract so packaged
  `citeguard-verify` instructions keep proactive triggers, forbidden behaviors,
  Codex/Claude Code/Cursor setup notes, response templates, MCP payload
  examples, and safe wording examples for not-found/source-outage cases.
- Added a default release-gate batch workflow examples smoke that runs packaged
  `extract`, `audit`, `support-audit`, JSONL, `support-set`, and
  `--high-risk-only` examples against an offline fixture, then checks summaries,
  action queues, filtered index traceability, and citation-set result shape.
- Added citation-audit `risk_ranking` repair hints (`mismatched_fields`,
  `suggested_citation`, and canonical identifiers) so batch agents can present
  metadata corrections directly from the risk-sorted review queue.
- Added support-audit `risk_ranking` provenance fields (`support_confidence`,
  `support_engine`, `resolution_verdict`, resolved title/year, and evidence
  source name/field/URL) so claim-support batch rows can be displayed without
  expanding full result payloads or inferring the source from field-name
  prefixes.
- Added citation-set aggregate provenance fields (`evidence_scopes`,
  `evidence_source_names`, and `evidence_source_fields`) so support-set and
  support-audit rows can show set-level evidence provenance without expanding
  every child citation result.
- Added a default release-gate benchmark claim safety contract so
  release-facing docs cannot describe the synthetic support seed set as a
  human-reviewed benchmark while label provenance still reports
  `human_reviewed: 0`.
- Added a default release-gate MCP stdio smoke contract so `scripts/smoke_mcp.py`
  must keep initialize/list-tools, offline fixture verification, batch
  high-risk filtering, source-outage safety, and structured error coverage.
- Added language coverage and `by_language` support-eval reporting so English
  and Chinese false-support or missed-contradiction risks can be triaged
  separately.
- Added language breakdowns to support-label `high_risk_review` sidecar
  validation so reviewed and unreviewed high-risk benchmark cases can be
  audited by language before release claims.
- Added `--min-high-risk-reviewed-by-language` sidecar gates for release checks
  that require human review coverage for specific benchmark languages.
- Added a default `support_label_sidecar_gate` step to the consolidated release
  package gate so package releases also validate support-label provenance.
- Made the release gate record structured support-label gate thresholds,
  metrics, and failures instead of requiring agents to parse stdout tails.
- Added `prepare_support_label_sidecar.py --limit-per-language` and
  `--limit-per-case-type` / `--limit-per-evidence-scope` for balanced high-risk
  annotation batches.
- Added `prepare_support_label_sidecar.py --unreviewed-only` so reviewer packets
  can skip cases that already have human-review provenance.
- Added `prepare_support_label_sidecar.py --review-status` for second-reviewer
  and status-specific annotation packets.
- Added annotation-packet `packet_summary` coverage metadata, including
  `case_count_by_review_status`, for review-batch provenance.
- Added support-label audit `recommended_packets` so maintainers and agents can
  turn review-readiness gaps into reviewer-packet commands without parsing prose.
- Added a release-gate smoke that generates the balanced support-label
  `recommended_packets` annotation packet and checks review-status provenance
  without leaking hidden gold, adjudicated, or prediction fields.
- Added `review_phase` and `packet_purpose` metadata to support-label
  annotation packets generated from recommended review-plan commands.
- Added deterministic annotation-packet `packet_id` values for reproducible
  reviewer-batch archives.
- Added `merge_report.source_packet_ids` to preserve reviewer-batch provenance
  after annotation-packet merges.
- Added `source_packet_metadata` to annotation-packet merge and adjudication
  reports so review phase and packet purpose survive conflict resolution.
- Added `merge_report.adjudication_queue` with reviewer rationales and blank
  adjudication templates for unresolved annotation disagreements.
- Added source packet ids and packet case indexes to annotation conflict
  examples so adjudication can trace disagreements back to reviewer batches.
- Added `source_packet_ids` to adjudication templates, reports, and sidecar
  notes so resolved disagreements preserve reviewer-batch provenance.
- Added high-risk case-count-by-language metrics to support-label gates so
  release checks can report reviewed and unreviewed language coverage in one
  place.
- Added high-risk support-label review cross tables by language and case type
  so manifests and release reports can assign contradiction, hard-negative, and
  full-text-boundary review gaps without re-parsing sidecar rows.
- Added language-specific high-risk audit failures for support-label sidecar
  readiness checks, so reviewer assignment can block on unreviewed Chinese or
  other language-specific high-risk cases.
- Expanded the synthetic support eval seed set to 48 evidence-level cases with
  additional high-risk hard-negative, contradiction, and full-text-required
  boundaries for benchmark-provenance overclaims, source-outage fabrication
  inferences, abstract-only eligibility claims, simulated-review causal
  overclaims, reviewer-replacement overclaims, multi-paper weak-evidence
  over-synthesis, model-availability-as-support overclaims, supplemental-material
  full-text boundaries, and Semantic Scholar rate-limit non-existence
  overclaims. The latest contradiction case keeps counter-evidence search leads
  as review signals rather than final contradiction verdicts.
- Expanded citation-set support policy coverage to 6 citation-set policy cases,
  including a Chinese citation-set weak aggregation boundary and a
  source-limited citation-set fabrication boundary.
- Added Chinese source-outage/not-found safety benchmark cases covering
  unsafe fabrication-confidence overclaims, Crossref timeout hard negatives,
  and rate-limit/not-found contradiction examples.
- Expanded the CiteGuard agent skill examples with high-risk-only batch audit
  payloads and structured MCP shape-error repair guidance for agents.
- Added non-gold `review_focus` hints to support-label annotation packets so
  reviewers know which support boundary to inspect without seeing gold labels,
  adjudicated labels, or `label_notes`.
- Added a `source_outage_safety` counter-evidence query role and
  `source_outage_safety_cue` candidate signal for claims that overinterpret
  source outages, timeouts, or `not_found` as fabrication evidence.
- Extended source-outage safety counter-evidence probes to Chinese
  source-outage/not-found overclaims while keeping the same stable role and
  signal fields.
- Expanded the CiteGuard agent skill with client-specific MCP setup notes,
  structured-error recovery guidance, and safe wording examples for ambiguous,
  metadata-mismatch, not-found, outage, and claim-support results.
- Added an agent-skill scenario routing table for bibliographies, generated
  related-work citations, single/multi-citation claim-support checks,
  ambiguity, metadata mismatches, and source-limited results.
- Moved detailed agent-skill MCP payload and wording examples into
  `skills/citeguard-verify/references/examples.md` so the main skill stays
  concise while examples remain packaged.
- Added `skills/citeguard-verify/agents/openai.yaml` with display metadata,
  default prompt, and the CiteGuard MCP stdio dependency for Codex-style skill
  surfaces.
- Added a reusable agent response template for batch audit summaries, action
  queues, high-risk filtering indexes, evidence-scope limits, and next steps.
- Added release metadata guard tests for console scripts, distribution manifests,
  and public `citeguard.*` import hygiene.
- Added a legacy import deprecation signal plus public API migration notes so
  new code can standardize on `citeguard.*` while older imports keep working.
- Converted legacy retrieval and verification package entrypoints into thin
  public `citeguard.*` shims so compatibility imports share the stable public
  export lists.
- Refreshed the roadmap around the current agent-auditor package status,
  implemented MCP/batch/cache/source-health foundations, and remaining
  benchmark/full-text/release gaps.
- Added example batch input files for citation and claim-support audits.
