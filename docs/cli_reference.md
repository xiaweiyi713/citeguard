# CLI Reference

CiteGuard CLI commands print JSON on success. Expected usage, input, file, and
JSON parse errors are machine-readable JSON on stderr; see
[`docs/error_codes.md`](error_codes.md). Expected error payloads include
`error.code`, `error.recovery`, and stable `error.next_action` for agent
branching.

## status

```bash
citeguard status
python -m citeguard status
citeguard status --check-sources
citeguard status --check-sources --health-query "Attention Is All You Need"
```

Shows local configuration and dependency readiness without querying live
scholarly sources or loading model weights by default. The top-level
`schema_version` and nested `source_health.schema_version` fields version the
machine-readable status contract. With `--check-sources`,
CiteGuard probes each configured live source with a lightweight query and reports
per-source `available`, `empty`, or `unavailable` status plus structured failure
details when a source times out, rate-limits, or fails. Probe output includes
`cache_hit` so agents can distinguish cached success from a fresh live response
without treating HTTP cache replay as a source outage. `source_health.summary`
counts each status, lists `sources_configured`, `sources_checked`,
`sources_responded`, `sources_unchecked`, `sources_available`,
`sources_failed`, and `invalid_sources`, and exposes `degraded`,
`all_checked_sources_failed`, summary-level `failure_count` and
`failure_details`, `failure_kind_counts`, and `failure_kind_sources`, stable
`recovery_code` values such as `timeout`, `source_unavailable`, or
`invalid_input`, and a stable `next_action` such as `continue`,
`inspect_source_health`, `retry_or_check_source_health`, or `fix_configuration`.
Use `--health-query` to override the
probe query for a project-specific known paper. Status output also includes
`remote_evidence_policy`, which exposes whether landing-page evidence harvesting
is enabled, whether non-HTTP URLs are allowed, and which gated-source host
suffixes are blocked. `http_user_agent` shows the User-Agent used for live
source requests. `cache_status` is a non-sensitive cache-inspection snapshot with
`schema_version`, `entries`, `entry_prefixes`, timestamp bounds, `size_bytes`,
`inspect_ok`, and stable `next_action`; it does not expose raw cache queries.
`polite_access` is a machine-readable compliance hint for live scholarly-source
usage. It reports `contact_email_configured`, the `contact_env_var`
(`CITEGUARD_MAILTO`), which configured sources require a contact email
(`configured_contact_required_sources`, currently OpenAlex/Crossref), whether
the current mode is `compliant`, and a stable `next_action` (`continue` or
`fix_configuration`). Each source item also includes `polite_access.status`, so
agents can ask the user to configure a real contact email before live
OpenAlex/Crossref runs without treating this as citation evidence.
When `CITEGUARD_MAILTO` is configured, it includes that contact
email.
When optional landing-page evidence harvesting is enabled, publisher or DOI page
timeouts are record-level evidence provenance, not source-level citation
resolution failures. A metadata record that resolves successfully can include
`metadata.evidence_harvest_failures` entries with `stage=remote_evidence`,
`code`, `kind`, `status_code`, `url`, `error`, and `cache_hit` so agents can say
snippet/full-text-adjacent evidence was unavailable without calling the citation
missing or fake.

Live source adapters normalize sparse or oddly shaped metadata conservatively.
For example, Crossref records with missing `container-title`, partial
`issued.date-parts`, non-object author entries, or string-valued `title` fields
are kept usable without inventing missing venue/year values. Semantic Scholar
records with null `abstract` / `venue`, string-valued `year`, non-object author
entries, or non-object `externalIds` are handled the same way. arXiv Atom entries
with malformed dates or missing author names remain usable, while completely
blank entries are skipped. Treat missing fields as incomplete metadata, not evidence
that a citation is fabricated.

## verify

```bash
citeguard verify \
  --title "Attention Is All You Need" \
  --author "Ashish Vaswani" \
  --year 2017 \
  --arxiv-id 1706.03762
```

Accepted citation fields:

| flag | meaning |
|---|---|
| `--raw-text` | Free-text citation. |
| `--title` | Paper title. |
| `--author` | Author name; repeat for multiple authors. |
| `--year` | Publication year. |
| `--venue` | Venue, journal, conference, or repository. |
| `--doi` | DOI. |
| `--arxiv-id` | arXiv identifier. |

Single verification results include `next_action`, a stable machine-readable
action (`keep`, `review_metadata`, `resolve_identifier_or_replace`,
`disambiguate_identifier`, `inspect_source_health`, or
`retry_or_check_source_health`). Use it for agent branching; keep
`explanation` and `suggested_citation` for user-facing context.

## audit

```bash
citeguard audit examples/citations.json
citeguard audit refs.jsonl
citeguard audit manuscript.md
citeguard audit refs.json --high-risk-only
```

Input can be either:

- a JSON array of citation objects
- JSONL, one citation object per line

Citation object fields are validated before lookup. String fields such as
`title`, `doi`, and `arxiv_id` must be strings; `authors` must be a list of
strings; `year` may be an integer or digit string. Invalid fields return
`invalid_input` with `details.field` and, for batch items, `details.index`.
Invalid batch file shapes include `details.command`, `details.expected`, and
`details.received`; non-object items also include 1-based `details.index`.
JSON/JSONL parse errors include `details.command`, `details.line`, and
`details.column` when the command is known.
Missing or unreadable input files return `file_error` with
`details.field=path`, `details.command`, `details.filename`, and
`details.errno`.

Returns a summary and per-citation verification results. For non-JSON files,
`audit` first extracts citation candidates from Markdown, LaTeX/BibTeX, DOCX,
or plain text references.

Batch audit output includes `review_summary` and `risk_ranking`, sorted
highest-risk first. `review_summary` gives full-batch counts for high/medium/low
risk, next-action counts, and the top risk indexes for review queues. Use
`--high-risk-only` to return only high-risk results while preserving the full
summary and review-summary counts. Each risk-ranking row includes `next_action`, a stable
machine-readable action for agents (`keep`, `review_metadata`,
`resolve_identifier_or_replace`, `disambiguate_identifier`,
`inspect_source_health`, or `retry_or_check_source_health`), plus a
human-readable `recommendation`. Verification results include `sources_failed` and
`source_failure_details` when a live source times out, rate-limits, or fails with
an HTTP/network error. They also include `sources_available`, which is
`sources_checked` minus `sources_failed`, and `sources_responded`, which only
lists sources that returned candidate records. They also include
`source_failure_mode` (`none`, `partial_outage`, or `all_sources_failed`) and
`outage_limited`; when every checked source fails, `not_found` is treated as an
inconclusive low-confidence result rather than evidence of fabrication.
Non-error results can include `recovery_code` from the stable error-code
registry, such as `ambiguous_citation`, `timeout`, or `source_unavailable`, so
agents can choose the next step without parsing prose.

## extract

```bash
citeguard extract examples/references.md
citeguard extract paper.tex --format latex
citeguard extract bibliography.bib --format bibtex
citeguard extract manuscript.docx
```

Prints a JSON list of citation candidate objects that can be saved and passed to
`citeguard audit`. The extractor is conservative: it looks for reference
sections, LaTeX `\bibitem`, and BibTeX entries rather than trying to infer every
in-text citation.

## cache

```bash
citeguard cache inspect
citeguard cache inspect --path data/logs/verification_cache.sqlite
citeguard cache export --deterministic --output replay_fixture.json
citeguard cache clear
```

`cache inspect` returns the cache schema version, entry count, counts by cache
key prefix, and file size without exposing raw queries. `cache export` turns
cached resolved records into a JSON fixture suitable for
`CITEGUARD_FIXTURE_CITATIONS`; with `--output`, stdout reports a manifest with
schema version, cache entry count, entry-prefix counts, oldest/newest cache
timestamps, export timestamp, output path, and exported record count, while the
file contains records only. Exported records include
`metadata.cache_provenance` with the cache operation, source, query, timestamp,
and raw match score. Use `--deterministic` with `--output` to strip timestamp-only
record provenance while preserving source, query, and raw match score, producing
a stable records-only replay fixture. `cache clear` deletes cached lookup/search
rows and preserves cache metadata.

## support

```bash
citeguard support \
  --claim "The Transformer relies entirely on attention." \
  --title "Attention Is All You Need" \
  --arxiv-id 1706.03762
citeguard support \
  --claim "A claim that requires body-text evidence." \
  --title "A verified paper title" \
  --full-text "A short lawful excerpt from the paper body."
citeguard support \
  --claim "A claim that requires body-text evidence." \
  --title "A verified paper title" \
  --full-text-file lawful_excerpt.txt
citeguard support \
  --claim "A claim that requires body-text evidence." \
  --title "A verified paper title" \
  --full-text-file lawful_local_paper.pdf
```

Checks whether the cited paper supports a claim using title/abstract/source
metadata and any caller-provided evidence snippets. Use `--full-text` or
`--full-text-file` only for files or short excerpts you are allowed to provide;
CiteGuard does not bypass paywalls or scrape gated content. UTF-8 text files are
read directly. Local PDF files are supported when `pypdf` or `PyPDF2` is
installed; use `python -m pip install "citeguard[pdf]"` to install the packaged
PDF extra. If no PDF extractor is available, CiteGuard returns a structured
`invalid_input` error with `details.field=full_text_file` and
`details.dependency=pypdf`. Invalid `full_text_file` values in batch commands
also include `details.command` and 1-based `details.index`, so agents can point
the user to the exact claim/citation item. Missing or unreadable evidence files
return `file_error` with `details.field=full_text_file`, `details.filename`,
and the same batch `details.command` / `details.index` context. Without deep
model dependencies, CiteGuard falls back to a labelled heuristic mode. Output
includes `evidence_scope` so agents can
distinguish title, abstract, metadata snippet, full-text,
mixed-with-full-text, or no evidence. If configured model backends are installed
but fail to load or run, support output includes `model_failure_details` entries
with `error_code=model_unavailable` and continues with available fallback
evidence scoring. If the cited paper cannot be resolved, `resolution` includes
the same `sources_available`, `source_failure_mode`, `outage_limited`,
`sources_failed`, and `source_failure_details` fields as citation verification,
so agents can distinguish source outage from normal insufficient evidence.
Support results include `next_action`; unresolved or ambiguous support
resolutions also include `recovery_code` when a stable recovery code is
available.

## counterevidence

```bash
citeguard counterevidence \
  --claim "Method M improves task T." \
  --top-k 5
```

Searches configured scholarly sources for records that may contain
counter-evidence for a claim. Output includes generated `queries`, a richer
`query_plan` with each query's role and rationale, per-query `query_results`,
ranked candidate records, source health diagnostics, stable `next_action`, and
an `interpretation` reminder. Candidate rows include `matched_queries`,
`matched_query_roles`, and `match_rationales` so reviewers can see whether a
lead came from the original claim query, an improvement-negation probe, a
support-negation probe, or an absolute-claim exception probe.

Candidates are review leads only: they are not proof of contradiction, and an
empty result is not proof that no counter-evidence exists. Run support checks on
promising candidates before rewriting claims or replacing citations. When
candidates are returned, `next_action=review_counterevidence_leads`; when
sources fail before any candidate is found,
`next_action=retry_or_check_source_health`.

## support-audit

```bash
citeguard support-audit examples/claim_citations.json
citeguard support-audit examples/claim_citations.jsonl
citeguard support-audit examples/claim_citations_full_text.json
citeguard support-audit examples/claim_citations.json --high-risk-only
citeguard support-audit examples/claim_citations.json --with-counterevidence
```

Input can be JSON array or JSONL. Each item requires `claim`. It may use either
of two shapes:

- single-citation item: citation fields such as `title`, `raw_text`, `doi`, or
  `arxiv_id` at the top level.
- citation-set item: `citations`, a non-empty list of citation objects, when a
  single claim is supported by multiple cited papers.

Optional support evidence fields are accepted on either a single-citation item
or inside each `citations` object:

- `abstract`: known abstract text.
- `evidence_text`: generic caller-provided evidence snippet or list of snippets.
- `full_text`, `full_text_excerpt`, or `full_text_excerpts`: lawful full-text
  excerpt string or list of excerpts, tagged as `evidence_scope=full_text`.
- `full_text_file`, `full_text_files`, `full_text_excerpt_file`, or
  `full_text_excerpt_files`: path string or list of local lawful text/PDF
  evidence files, also tagged as `evidence_scope=full_text`. PDF extraction uses
  optional `pypdf`/`PyPDF2`; missing extraction dependencies are structured
  `invalid_input` errors. Invalid file-path field types in batch inputs include
  `details.index`; missing or unreadable files return `file_error` with
  `details.filename`; nested citation-set items also include
  `details.citation_index`.
- `evidence_chunks`: advanced list of `{text, source_field, source_url,
  evidence_scope}` objects.

Support-audit output also includes `review_summary` and `risk_ranking`;
contradicted claims and unresolved/ambiguous citations are high-risk, while weak
support and insufficient evidence receive recommendations to inspect full text or
revise the claim. `review_summary` gives full-batch risk counts, next-action
counts, and top high-risk indexes so agents can build a compact review plan.
Each risk-ranking row includes a stable `next_action` such as
`keep_claim`, `resolve_citation_identity`, `disambiguate_identifier`,
`retry_or_check_source_health`, `tighten_claim_or_inspect_full_text`,
`inspect_full_text_or_find_stronger_citation`, or
`rewrite_or_replace_evidence`. Each support result and risk item includes
`counterevidence_review`,
`counterevidence_reason`, and `counterevidence_recommendation`; this is a
conservative review signal, not proof that a separate counter-evidence search has
already been run.
Citation-set results include `input_mode=citation_set`, aggregate `support_mode`,
supporting/contradicting citation counts, and per-citation child `results`.
Use `--with-counterevidence` to run that search for review-worthy items and
attach `counterevidence` reports to the relevant results and risk-ranking rows.
Use `--counterevidence-top-k` to limit candidates per claim.

## support-set

```bash
citeguard support-set examples/citations.json \
  --claim "Citation auditing should verify existence, metadata, and claim support."
citeguard support-set refs.jsonl --claim "A single claim may cite multiple papers."
citeguard support-set refs.json --claim "A risky claim." --with-counterevidence
```

Input can be JSON array or JSONL. Each item is a citation object with `title`,
`raw_text`, `doi`, or `arxiv_id`; it may also include the optional evidence
fields listed above. The command runs evidence-scope-aware support checks for
one claim across all citations and returns an aggregate verdict,
per-citation results, supporting/contradicting evidence snippets, `risk`, and a
recommendation. Contradictions dominate the aggregate verdict; otherwise any
strong support makes the set supported, while weak-only evidence remains
tentative. The aggregate also includes `evidence_scope`; current live checks are
abstract/metadata-level unless a source adapter or caller-provided excerpt
supplies full-text spans.
Support-set output includes `support_mode` (`single_strong_support`,
`multiple_strong_support`, `single_weak_support`, `multiple_weak_support`,
`contradiction_dominates`, or `insufficient_evidence`), plus
`supporting_citation_count` and `contradicting_citation_count`. Treat
`multiple_weak_support` as tentative corroboration, not as a strong-support
upgrade.
For weak, insufficient, or contradicted aggregates, `counterevidence_review`
marks the citation set for full-text or replacement review.
Use `--with-counterevidence` to attach possible counter-evidence candidates to
review-worthy aggregates; tune the number of candidates with
`--counterevidence-top-k`. These candidates are leads only, not contradiction
verdicts.

## Output

Use `--compact` after any subcommand for single-line JSON:

```bash
citeguard status --compact
```

Batch commands return:

```json
{
  "summary": {
    "verified": 1,
    "metadata_mismatch": 0,
    "not_found": 1,
    "ambiguous": 0
  },
  "results": []
}
```
