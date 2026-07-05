# Changelog

## Unreleased

- Added public `citeguard.cli` and `citeguard.mcp.server` entry points.
- Added JSONL support for `citeguard audit` and `citeguard support-audit`.
- Added `citeguard extract` plus direct `citeguard audit` support for Markdown,
  LaTeX/BibTeX, DOCX, and plain text reference extraction.
- Added batch `risk_ranking`, recommendations, and `--high-risk-only` filtering
  for citation and claim-support audits.
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
- Added support-labeling guidelines for future human-reviewed claim-support
  benchmark expansion.
- Added support-label sidecar maturity diagnostics for dual-label disagreement
  pairs and supported-label disagreement case ids.
- Added a release gate option for blocking benchmark claims when supported-label
  disagreements remain unresolved.
- Added high-risk support-label review coverage metrics and a
  `--min-high-risk-reviewed` sidecar gate for release readiness checks.
- Expanded the CiteGuard agent skill with client-specific MCP setup notes,
  structured-error recovery guidance, and safe wording examples for ambiguous,
  metadata-mismatch, not-found, outage, and claim-support results.
- Added release metadata guard tests for console scripts, distribution manifests,
  and public `citeguard.*` import hygiene.
- Added example batch input files for citation and claim-support audits.
