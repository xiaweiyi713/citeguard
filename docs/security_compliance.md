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
  evidence, not as proof the citation is unavailable or fabricated.
- Configure `CITEGUARD_MAILTO` with a real contact email for polite OpenAlex and
  Crossref usage. Live-source HTTP clients include that contact in the
  User-Agent as `mailto:<email>` when configured.
- Respect source rate limits. Prefer cached/offline fixtures for development,
  tests, demos, and repeated eval runs. The HTTP client retries transient
  `429`/`5xx` failures briefly and respects `Retry-After` with a short cap for
  interactive use.
- Live HTTP adapters expose machine-readable diagnostics (`last_error_code`,
  `last_error_kind`, `last_status_code`, `last_url`, and `last_cache_hit`) so
  agents can distinguish timeout, rate-limit, HTTP, network, and cached-response
  states without parsing prose.

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
