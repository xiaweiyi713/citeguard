# CiteGuard Skill Examples

Use these examples when you need exact MCP payload shapes or safe wording for
edge cases. Keep the main `SKILL.md` workflow authoritative.

## Tool Examples

Single citation:

```json
{
  "tool": "verify_citation_tool",
  "arguments": {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani"],
    "year": 2017,
    "arxiv_id": "1706.03762"
  }
}
```

Source health probe:

```json
{
  "tool": "citeguard_status_tool",
  "arguments": {
    "check_sources": true,
    "health_query": "Attention Is All You Need"
  }
}
```

If `source_health.summary.degraded=true`, summarize `sources_available`,
`sources_failed`, `failure_kind_counts`, and `failure_kind_sources`; then branch
on `source_health.summary.next_action`.

Batch citation audit:

```json
{
  "tool": "audit_citations_tool",
  "arguments": {
    "citations": [
      {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani"],
        "year": 2017,
        "arxiv_id": "1706.03762"
      },
      {
        "raw_text": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks. Journal of Imaginary Methods, 2024."
      }
    ]
  }
}
```

Claim support:

```json
{
  "tool": "check_claim_support_tool",
  "arguments": {
    "claim": "The Transformer relies entirely on attention mechanisms.",
    "title": "Attention Is All You Need",
    "arxiv_id": "1706.03762",
    "lang": "en"
  }
}
```

One claim, multiple citations:

```json
{
  "tool": "check_claim_support_set_tool",
  "arguments": {
    "claim": "Citation auditing should verify existence, metadata, and claim support.",
    "citations": [
      {"title": "GhostCite: A Large-Scale Analysis of Citation Validity"},
      {"raw_text": "Another citation string from the bibliography."}
    ],
    "lang": "en"
  }
}
```

Ambiguous citation:

```json
{
  "tool": "verify_citation_tool",
  "arguments": {
    "title": "Deep Learning",
    "year": 2015
  }
}
```

If this returns `ambiguous`, do not choose one match. Ask for a DOI, arXiv id,
venue, complete author list, or exact reference text.

Metadata mismatch:

```json
{
  "tool": "verify_citation_tool",
  "arguments": {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani"],
    "year": 2018,
    "arxiv_id": "1706.03762"
  }
}
```

If this returns `metadata_mismatch`, show `field_diffs`, quote the
`suggested_citation` if present, and ask before editing the user's bibliography.

Claim/citation batch:

```json
{
  "tool": "audit_claim_support_tool",
  "arguments": {
    "items": [
      {
        "claim": "The Transformer relies entirely on attention mechanisms.",
        "title": "Attention Is All You Need",
        "arxiv_id": "1706.03762"
      },
      {
        "claim": "Citation auditing should verify existence, metadata, and claim support.",
        "citations": [
          {"title": "A citation auditing paper"},
          {"title": "A second related paper"}
        ]
      }
    ],
    "lang": "en"
  }
}
```

Counter-evidence lead search:

```json
{
  "tool": "search_counterevidence_tool",
  "arguments": {
    "claim": "Method M improves task T.",
    "top_k": 5
  }
}
```

Suggested compact result table:

| item | verdict | risk | next step |
|---|---|---|---|
| Attention Is All You Need | `verified` | low | keep citation |
| Title-only same-name record | `metadata_mismatch` | medium | confirm DOI/arXiv id before editing |
| Unknown reference | `not_found` | high | ask user for source or replacement |
| Claim support check | `insufficient_evidence` | medium | inspect full text or rewrite claim |

## Result Wording Examples

Metadata mismatch:

> CiteGuard found a likely real paper, but the year differs from your reference:
> your citation says 2021, the matched record says 2020. Because there is no DOI
> or arXiv id, treat this as a possible mismatch and confirm the identifier
> before editing.

Ambiguous citation:

> CiteGuard found multiple plausible matches for this title. I should not choose
> one silently; please provide a DOI, arXiv id, or venue/year confirmation.

Not found:

> CiteGuard could not verify this reference in the checked sources. That makes it
> high-risk, but it is not proof that the paper is fabricated.

Source outage:

> CiteGuard could not reach one or more sources, so this result is inconclusive.
> I will not treat source failure as evidence that the citation is fake. If
> `outage_limited=true`, I should retry or ask for stronger identifiers.

Rate-limited source health:

> CiteGuard reached the status probe, but Semantic Scholar is rate-limited
> (`failure_kind_counts.rate_limited=1`). I should wait, reduce batch size, or
> configure credentials; this does not make any unresolved citation fake.

Remote evidence harvest failure:

> CiteGuard resolved the citation metadata, but optional publisher/DOI landing
> page snippet harvesting failed (`metadata.evidence_harvest_failures`,
> `stage=remote_evidence`). I can keep the metadata result, but I should not
> claim full-text or landing-page support from the missing snippet.

Claim support with limited scope:

> The citation exists, but the support check only used abstract-level evidence.
> The abstract does not confirm the stronger claim; inspect the full text or
> weaken the sentence.

Contradiction:

> CiteGuard found evidence that contradicts the claim. Treat this as high-risk:
> revise the claim, replace the citation, or inspect the source manually before
> keeping it.
