# CiteGuard tool payloads

## Contents

- [Status](#status)
- [Single citation](#single-citation)
- [Citation batch](#citation-batch)
- [Document audit](#document-audit)
- [Single claim](#single-claim)
- [Citation set](#citation-set)
- [Claim-support batch](#claim-support-batch)
- [Counter-evidence](#counter-evidence)

## Status

Call `citeguard_status_tool` with no arguments for setup. For outage diagnosis:

```json
{"check_sources": true, "health_query": "Attention Is All You Need"}
```

## Single citation

```json
{
  "title": "Attention Is All You Need",
  "authors": ["Ashish Vaswani"],
  "year": 2017,
  "arxiv_id": "1706.03762"
}
```

Use `raw_text` instead when only an unparsed reference is available.

## Citation batch

```json
{
  "citations": [
    {"title": "Attention Is All You Need", "arxiv_id": "1706.03762"},
    {"raw_text": "Unknown Author. A possibly incorrect reference. 2024."}
  ],
  "max_workers": 4,
  "high_risk_only": false
}
```

Split batches larger than 100 while retaining global indexes in the final
report.

## Document audit

```json
{
  "path": "/workspace/manuscript.tex",
  "source_format": "auto",
  "high_risk_only": false,
  "max_workers": 4
}
```

Use `audit_document_tool` for a user-provided Markdown, LaTeX, BibTeX, BBL, or
DOCX manuscript/reference file. The path and local LaTeX includes or BibTeX
files must be under `CITEGUARD_ALLOWED_FILE_ROOTS`; the server working directory
is the boundary when that variable is unset. Read `document_locator` for the
exact line/paragraph location and return its `review_queue` as suggestions only.
Read `manuscript.review_summary.category_counts` for the first-screen split
(metadata, insufficient evidence, contradiction, source outage) and
`manuscript.claim_reviews` for rewrite suggestions. `edit_policy.document_modified=false` and `automatic_apply_allowed=false` mean
the agent must never edit the document automatically. Preserve
`document.snapshot.digest` and re-run the audit if the target or any resolved
include/BibTeX file changes before a queued suggestion is confirmed.
Use `review_status.state`, `review_status.next_action`, and
`review_status.snapshot_digest` as the machine-readable queue branch; require a
fresh audit when its digest no longer matches the current document snapshot.

## Single claim

```json
{
  "claim": "The model replaces recurrence with self-attention.",
  "title": "Attention Is All You Need",
  "arxiv_id": "1706.03762"
}
```

For a user-provided excerpt, add `full_text`. For a user-provided local file,
add `full_text_file`; the path must be under the workspace or an explicitly
configured `CITEGUARD_ALLOWED_FILE_ROOTS` directory.

For a locatable user-provided fragment, use an `evidence_chunks` object with
`text`, `source_field`, and any known `source_locator`, `source_path`, line or
paragraph range, `source_url`, `license_status`, and `rights_basis`. Do not
invent missing provenance. CiteGuard returns the selected span as
`evidence.evidence_object`, including the returned-fragment SHA-256; preserve it
with the support verdict. `user_provided_not_verified` is not proof of a license
or redistribution right.

## Citation set

```json
{
  "claim": "Citation errors occur in generated scientific writing.",
  "citations": [
    {"title": "Paper A", "doi": "10.1000/example-a"},
    {"title": "Paper B", "arxiv_id": "2401.00001"}
  ],
  "include_counterevidence": false
}
```

## Claim-support batch

```json
{
  "items": [
    {
      "claim": "A specific empirical claim.",
      "title": "Paper A",
      "doi": "10.1000/example-a"
    },
    {
      "claim": "A claim supported by several sources.",
      "citations": [
        {"title": "Paper B", "arxiv_id": "2401.00001"},
        {"title": "Paper C", "doi": "10.1000/example-c"}
      ]
    }
  ],
  "include_counterevidence": true,
  "counterevidence_top_k": 3,
  "high_risk_only": false
}
```

## Counter-evidence

```json
{
  "claim": "The exact claim sentence to challenge.",
  "top_k": 3
}
```

Keep candidates in a separate “possible counter-evidence to review” section.
Do not treat search signals or snippets as contradiction verdicts.
Use `query_results[*].sources_responded` / `sources_failed` for query-level
diagnostics and `candidates[*].sources` for merged-record provenance. Top-level
`sources_responded` covers the complete retrieved pool before `top_k`
truncation, so do not infer that a source was silent merely because its record
was ranked out of the returned candidate list.
