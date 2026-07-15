# CiteGuard tool payloads

## Contents

- [Status](#status)
- [Single citation](#single-citation)
- [Citation batch](#citation-batch)
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
