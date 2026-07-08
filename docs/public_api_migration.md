# Public API Migration

CiteGuard's stable user-facing package is `citeguard`. Source checkouts keep
the older root package named `src` only as a temporary compatibility bridge for
historical scripts and notebooks; published packages expose the `citeguard.*`
surface as the product contract.

## Use These Imports

| Task | Public import |
|---|---|
| Citation verification | `citeguard.verification` |
| Live and fixture scholarly sources | `citeguard.retrieval` |
| MCP server entry point | `citeguard.mcp` |
| CLI runner | `citeguard.cli` |
| Runtime/status helpers | `citeguard.runtime` |

## Experimental Source-Checkout Modules

Some modules still exist in source checkouts for historical writing-agent
experiments and benchmark utilities:

- `citeguard.orchestrator`
- `citeguard.planner`
- `citeguard.writer`
- `citeguard.api`
- selected `citeguard.benchmark` helpers

These modules are kept importable for local experiments and compatibility tests,
but they are not the stable v0.1 product contract. New installed-package user
code, README snippets, scripts, examples, and agent skills should use the
auditor package surface listed above: `citeguard.verification`,
`citeguard.retrieval`, `citeguard.mcp`, `citeguard.cli`, and
`citeguard.runtime`.

## Migration Rules

- Prefer `citeguard` and `citeguard.*` in README snippets, tests, scripts,
  examples, agent skills, and user code.
- Treat the legacy root package as deprecated even when it is present in a
  source checkout for compatibility.
- Do not add new product behavior under the legacy root package; implement it
  under `citeguard.*` and keep any compatibility shim thin.
- Avoid branching on legacy import errors. Feature detection should use the
  public package, console scripts, or `citeguard status`.

## Compatibility Policy

In source checkouts, existing legacy imports continue to work for now and emit a
`DeprecationWarning` when the compatibility package is imported. Deprecation
warnings are hidden by default in normal Python runs, so older users are not
interrupted, while test suites and release checks can opt into seeing the
migration signal with:

```bash
python -Wd -c "import src"
```

Legacy package entrypoints are thin public facades: compatibility imports for
retrieval and verification re-export the same public `__all__` lists as
`citeguard.retrieval` and `citeguard.verification`. Do not add local export
lists, lazy loaders, or new behavior under compatibility entrypoints.

The eventual release target is a package whose public documentation, tests,
scripts, examples, and agent skills all point to the `citeguard.*` interfaces.
Current release artifacts are checked so they do not include the legacy
compatibility namespace; migrate installed-package user code to `citeguard.*`.

The root package facade (`import citeguard`) re-exports only stable auditor
helpers such as `verify_citation`, `audit_citations`,
`check_claim_support_set`, `parse_citation`, `error_payload`,
`error_code_registry`, and `__version__`.
It does not export the experimental source-checkout modules in `citeguard.__all__`.
Import experiments by their fully qualified names only when working from a
source checkout, and do not present them as the published API.
