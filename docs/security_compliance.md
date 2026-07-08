# Security and Compliance Boundaries

CiteGuard is a citation-verification assistant, not a legal authority, research
integrity tribunal, or substitute for human review.

## Source Access Policy

- CiteGuard uses open scholarly metadata sources such as OpenAlex, Crossref,
  arXiv, and Semantic Scholar.
- CiteGuard does not scrape CNKI, Wanfang, or other gated scholarly platforms.
- CiteGuard must not bypass paywalls, login walls, CAPTCHAs, robots.txt, or
  publisher access controls.
- Full-text support checks may use short excerpts supplied by the user or by a
  lawful open source adapter. Do not place private manuscripts, reviewer notes,
  or paywalled body text in public fixtures.
- CLI `--full-text-file` and JSON `full_text_file` inputs are local user-provided text/PDF readers, not crawlers.
  Use them only for files you are allowed to process, and do not commit those excerpt or PDF files unless they are
  redistributable fixtures. Local PDF extraction never downloads remote full
  text and must not be used to bypass access controls.
- Remote landing-page evidence harvesting is disabled by default. When enabled,
  it should remain timeout-limited and conservative. The harvester skips
  non-HTTP URLs and explicitly blocked gated-source hostnames such as CNKI,
  Wanfang, and CQVIP.
- Publisher or DOI landing-page failures are recorded as
  `metadata.evidence_harvest_failures` with `stage=remote_evidence` when
  metadata resolution succeeds. Treat these as missing snippet/full-text-adjacent
  evidence, not as proof the citation is unavailable or fabricated. Rate-limited
  landing pages preserve `retry_after_seconds` when the source provides a
  `Retry-After` hint. Non-HTML responses use `kind=non_html_response`, and HTML
  pages with no extractable paragraph/meta evidence use
  `kind=no_extractable_evidence`.
- Configure `CITEGUARD_MAILTO` with a real contact email for polite OpenAlex and
  Crossref usage. Live-source HTTP clients include that contact in the
  User-Agent and source API `mailto` parameters when configured; placeholder or
  empty values are not sent.
- Respect source rate limits. Prefer cached/offline fixtures for development,
  tests, demos, and repeated eval runs. The HTTP client retries transient
  `429`/`5xx` failures briefly and respects numeric or HTTP-date `Retry-After`
  with a short cap for interactive use.
- Live HTTP adapters expose machine-readable diagnostics (`last_error_code`,
  `last_error_kind`, `last_status_code`, `last_url`, `last_final_url`,
  `last_redirected`, `last_cache_hit`, `last_attempt_count`,
  `last_retry_count`, `last_retry_after_seconds`, and
  `last_retry_delay_seconds`) so agents can distinguish timeout, rate-limit,
  HTTP, network, malformed JSON, redirects, capped retry waits, and
  cached-response states without parsing prose. Malformed source JSON is reported as
  `code=source_unavailable`, `kind=invalid_json`, not as a user input parse
  error.
- `citeguard status --check-sources` exposes source-level health for OpenAlex,
  Crossref, arXiv, and Semantic Scholar, including `sources_checked`,
  `sources_responded`, `sources_failed`, failure-kind counts, and Semantic
  Scholar `SEMANTIC_SCHOLAR_API_KEY` configuration status. Summary-level
  `retry_guidance=wait_before_retry`, `retry_after_seconds`, and
  `retry_after_sources` preserve rate-limit wait hints, while
  `retry_delay_seconds` and `retry_delay_sources` preserve the actual capped
  client waits used during retries without requiring agents to parse every
  failure detail. The summary-level `confidence_effect` and
  `interpretation` fields make source limitations explicit;
  `source_outage_lowers_confidence_not_fabrication_evidence` is the stable
  reminder that an outage lowers confidence without proving fabrication.
- Resolved live-source records include `metadata.metadata_quality` for sparse
  source fields. `missing_fields` should be presented as incomplete metadata;
  `confidence_effect=missing_metadata_lowers_confidence_not_fabrication_evidence`
  means missing fields lower confidence without proving fabrication.

## Interpretation Policy

- `not_found` means CiteGuard could not verify a citation in the checked sources.
  It is not proof that a citation is fake.
- `source_unavailable` or `timeout` should lower confidence and prompt retry or
  stronger identifiers, not accusations. When verification output sets
  `outage_limited=true`, treat the result as inconclusive even if the verdict is
  `not_found`.
- `insufficient_evidence` means available abstract-level evidence did not confirm
  the claim. It is not a full-text non-support judgment.
- `supported` is the riskiest false positive. Agents should preserve confidence,
  evidence scope, and source provenance when presenting support results.

## Data Handling

- Cache files may contain resolved citation metadata from public sources.
- Use `citeguard cache inspect` for non-sensitive counts and
  `citeguard cache clear` before sharing a workspace when needed.
- Do not place private manuscripts, reviewer notes, or unpublished bibliographies
  in public examples or fixtures.

## Responsible Use Statement

CiteGuard is designed to help writers and agents become more skeptical about
citations. Final decisions about research integrity, plagiarism, misconduct,
copyright, licensing, or publication suitability remain with qualified humans
and the relevant institutions.
