# Live Retrieval Benchmark Protocol

This protocol measures how CiteGuard resolves known real records against live
scholarly sources. It is separate from the deterministic adapter fixture and
the small daily canary. Neither of those is a live-source quality benchmark.

## What Counts

Each case must be a known real record with a lawful metadata locator and an
expected canonical identity. Collect DOI, arXiv-ID, and title-query cases
separately. The first campaign requires 200 qualifying cases: at least 50 DOI,
50 arXiv-ID, and 100 title queries, with at least three observations per case
over time.

Store only lawful public metadata, open-access metadata, user-provided metadata,
or licensed metadata. Do not add inaccessible full text, scrape restricted
databases, or use a `not_found` result as proof that a paper is fabricated.

## Curate Known Records

Add cases to `data/eval/live_retrieval_benchmark.json` only after independently
checking their canonical DOI, arXiv ID, or title. Each row needs:

- `benchmark_origin=real_source` and a stable case ID.
- `query_kind` of `doi`, `arxiv_id`, or `title`, with matching query fields.
- `expected_identity` containing a canonical DOI, arXiv ID, or title.
- `ground_truth_locator`, rights basis, language, and domain.

For repeatable curation, start with an operator-reviewed request manifest and
run the public-metadata collector:

```bash
python scripts/collect_live_retrieval_cases.py \
  --requests data/eval/live_retrieval_pilot_requests.json \
  --mailto research-contact@example.org \
  --merge-into data/eval/live_retrieval_benchmark.json \
  --output data/eval/live_retrieval_benchmark.json \
  --report experiments/live-retrieval-collection-report.json
```

The collector never promotes the first search result blindly. DOI/arXiv
requests require identifier agreement; title requests require an exact title
or an independently supplied expected identifier. Rejected candidates remain
in the report with source diagnostics. Accepted rows carry a public metadata
snapshot and a content digest so downstream support candidates can cite the
same lawful abstract without re-querying a source.

The repository currently contains a 12-case pilot (`4` DOI, `4` arXiv-ID,
`4` title), not the 200-case campaign. It is useful for exercising the workflow
and revealing source-specific failures; it is deliberately not enough for a
permanent quality claim.

The collection audit shows exact gaps without contacting any source:

```bash
python scripts/audit_live_retrieval_benchmark.py
python scripts/audit_live_retrieval_benchmark.py --strict
```

The normal command intentionally exits zero while the collection is incomplete;
strict mode is for claiming that the collection is ready.

## Capture Observations

Run observations from a deliberately recorded region and archive the standard
artifact. Region is operator-supplied rather than inferred from an IP address.

```bash
python scripts/observe_live_retrieval_benchmark.py \
  --observer-region CN-Shanghai \
  --mailto research-contact@example.org \
  --output-dir experiments \
  --run-id retrieval-observation-2026-08-07
```

The result records UTC timestamp, requested source, adapter version, supplied
API version where one is known, and `not_disclosed` otherwise. It reports
identity accuracy only across attempts unaffected by source failure; it also
records p50/p95 latency, rate-limit count, outage count, explicit `ambiguous`
and `resolved_incorrect` counts, failure-kind counts, and separate
DOI/arXiv/title slices. When a known work legitimately has both a DOI and an
arXiv ID, record both in `expected_identity`; either registered identifier may
establish the same canonical work, but a same-title record with neither match
remains incorrect or ambiguous.

Use `--source-api-version SOURCE=VERSION` only when the source actually exposes
that version. Do not invent a source version. Use `--fail-on-source-limited` for
operational alerts; source limits remain observation outcomes, not quality or
fabrication verdicts.

## Aggregate Longitudinal Coverage

Aggregate only archived observation artifacts. This command reads local JSON and
does not make scholarly-source requests:

```bash
python scripts/summarize_live_retrieval_observations.py \
  --artifact-dir experiments/retrieval-observation-2026-08-07 \
  --artifact-dir experiments/retrieval-observation-2026-08-14 \
  --artifact-dir experiments/retrieval-observation-2026-08-21 \
  --output-dir experiments \
  --run-id retrieval-observation-summary-2026-08
```

The aggregate validates each artifact's standard manifest/config/result triplet,
the current known-record query and ground-truth digest, timestamp, region, source
metadata, and row cardinality. It requires three distinct timestamps with at
least one non-source-limited attempt per case. Repeated artifacts or retries at
the same timestamp do not satisfy the three-observation target; source-limited
attempts remain visible in availability metrics but do not silently complete
eligible coverage.

Use `--artifact-root experiments` only when that tree is dedicated to archived
observation runs; it discovers only `live_retrieval_observation` artifacts. Use
`--strict` when checking readiness. The ordinary command stays non-blocking while
collection or coverage is incomplete.

## Interpret Results Conservatively

- Compare observations across the same region, time window, case set, and
  CiteGuard configuration. A single run is not a permanent source ranking.
- Exclude rate-limited, timeout, and outage-limited attempts from identity
  accuracy denominators; retain them in availability and failure metrics.
- Treat a known real record that returns `not_found` as a retrieval failure to
  investigate. It does not establish author intent or citation fabrication.
- Preserve source failures and `Retry-After` data. Do not retry aggressively or
  circumvent source access controls.

Before publishing an aggregate table, archive every `result.json`, `config.json`,
and `manifest.json`, name the observation dates/regions, report source-version
availability, and describe the result as a time-bounded observation.
