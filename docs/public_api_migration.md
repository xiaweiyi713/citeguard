# Public API Migration

CiteGuard's stable user-facing package is `citeguard`. The older root package
named `src` is kept only as a temporary compatibility bridge for historical
scripts and notebooks.

## Use These Imports

| Task | Public import |
|---|---|
| Citation verification | `citeguard.verification` |
| Live and fixture scholarly sources | `citeguard.retrieval` |
| MCP server entry point | `citeguard.mcp` |
| CLI runner | `citeguard.cli` |
| Runtime/status helpers | `citeguard.runtime` |

## Migration Rules

- Prefer `citeguard` and `citeguard.*` in README snippets, tests, scripts,
  examples, agent skills, and user code.
- Treat the legacy root package as deprecated even though it still imports for
  compatibility.
- Do not add new product behavior under the legacy root package; implement it
  under `citeguard.*` and keep any compatibility shim thin.
- Avoid branching on legacy import errors. Feature detection should use the
  public package, console scripts, or `citeguard status`.

## Compatibility Policy

Existing legacy imports continue to work for now and emit a `DeprecationWarning`
when the compatibility package is imported. Deprecation warnings are hidden by
default in normal Python runs, so older users are not interrupted, while test
suites and release checks can opt into seeing the migration signal with:

```bash
python -Wd -c "import src"
```

The eventual release target is a package whose public documentation, tests,
scripts, examples, and agent skills all point to the `citeguard.*` interfaces.
