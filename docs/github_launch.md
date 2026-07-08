# GitHub Launch Pack

This document collects repository naming, topics, profile copy, pinned-project wording, and first-release copy for a clean public launch of CiteGuard as an agent-facing skeptical citation auditor.

## Recommended Repository Name

Recommended:

- `citeguard`

Why this is the best default:

- matches the project name exactly
- short, memorable, and easy to search
- broad enough to grow with the project
- avoids overcommitting to one submodule such as support verification only

Strong alternatives:

- `citeguard-agent`
- `citeguard-auditor`
- `citeguard-mcp`

Recommendation:

- If the repository is the canonical home of the project, use `citeguard`
- If your GitHub already has multiple similarly named tooling repos, use `citeguard-agent`

## Suggested GitHub Repository Description

Primary short description:

> Skeptical citation auditing for agent writing workflows.

Alternative short description:

> Agent-ready citation, metadata, and claim-support auditing.

Longer one-sentence description:

> CiteGuard checks whether cited papers exist, whether supplied metadata matches scholarly records, and whether available evidence supports the claim, with conservative CLI, batch, cache-replay, and MCP workflows for writing agents.

Conservative safety wording:

> A `not_found` result, source outage, sparse metadata record, or counter-evidence lead is not proof that a citation is fabricated. CiteGuard lowers confidence, records the source state, and recommends human review when evidence is incomplete.

## Suggested GitHub Topics

Primary topic set:

- `citation-verification`
- `scientific-writing`
- `mcp`
- `agent-tools`
- `hallucination-mitigation`
- `retrieval-augmented-generation`
- `nli`
- `evidence-attribution`
- `openalex`
- `crossref`
- `arxiv`
- `semantic-scholar`

If you want a slightly more academic emphasis, swap in:

- `scholarly-search`
- `benchmarking`
- `trustworthy-ai`
- `research-integrity`

## Suggested Social Preview Text

Short version:

> An agent-facing skeptical citation auditor for checking existence, metadata, and claim support before references enter generated text.

Alternative:

> Trustworthy agent writing starts with checking claim-citation-evidence links, not trusting fluent text.

## Pinned Project Copy

### Recommended pinned repository title

- `CiteGuard`

### Recommended pinned repository description

> An agent-facing skeptical citation auditor for trustworthy writing. CiteGuard verifies citation existence, metadata fit, and claim support with conservative outputs.

### Slightly more workflow-oriented pinned description

> CiteGuard ships a public `citeguard.*` Python package, `citeguard` CLI, `citeguard-mcp` stdio server, JSON/JSONL batch audits, cache replay, and source-health aware outputs.

### Chinese pinned description option

> 面向 agent 写作流程的审慎引用审计器，在引用进入正文前检查论文是否存在、元数据是否匹配、证据是否支撑 claim，并把不可达来源视为不确定性而不是伪造证据。

## Suggested Profile Pinned Project Blurb

Short blurb:

> Building conservative citation-auditing infrastructure for trustworthy agent writing.

Longer blurb:

> CiteGuard treats academic writing as a `claim -> citation -> evidence` problem. It prefers abstention, source-state reporting, and review recommendations over unsupported confidence.

## Suggested First Release Title

- `v0.1.0: Alpha agent-facing citation auditor`

## Suggested First Release Tagline

> Public alpha for skeptical citation auditing in agent writing workflows.

## Suggested First Release Notes Link

Use `docs/releases/v0.1.0.md` for the full launch note. The release note should call out:

- public `citeguard.*` package structure
- `citeguard` CLI and `citeguard-mcp` stdio server
- JSON and JSONL batch audits
- MCP stdio smoke coverage
- source-health/status contracts
- cache inspect, clear, export, and offline replay
- support-eval provenance and false-support risk tracking
- security/compliance boundaries, including no gated-source crawling or paywall bypassing
