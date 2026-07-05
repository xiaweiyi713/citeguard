# Changelog

## Unreleased

- Added public `citeguard.cli` and `citeguard.mcp.server` entry points.
- Added JSONL support for `citeguard audit` and `citeguard support-audit`.
- Added `citeguard extract` plus direct `citeguard audit` support for Markdown,
  LaTeX/BibTeX, DOCX, and plain text reference extraction.
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
- Added annotation-packet `packet_summary` coverage metadata for review-batch
  provenance.
- Added deterministic annotation-packet `packet_id` values for reproducible
  reviewer-batch archives.
- Added `merge_report.source_packet_ids` to preserve reviewer-batch provenance
  after annotation-packet merges.
- Added high-risk case-count-by-language metrics to support-label gates so
  release checks can report reviewed and unreviewed language coverage in one
  place.
- Added language-specific high-risk audit failures for support-label sidecar
  readiness checks, so reviewer assignment can block on unreviewed Chinese or
  other language-specific high-risk cases.
- Expanded the synthetic support eval seed set to 36 evidence-level cases with
  additional high-risk hard-negative, contradiction, and full-text-required
  boundaries for benchmark-provenance overclaims, source-outage fabrication
  inferences, and abstract-only eligibility claims.
- Added Chinese source-outage/not-found safety benchmark cases covering
  unsafe fabrication-confidence overclaims, Crossref timeout hard negatives,
  and rate-limit/not-found contradiction examples.
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
- Added a reusable agent response template for batch audit summaries, action
  queues, high-risk filtering indexes, evidence-scope limits, and next steps.
- Added release metadata guard tests for console scripts, distribution manifests,
  and public `citeguard.*` import hygiene.
- Added a legacy import deprecation signal plus public API migration notes so
  new code can standardize on `citeguard.*` while older imports keep working.
- Refreshed the roadmap around the current agent-auditor package status,
  implemented MCP/batch/cache/source-health foundations, and remaining
  benchmark/full-text/release gaps.
- Added example batch input files for citation and claim-support audits.
