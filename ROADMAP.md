# CiteGuard Roadmap

This roadmap tracks the most important work needed to move CiteGuard from an
early research prototype toward a stable agent-facing skeptical citation auditor.

## Current Stage

- Status: `Alpha agent-auditor package`
- Strength: end-to-end falsification-first verification, batch audit workflows,
  MCP stdio integration, source-health reporting, cache replay, and agent skill
  guidance are working
- Main gap: claim-support benchmark scale, human label rigor, full-text support
  boundaries, and release hardening still lag behind the system architecture

Implemented foundations:

- Public `citeguard.*` package facades for verification, retrieval, MCP, CLI,
  and runtime use; the legacy `src` root package is now a compatibility bridge
  with a documented migration path.
- MCP stdio smoke coverage that can initialize a client, list tools, call
  status, run fixture-backed verification/support checks, and validate
  structured errors when the MCP SDK is installed.
- Batch citation and claim-support audits with JSON/JSONL input, extracted
  Markdown/LaTeX/DOCX candidates, risk rankings, review summaries, action
  queues, and high-risk-only filtering.
- Source-health/status contracts with checked/failed source separation,
  timeout/rate-limit/network failure summaries, and conservative outage
  handling.
- SQLite cache schema/version inspection, clear/export workflows, deterministic offline replay fixtures, and cache provenance.
- Support calibration artifacts with false-support case ids, confusion-bucket
  score summaries, and decision-path diagnostics for NLI/reranker threshold
  tuning.
- Agent skill instructions that define triggers, forbidden behaviors, MCP client
  setup notes, compact risk-first presentation, and cautious wording for
  not-found, outage, ambiguous, metadata-mismatch, and support results.

## Milestone 0.1: Public Research Prototype

Status: completed

- Ship a clean public repository with install docs, CI, examples, and governance basics
- Expose the falsification-first architecture, verifier stack, and calibration tooling clearly
- Keep the default workflow conservative and auditable

Definition of done:

- Public README, LICENSE, CITATION, CONTRIBUTING, PR and issue templates
- Reproducible local setup and green CI
- Example corpus and calibration examples included in-repo

## Milestone 0.2: Evaluation Foundations

Status: current

- Expand support verification examples into a larger real dev/test split
- Raise human-reviewed support label coverage and resolve supported-label
  disagreements
- Keep calibration data separate from final reporting data
- Save standardized experiment outputs under `experiments/`
- Track false-support risk, abstention rate, contradiction recall, and
  evidence-scope breakdowns before making broad benchmark claims

Definition of done:

- At least one benchmark subset with explicit label provenance
- Stable evaluation scripts for calibration and final scoring
- Standardized experiment artifacts with result/config/manifest snapshots
- Baseline and CiteGuard comparison tables that can be reproduced from the repo
- Release gates require meaningful human review coverage for high-risk
  supported/contradicted/full-text-required cases

## Milestone 0.3: Stronger Evidence Verification

Status: planned

- Improve lawful live evidence harvesting beyond title and abstract fallbacks
- Add more robust source-aware chunk filtering and provenance metadata
- Investigate contradiction-aware retrieval and stronger negative evidence handling
- Continue improving calibration diagnostics for NLI neutral vs entailment
  behavior on larger, human-reviewed slices
- Keep full-text evidence opt-in through lawful user-provided excerpts/files or
  open-source adapters; do not bypass paywalls or gated sources

Definition of done:

- Measurable support-verification improvement on held-out examples
- Evidence provenance retained end-to-end in audit outputs
- Source-specific limitations documented
- Support outputs distinguish abstract, metadata snippet, local full-text, and
  mixed evidence scopes without overclaiming

## Milestone 0.4: Research-Grade Benchmarking

Status: planned

- Add cross-domain evaluation slices such as CS, biomedicine, and high-citation-density review writing
- Run verifier ablations and retrieval-source ablations
- Add structured error analysis artifacts for hallucinated, unsupported, and abstained claims

Definition of done:

- Reproducible benchmark protocol with domain slices
- Clear tables for ablation and error categories
- Strong enough evaluation package for paper writing or workshop submission support

## Milestone 0.5: Usability and Extensions

Status: current

- Keep tightening public API stability around `citeguard.*` while preserving
  legacy shims long enough for users to migrate
- Add better configuration management for source selection, thresholds, and
  experiment presets
- Improve developer ergonomics around model setup and experiment execution
- Harden PyPI/MCP release checks, published-package smoke plans, and client setup
  docs
- Consider lightweight visualization or review tooling for `CCEG`

Definition of done:

- Easier onboarding for external contributors
- Cleaner experiment interfaces
- Better inspection of claim-citation-evidence decisions
- Published package can be installed, smoke-tested, and connected from Codex,
  Claude Code, Cursor, or another MCP client without relying on repository-only
  paths

## Ongoing Priorities

- Keep uncertainty visible rather than hidden
- Prefer conservative citation acceptance over optimistic unsupported claims
- Strengthen reproducibility every time a new experiment path is added
- Document source-specific caveats whenever a live adapter changes
- Treat source outages, model failures, and missing snippets as uncertainty, not
  proof of fabrication
- Make agent-facing contracts machine-readable before relying on prose

## What We Are Not Optimizing For Yet

- Production-scale hosted service reliability
- Full-featured UI productization
- Broad benchmark claims before the dataset is mature enough to support them
- Automated gated full-text retrieval or paywall bypass
