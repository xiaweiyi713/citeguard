# Public API Migration

CiteGuard's stable user-facing package is `citeguard`. Earlier source checkouts
kept an older root package as a temporary compatibility bridge for historical
scripts and notebooks; that bridge has been removed, and both source checkouts
and published packages expose the `citeguard.*` surface as the product
contract.

## Use These Imports

| Task | Public import |
|---|---|
| Citation verification | `citeguard.verification` |
| Live and fixture scholarly sources | `citeguard.retrieval` |
| MCP server entry point | `citeguard.mcp` |
| CLI runner | `citeguard.cli` |
| Runtime/status helpers | `citeguard.runtime` |

## Experimental Source-Checkout Modules

The historical writing-agent experiments were never part of the stable
surface, and they no longer live inside the `citeguard` package at all. The
modules formerly importable as `citeguard.orchestrator`, `citeguard.planner`,
`citeguard.writer`, and `citeguard.api` — together with the writing-benchmark
builders formerly at `citeguard.benchmark.baselines` and
`citeguard.benchmark.dataset_builder` — moved to the repo-root `legacy/`
directory (see `legacy/README.md`). They exist only in source checkouts, are
excluded from wheels and sdists, and are not the stable v0.1 product contract.
The `citeguard.benchmark` subpackage keeps only the shipped support-eval
helpers (metrics, calibration, experiment artifacts).

New installed-package user code, README snippets, scripts, examples, and
agent skills should use the auditor package surface listed above:
`citeguard.verification`, `citeguard.retrieval`, `citeguard.mcp`,
`citeguard.cli`, and `citeguard.runtime`.

## Migration Rules

- Prefer `citeguard` and `citeguard.*` in README snippets, tests, scripts,
  examples, agent skills, and user code.
- The legacy root package has been removed; migrate any remaining private
  scripts or notebooks that still import it to `citeguard.*`.
- Do not reintroduce a legacy root package; implement new behavior under
  `citeguard.*`.
- Avoid branching on legacy import errors. Feature detection should use the
  public package, console scripts, or `citeguard status`.

## Compatibility Policy

Historically, source checkouts shipped legacy imports that emitted a
`DeprecationWarning` when the compatibility package was imported, and legacy
package entrypoints were thin public facades that re-exported the
same public `__all__` lists as `citeguard.retrieval` and
`citeguard.verification`. That compatibility layer has now been removed
entirely: there is no legacy namespace in source checkouts or release
artifacts, and release gates verify that distributions do not include it. Do
not add local export lists, lazy loaders, or compatibility entrypoints back.

Public documentation, tests, scripts, examples, and agent skills all point to
the `citeguard.*` interfaces; migrate installed-package user code to
`citeguard.*`.

The root package facade (`import citeguard`) re-exports only stable auditor
helpers such as `verify_citation`, `audit_citations`,
`check_claim_support_set`, `parse_citation`, `error_payload`,
`error_code_registry`, and `__version__`.
It does not export the experimental source-checkout modules in `citeguard.__all__`.
Import experiments by their fully qualified names only when working from a
source checkout, and do not present them as the published API.
