---
name: citeguard-verify
description: Use when checking, auditing, or fixing citations in scientific or technical writing — verifying that cited papers actually exist and that their metadata (title, authors, year, venue, DOI) is correct against live scholarly sources. Triggers when the user is writing related work / a literature review / a bibliography, pastes references, or asks to "check my citations".
---

# CiteGuard Citation Verification

You verify citations against real scholarly sources before trusting them. You do NOT invent or guess whether a paper exists — you call the CiteGuard MCP tools.

## When to use

- The user is drafting related work, a literature review, or a reference list.
- The user pasted citations / a bibliography and wants them checked.
- You are about to present citations you generated yourself — verify them first.

## How to use

1. For a single citation, call the `verify_citation_tool` MCP tool with structured
   fields (`title`, `authors`, `year`, `doi`, `arxiv_id`) when you have them, or
   `raw_text` for a free-text reference. Identifiers (DOI/arXiv) give the most
   reliable result.
2. For a list, call `audit_citations_tool` with an array of citation objects.
3. Read the `verdict` for each result:
   - `verified` — exists and metadata matches. Safe to keep.
   - `metadata_mismatch` — the paper exists but a field disagrees with the matched
     record. Show the wrong fields (`field_diffs`) and offer the `suggested_citation`.
     Caveat: when the citation had NO DOI/arXiv id and the only mismatch is `year`
     or `venue`, the matched record may be a same-title reprint/re-index and the
     user could be right. Present such cases as "possible mismatch — confirm or add
     a DOI/arXiv id", not as a definitive error.
   - `not_found` — could not be verified. Flag it clearly as high-risk and ask the
     user to confirm; do NOT assert it is fabricated.
   - `ambiguous` — multiple plausible matches; ask the user to provide a DOI/arXiv id.

## How to present results

- Use a compact table: `✓ verified` / `⚠ metadata` / `✗ not found` / `? ambiguous`.
- For `metadata_mismatch`, show what is wrong and the suggested correction.
- NEVER silently rewrite the user's citations. Propose changes and let them decide.
- Always mention which sources were checked (`sources_checked`).
