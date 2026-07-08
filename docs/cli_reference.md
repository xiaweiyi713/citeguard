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
without treating HTTP cache replay as a source outage. HTTP-backed failure
details also include `attempt_count`, `retry_count`, and optional
`final_url` / `redirected` when a DOI resolver or publisher landing page moved
the request before failing. They also include optional `retry_after_seconds`
parsed from numeric or HTTP-date `Retry-After`, plus
optional `retry_delay_seconds` for the actual capped client wait used before a
retry; when `retry_count > 0`, `retry_delay_seconds` is set, or
`retry_after_seconds` is set, the source was already retried briefly or asked
clients to wait, and agents should avoid immediate repeat probes unless the
user explicitly asks.
Each `source_health.sources[]` item also includes source-level `next_action`,
`confidence_effect`, `interpretation`, `recovery_code`, `retry_after_seconds`,
`retry_delay_seconds`, and `retry_guidance`, so agents can route one failed
source without parsing the summary or the failure prose. A per-source
`confidence_effect=source_unavailable` is a reliability state, not evidence that
a citation is fake.
`source_health.summary`
counts each status, lists `sources_configured`, `sources_checked`,
`sources_responded`, `sources_unchecked`, `sources_available`,
`sources_failed`, and `invalid_sources`, and exposes `degraded`,
`all_checked_sources_failed`, summary-level `failure_count` and
`failure_details`, `failure_kind_counts`, `failure_kind_sources`,
`retry_after_seconds`, `retry_after_sources`, `retry_delay_seconds`,
`retry_delay_sources`, and `retry_guidance`, stable
`confidence_effect` values such as `none`, `not_checked`,
`partial_source_limited`, `all_sources_unavailable`, or
`invalid_configuration`, stable `interpretation` values such as
`source_outage_lowers_confidence_not_fabrication_evidence`, `recovery_code`
values such as `timeout`, `source_unavailable`, or `invalid_input`, and a
stable `next_action` such as `continue`,
`inspect_source_health`, `retry_or_check_source_health`, or `fix_configuration`.
When `retry_guidance=wait_before_retry`, agents should wait at least the summary
`retry_after_seconds` before probing the listed `retry_after_sources` again.
If a source reports `retry_after_seconds=0.0`, the wait hint has already expired
or requires no delay; keep the hint for provenance, but follow the ordinary
`retry_or_check_source_health` guidance instead of waiting.
Agents should treat `partial_source_limited` and `all_sources_unavailable` as
confidence-limiting source reliability states, not as evidence that a citation
is fabricated.
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
Semantic Scholar source items expose `api_key_configured` for
`SEMANTIC_SCHOLAR_API_KEY` so agents can distinguish missing credentials from a
source outage. When `CITEGUARD_MAILTO` is configured, it includes that contact
email.
When optional landing-page evidence harvesting is enabled, publisher or DOI page
timeouts are record-level evidence provenance, not source-level citation
resolution failures. A metadata record that resolves successfully can include
`metadata.evidence_harvest_failures` entries with `stage=remote_evidence`,
`code`, `kind`, `status_code`, `url`, `final_url`, `redirected`, `error`,
`cache_hit`, `attempt_count`, and `retry_count`, plus optional
`retry_after_seconds` for rate-limited landing
pages and optional `retry_delay_seconds` for actual capped retry waits, so
agents can say snippet/full-text-adjacent evidence was unavailable without
calling the citation missing or fake.

Live source adapters normalize sparse or oddly shaped metadata conservatively.
For example, Crossref records with missing `container-title`, partial
`issued.date-parts`, non-object author entries, or string-valued `title` fields
are kept usable without inventing missing venue/year values. Semantic Scholar
records with null `abstract` / `venue`, string-valued `year`, non-object author
entries, or non-object `externalIds` are handled the same way. arXiv Atom entries
with malformed dates or missing author names remain usable, while completely
blank entries are skipped. Treat missing fields as incomplete metadata, not evidence
that a citation is fabricated.
Resolved live-source records include `metadata.metadata_quality` with
`present_fields`, `missing_fields`, identifier provenance, completeness, and
`confidence_effect=missing_metadata_lowers_confidence_not_fabrication_evidence`
when sparse source fields should lower confidence without becoming fabrication
evidence.

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
citeguard audit examples/citations.jsonl --high-risk-only
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
`details.field=path`, `details.command`, and `details.filename`; OS-level
failures also include `details.errno`. Malformed DOCX files use the same
machine-readable contract instead of emitting a traceback.

Returns a summary and per-citation verification results. For non-JSON files,
`audit` first extracts citation candidates from Markdown, LaTeX/BibTeX/BBL, DOCX,
or plain text references. Extracted risk-ranking rows carry `input_source_path`,
`input_source_format`, `input_source_index`, `input_source_locator`, and, when
available, `input_source_line_start` / `input_source_line_end`, so
filtered/high-risk tables can still point back to the original reference-file
item and line range.

Batch audit output includes `review_summary` and `risk_ranking`, sorted
highest-risk first. `review_summary` gives full-batch counts for high/medium/low
risk, next-action counts, top risk indexes, and `action_queues` for common agent
work queues: identity resolution, metadata review, evidence review,
rewrite/replace, source retry, input repair, and safe-to-keep indexes. Use
`next_actions` for exact action counts; every stable `next_action` is assigned
to one `action_queues` list for compact routing. `review_summary.source_traceability`
summarizes extracted source-backed rows with `source_paths`, `source_formats`,
`source_indexes`, `review_required_source_locators`, and
`high_risk_source_indexes`, so agents can route repairs back to original
Markdown/LaTeX/BibTeX/BBL/DOCX bibliography items without expanding every risk row.
`recommended_next_steps`
turns those queues into a priority-ordered plan with `first_queue`,
`first_action`, `steps[].{priority, action, queue, count, indexes}`, and
`safe_to_keep_indexes`, so agents can say what to fix first without inferring
priority from prose. `review_summary.suggested_fix_summary` aggregates
`suggested_fix.kind` counts, `confirmation_required_indexes`,
`no_confirmation_required_indexes`, and `missing_suggested_fix_indexes`; its
`auto_apply_allowed=false` policy means agents must propose citation, metadata,
or claim changes for user confirmation instead of silently applying them.
`review_summary.triage_plan` is the one-line batch
decision contract: `status=review_required` means queued rows must be handled
before accepting the batch, `next_action` is always one of the stable
`next_action` registry values, `first_queue` points at the first review queue,
`status=clear` means only low-risk rows remain, and `policy` keeps source retry
inconclusive rather than fabrication evidence. `recommended_next_steps.first_action`
is a compact queue action such as `resolve_identity`; use `triage_plan.next_action`
for stable machine branching.
`--high-risk-only` to return only high-risk results while preserving the full
summary and review-summary counts. The `filtered` block includes
`returned_indexes` and `omitted_indexes`, both using original input indexes, so
agents can map filtered result rows back to the source batch. It also includes
`omitted_review_summary`, which preserves the omitted rows' risk counts,
`next_actions`, `action_queues`, and `recommended_next_steps` for compact
reporting. Each risk-ranking row
includes `next_action`, a stable
machine-readable action for agents (`keep`, `review_metadata`,
`resolve_identifier_or_replace`, `disambiguate_identifier`,
`inspect_source_health`, or `retry_or_check_source_health`), `risk_reason` for
compact "why" columns (`no_strong_match`, `metadata_fields_mismatch`,
`multiple_plausible_matches`, `all_sources_failed`, etc.), plus a
machine-readable `suggested_fix` object (`kind`, `action`,
`requires_user_confirmation`, and any repair-specific fields) and a
human-readable `recommendation`. For `metadata_mismatch` rows, `risk_ranking`
also carries `mismatched_fields`, `suggested_citation`, and canonical title,
year, venue, DOI, and arXiv id fields so agents can show a repair candidate from
the risk-sorted view. Risk rows and verification results include
`canonical_metadata_quality`; risk rows also flatten
`source_metadata_missing_fields` and `source_metadata_confidence_effect` so
compact audit tables can flag sparse source metadata without treating missing
fields as fabrication evidence. Verification results include `sources_failed` and
`source_failure_details` when a live source times out, rate-limits, or fails with
an HTTP/network error. These details preserve `attempt_count`, `retry_count`,
optional `retry_after_seconds`, and optional `retry_delay_seconds`, so agents can
avoid immediate repeat probes after a rate limit. They also include
`sources_available`, which is
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
citeguard extract paper.bbl --format bbl
citeguard extract manuscript.docx
```

Prints a JSON list of citation candidate objects that can be saved and passed to
`citeguard audit`. The extractor is conservative: it looks for reference
sections, LaTeX `\bibitem`, generated `.bbl` files with `\bibitem`, local `.bib`
files referenced by `\bibliography{refs}` or `\addbibresource{refs.bib}`, and
BibTeX entries rather than trying to infer every in-text citation. For LaTeX projects, local
`\input{...}` and `\include{...}` subfiles are followed recursively when they
exist, so a main `paper.tex` can point to a references subfile that then points
to a local `.bib` file. Missing subfiles and remote-looking paths are skipped.
When a pasted bibliography has no heading, numbered or bulleted lines are
extracted only if the completed item contains citation signals such as a DOI,
arXiv id, year, journal, proceedings, or conference. Unnumbered
one-reference-per-line bibliographies are accepted
when a line has a DOI/arXiv id or a stricter author/year/source pattern.
Indented continuation lines under a numbered or bulleted item are folded into
that candidate before those citation signals are evaluated.
BibTeX parsing accepts common
nested-brace fields such as protected-case titles (`{Attention {Is} All You
Need}`), simple `#`-concatenated field values, and local `@string` macros for
field values such as journal or conference names; entries and `@string` macros
may use either outer braces or parentheses. Each extracted candidate includes
`source_type`, `source_format`, `source_index`, and `source_locator`;
candidates loaded from a file also include `source_path` and, when available,
`source_line_start` / `source_line_end`.

## cache

```bash
citeguard cache inspect
citeguard cache inspect --path data/logs/verification_cache.sqlite
citeguard cache inspect --operation lookup
citeguard cache inspect --source openalex
citeguard cache export --deterministic --output replay_fixture.json
citeguard cache export --deterministic --operation lookup --output lookup_replay_fixture.json
citeguard cache export --deterministic --source openalex --output openalex_replay_fixture.json
citeguard cache export --deterministic --include-manifest --output replay_fixture.json
citeguard cache clear --operation lookup
citeguard cache clear --source openalex
citeguard cache clear
```

`cache inspect` returns the cache schema version, entry count, counts by cache
key prefix, selected entry counts, selected prefix counts, active
`inspect_filters`, and file size without exposing raw queries. Use
`--operation search`, `--operation lookup`, or `--source SOURCE` to populate the
selected counts while preserving full `entries` / `entry_prefixes` totals.
`cache export` turns
cached resolved records into a JSON fixture suitable for
`CITEGUARD_FIXTURE_CITATIONS`; with `--output`, stdout reports a manifest with
schema version, cache entry count, entry-prefix counts, oldest/newest cache
timestamps, export timestamp, output path, and exported record count, while the
file contains records only. Exported records include
`metadata.cache_provenance` with the cache operation, source, query, timestamp,
and raw match score. Use `--deterministic` with `--output` to strip timestamp-only
record provenance and timestamp-only manifest fields while preserving source,
query, and raw match score, producing a deterministic records-only fixture that
can be replayed offline with `CITEGUARD_FIXTURE_CITATIONS`. Add
`--include-manifest` to write `{ "fixture_manifest": ..., "records": [...] }`
when the replay file itself should carry cache schema, count, and deterministic
export provenance; fixture loading accepts both this wrapped object and the
legacy records-only list.
Use `--operation search` or `--operation lookup` to build focused fixtures from
one cache row type, and `--source SOURCE` to export only rows produced by a
specific adapter. Inspect output and export manifests keep both total cache
entry counts and selected counts, including `selected_cache_entry_*` export
fields, so filtered fixture runs remain auditable.
`cache clear` accepts the same `--operation search` / `--operation lookup` and
`--source SOURCE` filters. Its JSON output includes `cleared_entries`,
`remaining_entries`, `clear_filters`, and `selected_entry_prefixes`; without a
filter it clears all cache rows.
If the output path cannot be written, the CLI returns `file_error` with
`details.field=output`, `details.command=cache`, `details.cache_command=export`,
`details.filename`, and `details.errno`.
`cache clear` deletes cached lookup/search rows and preserves cache metadata.

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
including any `retry_after_seconds` rate-limit hint and `retry_delay_seconds`
retry provenance, so agents can distinguish source outage from normal
insufficient evidence.
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
ranked candidate records, source health diagnostics, stable `next_action`,
`review_summary`, and an `interpretation` reminder. Candidate rows include `matched_queries`,
`matched_query_roles`, and `match_rationales` so reviewers can see whether a
lead came from the original claim query, an improvement-negation probe, a
support-negation probe, an absolute-claim exception probe, or a
`source_outage_safety` probe for claims that overinterpret source outages,
timeouts, or `not_found` as fabrication evidence, including Chinese
source-outage/not-found overclaims. Candidate `signal` can also be
`source_outage_safety_cue` when the lead explicitly says source failures lower
confidence without proving fabrication. `review_summary` includes
`signal_counts`, `matched_query_role_counts`, `top_candidate`, and
`recommended_next_steps` with stable queues such as
`explicit_contradiction_candidate_indexes`,
`source_outage_safety_candidate_indexes`, and `related_candidate_indexes`, plus
`policy=review_leads_not_contradiction_verdicts` for compact agent triage.

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
citeguard support-audit examples/claim_citations_full_text_file.json
citeguard support-audit examples/references.md --claim "The cited papers support my claim."
citeguard support-audit examples/references.md --claim "The cited papers support my claim." --high-risk-only
citeguard support-audit examples/references.md --claim "The cited papers support my claim." --with-counterevidence
citeguard support-audit examples/claim_citations.json --high-risk-only
citeguard support-audit examples/claim_citations.jsonl --high-risk-only
citeguard support-audit examples/claim_citations.json --with-counterevidence
```

Input can be JSON array or JSONL. Each JSON/JSONL item requires `claim` unless a
default `--claim` is supplied. JSON/JSONL items may use either of two shapes:

- single-citation item: citation fields such as `title`, `raw_text`, `doi`, or
  `arxiv_id` at the top level.
- citation-set item: `citations`, a non-empty list of citation objects, when a
  single claim is supported by multiple cited papers.

With `--claim`, input can also be a Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text
reference file. Non-JSON files are extracted with the same conservative
reference-section parser used by `citeguard extract`, `citeguard audit`, and
`citeguard support-set`; each extracted citation candidate becomes one
claim/citation audit item using the supplied claim. `--high-risk-only` also
works on reference-file input, preserving original extracted-citation indexes in
`filtered.returned_indexes` and summarizing hidden rows in
`filtered.omitted_review_summary`. Extracted support resolutions and risk rows
also include `input_source_path`, `input_source_format`, `input_source_index`,
`input_source_locator`, and, when available, `input_source_line_start` /
`input_source_line_end`.
`--with-counterevidence` also works on reference-file input; it attaches
reference-file counter-evidence review leads to extracted rows with
`counterevidence_review=true` while preserving the extracted-citation indexes in
`risk_ranking`.

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
counts, top high-risk indexes, and `action_queues` so agents can build a compact
review plan without parsing prose. It also includes `recommended_next_steps`,
which orders identity resolution, source retry, evidence/full-text review,
rewrite/replace, metadata review, and safe-to-keep indexes into stable
machine-readable work queues.
`review_summary.triage_plan` mirrors that queue as a compact agent decision:
read `status`, `next_action`, `review_required_indexes`, `high_risk_indexes`,
`medium_risk_indexes`, and `policy` before expanding individual rows.
Each risk-ranking row includes a stable `next_action` such as
`keep_claim`, `resolve_citation_identity`, `disambiguate_identifier`,
`retry_or_check_source_health`, `tighten_claim_or_inspect_full_text`,
`inspect_full_text_or_find_stronger_citation`, or
`rewrite_or_replace_evidence`, plus `risk_reason` values such as
`citation_identity_unresolved`, `available_evidence_is_partial`,
`available_evidence_does_not_confirm_claim`, or
`citation_set_evidence_does_not_confirm_claim`. Risk rows also include
`suggested_fix.kind` values such as `resolve_citation_identity`,
`inspect_full_text_or_find_stronger_citation`, `rewrite_claim_or_replace_evidence`,
or `keep_claim`, with `requires_user_confirmation` whenever an agent should ask
before editing a citation or claim. Single-citation risk rows also include
`support_confidence`, `support_engine`, `resolution_verdict`, `resolved_title`,
`resolved_year`, `evidence_source_name`, `evidence_source_field`, and
`evidence_source_url` so agents can show compact provenance without expanding
the full result or inferring a source from field-name prefixes. Citation-set
risk rows include aggregate `support_confidence`,
`support_engine=citation_set`, `evidence_scopes`, `evidence_source_names`, and
`evidence_source_fields`, so agents can display set-level provenance without
expanding every child result.
Single-citation support results and risk rows also expose
`canonical_metadata_quality`, `source_metadata_missing_fields`, and
`source_metadata_confidence_effect`; citation-set rows aggregate missing fields
and confidence effects across child citations. Treat these as source metadata
completeness signals, not as support or fabrication evidence.
Each support result and risk item includes
`counterevidence_review`,
`counterevidence_reason`, and `counterevidence_recommendation`; this is a
conservative review signal, not proof that a separate counter-evidence search has
already been run.
Citation-set results include `input_mode=citation_set`, aggregate `support_mode`,
`support_mode_details`, supporting/contradicting citation counts,
`evidence_scopes`, `evidence_source_names`, `evidence_source_fields`, aggregate
`input_source_*` lists for extracted reference-file inputs, and per-citation
child `results`.
Use `--with-counterevidence` to run that search for review-worthy items and
attach `counterevidence` reports to the relevant results and risk-ranking rows.
Use `--counterevidence-top-k` to limit candidates per claim.
When `--high-risk-only` is enabled, the `filtered.returned_indexes` and
`filtered.omitted_indexes` arrays preserve the original batch indexes for
traceability. `review_summary.source_traceability` and
`filtered.omitted_review_summary.source_traceability` summarize which extracted
source rows were returned, omitted, or still require review.
`filtered.omitted_review_summary` preserves omitted rows'
`next_actions`, `action_queues`, and `recommended_next_steps`, so agents can
still say whether hidden items were safe to keep, metadata review, or evidence
review rows.

## support-set

```bash
citeguard support-set examples/citations.json \
  --claim "Citation auditing should verify existence, metadata, and claim support."
citeguard support-set refs.jsonl --claim "A single claim may cite multiple papers."
citeguard support-set examples/references.md --claim "One claim backed by a bibliography."
citeguard support-set refs.json --claim "A risky claim." --with-counterevidence
```

Input can be JSON array, JSONL, or a Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text
reference file. Non-JSON files are extracted with the same conservative
reference-section parser used by `citeguard extract` and `citeguard audit`.
Each item is a citation object with `title`, `raw_text`, `doi`, or `arxiv_id`;
JSON/JSONL items may also include the optional evidence fields listed above.
The command runs evidence-scope-aware support checks for one claim across all
citations and returns an aggregate verdict,
per-citation results, supporting/contradicting evidence snippets, `risk`, and a
recommendation. Contradictions dominate the aggregate verdict; otherwise any
strong support makes the set supported, while weak-only evidence remains
tentative. The aggregate also includes `evidence_scope`; current live checks are
abstract/metadata-level unless a source adapter or caller-provided excerpt
supplies full-text spans.
Support-set output includes `support_mode` (`single_strong_support`,
`multiple_strong_support`, `single_weak_support`, `multiple_weak_support`,
`contradiction_dominates`, or `insufficient_evidence`), plus
`supporting_citation_count`, `contradicting_citation_count`, and aggregate
provenance lists `evidence_scopes`, `evidence_source_names`, and
`evidence_source_fields`. `support_mode_details` adds stable per-verdict
indexes such as `supported_indexes`, `weakly_supported_indexes`, and
`contradicted_indexes`, a compact `decision`, and the policy
`contradictions_dominate; multiple_weak_citations_remain_tentative;
no_unstated_multi_hop_or_full_text_support`. Treat `multiple_weak_support` as
tentative corroboration, not as a strong-support upgrade.
For weak, insufficient, or contradicted aggregates, `counterevidence_review`
marks the citation set for full-text or replacement review.
Use `--with-counterevidence` to attach possible counter-evidence candidates to
review-worthy aggregates; tune the number of candidates with
`--counterevidence-top-k`. These candidates are leads only, not contradiction
verdicts.

## Support Eval Scripts

```bash
python scripts/eval_support.py --report --split test --quality-gate
python scripts/eval_support.py --split test --backend heuristic --quality-gate --review-queue-only
python scripts/eval_support.py --split test --backend heuristic --quality-gate --review-queue-only --review-queue-limit 5
python scripts/compare_support_baselines.py --split test
```

The support-evaluation scripts are release and benchmark-triage interfaces, not
normal citation-audit subcommands. They print JSON for agents and CI. With
`--quality-gate`, `scripts/eval_support.py` adds a conservative
`quality_gate` block that fails on false support, weak false support, and missed
contradictions by default. Gate failures expose
`quality_gate.review_queue_case_ids` and
`quality_gate.critical_review_case_ids` so agents can inspect the riskiest
support failures first.

Use `--review-queue-only` when an agent or release script needs compact triage
instead of a full per-case report. The compact payload includes
`release_summary`, `review_queue_summary`, ordered `review_queue` rows,
`support_set_policy`, and
`false_support_analysis`, top-level `acceptance_guard`, plus `abstention_analysis` with
`incorrect_abstention_count`, `correct_abstention_count`, and
`review_case_ids`. It also includes `acceptance_slices`, the fixed high-risk
support slices `contradiction`, `hard_negative`, `full_text_boundary`,
`test_split`, and `non_english`, each with `status`, overcall case ids, policy,
and recommended action even when the slice is clear. Add
`--review-queue-limit N` to return only the first N
risk-ordered `review_queue` rows while preserving full queue counts in
`review_queue_summary`, `quality_gate`, and `review_queue_filtered`. When
`--label-sidecar` is supplied, it also includes
`label_maturity` and `label_sidecar_gate.metrics` with coverage,
human-reviewed and dual-annotation counts, raw dual agreement rate,
unresolved/supported disagreement case ids, high-risk review coverage,
language/case-type cross tables for targeted review assignment,
abstract/full-text boundary coverage, and label-source/source-locator
provenance. The compact `overall` block includes
`support_overcall_count` / `support_overcall_rate` so agents can track both
`supported` and `weakly_supported` overcalls on non-supporting cases. The
analysis includes `total_overcall_count`, `case_ids`,
`false_support_case_ids`, `weak_false_support_case_ids`,
`high_risk_overcall_case_ids`, machine-readable `risk_slices`, and
`top_risk_slice`. `acceptance_guard.ok_to_accept_supported` is false whenever
there are `block_acceptance_case_ids`; `review_before_accepting_case_ids`
records weak false-support overcalls that must be reviewed before being treated
as support. Treat `contradicted_overcalled`,
`hard_negative_overcalled`, and `full_text_boundary_overcalled` as the most
urgent supported-overcall review slices. These slices are release triage, not
proof that a production model is calibrated. When `--output-dir` is used with
this compact mode, the experiment `manifest.json` keeps
`support_release_status`, `support_release_next_action`,
`support_release_quality_gate_ok`, `support_release_label_sidecar_gate_ok`,
`support_release_benchmark_claim_safe`, `support_release_review_top_case_ids`,
`support_release_blocking_case_ids`, `support_release_review_required_case_ids`,
`support_release_top_risk_slice_id`, and
`support_release_label_high_risk_unreviewed`, plus
`false_support_total_overcall_count`, `false_support_risk_slice_count`,
`false_support_ok_to_accept_supported`,
`false_support_block_acceptance_count`,
`false_support_block_acceptance_case_ids`,
`false_support_review_before_accepting_case_ids`,
`false_support_top_risk_slice_id`, and
`false_support_top_risk_slice_case_ids`, plus
`support_acceptance_slice_ids`,
`support_acceptance_blocked_slice_ids`,
`support_acceptance_review_required_slice_ids`, and
`support_acceptance_slice_case_counts` so release tooling can compare saved
support-review runs without loading the full result payload.
The manifest also stores `abstention_total_count`,
`abstention_incorrect_count`, `abstention_correct_count`, and
`abstention_review_case_ids`, and sidecar-backed runs store stable
`support_label_*` maturity fields such as `support_label_dual_annotated`,
`support_label_raw_dual_agreement_rate`,
`support_label_unresolved_disagreements`, and
`support_label_supported_disagreement_case_ids`, plus
`support_label_high_risk_case_count_by_language_case_type`,
`support_label_high_risk_reviewed_by_language_case_type`, and
`support_label_high_risk_unreviewed_by_language_case_type` for archived
language/case-type review gaps.

`scripts/compare_support_baselines.py` compares the deterministic fixture
backend with the zero-model heuristic baseline by default. Each comparison row
includes `quality_gate_ok`, `macro_f1`, `weighted_f1`,
`false_support_rate`, `abstention_rate`, review queue case ids, and
`false_support_risk_slices` / `top_false_support_risk_slice` when overcalls
are present. Use macro/weighted metrics with false-support fields rather than
accuracy alone. The top-level `quality_gates_ok` summarizes all included
backend and sidecar gates. When `--output-dir` is used, the experiment
`manifest.json` keeps `support_baseline_metric_fields` and
`support_baseline_metrics` plus compact false-support triage fields such as
`false_support_overcall_backends`, `false_support_top_overcall_backend`, and
`false_support_top_risk_slice_id`; it also stores top-overcall review-plan
fields such as `false_support_top_overcall_review_plan_status`,
`false_support_top_overcall_review_plan_next_action`, and
`false_support_top_overcall_review_plan_phase_ids` so release tooling can rank
saved runs and route supported-overcall review without loading the full result
payload.

`release_summary` is the preferred machine-readable entry point for agents and
release scripts. It exposes `status`, `next_action`, `quality_gate_ok`,
`label_sidecar_gate_ok`, `benchmark_claim_safe`, `ok_to_accept_supported`,
compact metric/risk counts, top review-case ids, acceptance blockers, abstention
review ids, and label-maturity counts. Treat any `status` other than `clear` as
a reason to avoid unqualified support-quality or benchmark-readiness claims.

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
