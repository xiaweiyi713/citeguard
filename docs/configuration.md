# Configuration Reference

CiteGuard is conservative by default: live source probes are explicit, remote
landing-page evidence is disabled unless requested, and source outages lower
confidence instead of proving fabrication. This page lists the stable runtime
configuration knobs that agents and release checks can rely on.

## Inspect Configuration

```bash
citeguard status
citeguard status --check-sources
citeguard status --check-sources --health-query "Attention Is All You Need"
python -m citeguard status
```

`citeguard status` prints JSON and does not query live scholarly sources unless
`--check-sources` is set. The payload includes `configured_sources`,
`requested_sources`, `source_health`, `cache_status`, `polite_access`,
`remote_evidence_policy`, `support_models`, and warnings for missing optional
dependencies or unsafe live-source configuration.

`support_models` is machine-readable: it includes `engine`
(`production_ensemble` or `heuristic_fallback`), `deep_models_available`,
`model_dependencies`, `missing_dependencies`, `next_action`, `install_hint`, and
`warmup_command`. Agents should branch on `support_models.next_action`; when it
is `install_or_configure_dependency`, report that claim-support checks are using
the conservative heuristic fallback rather than deep reranker/NLI support.
Quote `support_models.install_hint` for dependency recovery: it recommends
`citeguard[models]` for installed or published packages before the editable
source-checkout fallback.

## Environment Variables

| variable | default | meaning |
|---|---:|---|
| `CITEGUARD_SOURCES` | `openalex,crossref,arxiv` | Comma-separated live metadata sources. Valid names are `openalex`, `crossref`, `arxiv`, `semantic_scholar`, plus aliases `semantic-scholar`, `semanticscholar`, and `s2`. Unknown names are reported as `invalid_input` / `fix_configuration`. |
| `CITEGUARD_CACHE` | `data/logs/verification_cache.sqlite` | SQLite cache path for live verification. Use `:memory:` for process-local tests. |
| `CITEGUARD_FIXTURE_CITATIONS` | empty | JSON or JSONL citation fixture path. When set, live sources are bypassed and `source_health.mode` is `fixture`. |
| `CITEGUARD_MAILTO` | empty | Real contact email used in OpenAlex/Crossref User-Agent strings and `mailto` query params. Empty or placeholder values are not sent; set a real email before live OpenAlex/Crossref runs. |
| `CITEGUARD_HTTP_TIMEOUT` | `10` | Positive integer timeout in seconds for live source HTTP requests. |
| `CITEGUARD_HTTP_RETRIES` | `1` | Non-negative retry count for transient live source HTTP failures. |
| `CITEGUARD_HTTP_RETRY_BACKOFF` | `0.2` | Non-negative base retry backoff in seconds. |
| `CITEGUARD_HTTP_MIN_INTERVAL` | `0` | Non-negative minimum interval in seconds between uncached live-source HTTP requests from the same adapter. Increase this for slower, more polite live runs. |
| `CITEGUARD_REMOTE_EVIDENCE` | `0` | Enables limited remote landing-page evidence harvesting when set to `1`, `true`, `yes`, or `on`. Disabled by default. |
| `CITEGUARD_OA_FULLTEXT` | `0` | Fetches open-access paper bodies for full-text claim support when set to `1`; OA locations only, gated hosts stay blocked, never bypasses paywalls. Disabled by default. |
| `CITEGUARD_DOI_REGISTRY` | `1` | Checks unresolved DOIs against the global doi.org Handle registry (covers all registrars, including China DOI/ISTIC) and reports `doi_registration` on `not_found` results. Set `0` to disable; automatically skipped in offline fixture mode. |
| `CITEGUARD_EVIDENCE_TIMEOUT` | `2` | Positive integer timeout in seconds for optional remote evidence fetching. |
| `SEMANTIC_SCHOLAR_API_KEY` | empty | Optional Semantic Scholar API key. Status reports only whether it is configured. |
| `CITEGUARD_RERANKER_MODEL` | packaged default | Optional reranker model name for deep claim-support mode. |
| `CITEGUARD_NLI_MODEL` | packaged default | Optional NLI model name for deep claim-support mode. |

Invalid numeric values are surfaced in `status.warnings` and appear as `null` in
the corresponding status fields; agents should ask the user to repair the
configuration instead of silently falling back.

## Source Health Contract

`citeguard status --check-sources` reports source-level health with:

- `sources_checked`, `sources_responded`, `sources_available`,
  `sources_failed`, and `sources_unchecked`
- per-source `next_action`, `confidence_effect`, `interpretation`,
  `recovery_code`, `retry_after_seconds`, `retry_delay_seconds`, and
  `retry_guidance` on `source_health.sources[]`
- `failure_details` with `code`, `kind`, `status_code`, `url`, `cache_hit`,
  `final_url`, `redirected`, `attempt_count`, `retry_count`, optional
  `retry_after_seconds` parsed from numeric or HTTP-date `Retry-After`, and
  optional `retry_delay_seconds` for the
  actual capped client wait used before a retry
- `failure_kind_counts` and `failure_kind_sources`
- summary-level `retry_after_seconds`, `retry_after_sources`,
  `retry_delay_seconds`, `retry_delay_sources`, and `retry_guidance`; when
  `retry_guidance=wait_before_retry`, wait at least that many seconds before
  probing those sources again
- `confidence_effect` and `interpretation`
- stable `recovery_code` and `next_action`

If a live source responds with malformed JSON, CiteGuard records
`code=source_unavailable` and `kind=invalid_json` in these fields. Treat that as
a source reliability problem, not as invalid user input and not as evidence that
a citation or claim is fake. When `confidence_effect` is
`partial_source_limited` or `all_sources_unavailable`,
`interpretation=source_outage_lowers_confidence_not_fabrication_evidence`
means the check should be retried or treated as source-limited instead of as a
fabrication finding.

OpenAlex and Crossref require polite contact configuration. arXiv and Semantic
Scholar do not require `CITEGUARD_MAILTO`; Semantic Scholar separately reports
`api_key_configured`.

## Cache And Replay

```bash
citeguard cache inspect
citeguard cache inspect --operation lookup
citeguard cache export --deterministic --output replay_fixture.json
citeguard cache export --deterministic --operation lookup --output lookup_replay_fixture.json
citeguard cache export --deterministic --include-manifest --output replay_fixture.json
citeguard cache clear --operation lookup
citeguard cache clear
```

`cache inspect` exposes non-sensitive counts such as `schema_version`,
`entries`, `entry_prefixes`, `selected_entries`, and
`selected_entry_prefixes` without raw query text. Use `--operation search`,
`--operation lookup`, or `--source SOURCE` to inspect the same filtered view you
plan to export while keeping total and selected counts separate. Deterministic cache
exports strip timestamp-only fields while preserving source, query, normalized
query, record source, and raw match score provenance for offline replay. Use
`--include-manifest` when the fixture file should carry a `fixture_manifest`
next to `records`; `CITEGUARD_FIXTURE_CITATIONS` accepts both manifest-wrapped
JSON fixtures and legacy records-only JSON/JSONL fixtures. Use
`--operation search`, `--operation lookup`, or `--source SOURCE` to export
focused replay fixtures; inspect output and manifests keep total cache entry
counts separate from selected counts. `cache clear` accepts the same filters and
reports `remaining_entries`, so selective cleanup can be audited before a full
clear.

## Safety Boundaries

- Do not configure CiteGuard to scrape gated sources such as CNKI, Wanfang, CQVIP
  or paywalled publisher full text.
- `CITEGUARD_REMOTE_EVIDENCE=1` is an opt-in metadata/landing-page evidence
  helper, not a paywall bypass.
- `not_found`, `source_unavailable`, and `timeout` mean CiteGuard could not
  confirm the citation with available sources. They are not evidence that a
  citation is fabricated.
- Claim support is abstract/metadata-level unless the caller provides lawful
  local excerpts or files via `full_text` / `full_text_file`.
