# Troubleshooting CiteGuard

Use `citeguard status` for CLI setups or `citeguard_status_tool` for MCP setups
before changing configuration. Do not diagnose source outages from a citation
verdict alone.

## `citeguard-mcp` is not found

**Likely cause:** the package is not installed in the Python environment used
by the MCP client, or that environment is older than Python 3.10.

```bash
python -m pip install --upgrade citationguard
python --version
citeguard-mcp
```

For an isolated command, use `uvx --from citationguard citeguard-mcp`. A source
checkout can use `python -m pip install -e .`.

## MCP reports `model_unavailable`

Existence and metadata verification still work. Claim-support checking is using
the labeled heuristic fallback.

```bash
python -m pip install "citationguard[models]"
citeguard models warmup
citeguard status
```

## `source_unavailable`, `timeout`, or `outage_limited=true`

These results are inconclusive, not evidence that a citation is fabricated.
Inspect `sources_failed`, `failure_kind_counts`, `retry_after_seconds`, and
`error.retryable`. Set a real `CITEGUARD_MAILTO` for polite OpenAlex/Crossref
access, then retry only after the recommended delay.

## A correct reference is `ambiguous`

Provide a DOI or arXiv identifier. CiteGuard deliberately abstains when strong
title matches conflict on year or when an authority lookup fails. It will not
replace a correct reference with a suspicious mirror record.

## A local evidence file returns `file_error`

`full_text_file` is restricted to the server working directory and roots in
`CITEGUARD_ALLOWED_FILE_ROOTS`. Symlinks are resolved before checking. Keep the
file under an allowed root, use a supported text/PDF format, and keep it below
the reported size/page limits. Do not broaden roots to system directories.

## A remote evidence URL is rejected

Remote evidence is off by default. When enabled, CiteGuard rejects non-HTTP
URLs, credentials in URLs, localhost, private/link-local/reserved IPs, DNS
answers that are not globally routable, gated-source hosts, and unsafe redirect
targets. Supply a lawful local excerpt instead; do not bypass the check.

## A batch is rejected or slow

Batches are limited to 100 rows. Split larger inputs into stable numbered
chunks and preserve global indexes. CLI commands accept `--jobs 1..16`; MCP
batch tools accept `max_workers`. Each scholarly adapter remains serialized to
respect its polite-access interval. `batch_execution` is a completion snapshot,
not streaming progress.

## Cache errors or stale-looking results

```bash
citeguard cache inspect
citeguard cache export --deterministic --output replay.json
citeguard cache clear
```

The cache is namespaced by package/config/source identity. Positive and negative
results have separate TTLs. Use `CITEGUARD_CACHE=:memory:` for a disposable run.

## Still blocked

Capture the JSON error (redacting API keys and private text), `citeguard status`
output, package version, Python version, and the minimal citation fields needed
to reproduce the issue. Do not upload copyrighted full text.
