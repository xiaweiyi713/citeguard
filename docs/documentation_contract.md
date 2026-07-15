# Documentation Contract

CiteGuard's core promise is that it never overclaims. That promise lives in the
docs as much as in the code, so `tests/test_release_metadata.py` enforces it: 80
test methods read README.md, README.en.md, and a dozen files under `docs/`, and
fail CI when documentation and behavior drift apart.

Those rules were previously discoverable only by tripping them and
reverse-engineering the assertion. This page states them up front.

## Why the gates exist

They are not style police. They catch two classes of real drift:

- **Contract drift** — a field name, CLI flag, error code, or environment
  variable exists in code but not in the docs (or vice versa). Roughly 85% of the
  assertions are of this kind: identifiers, flags, filenames, config syntax.
- **Claim drift** — the docs start describing capabilities or safety properties
  the tool does not actually have. This is the one that matters most: an
  auditing tool that overclaims is worse than no tool.

Recent examples of the gates working as intended: a version bump that missed
`CITATION.cff`, and a new error code documented in `docs/error_codes.md` but not
registered in `citeguard/errors.py`.

## Rules

### 1. Adding or renaming an error code

Update **both** `citeguard/errors.py` and `docs/error_codes.md`. A code must
appear in all four registries (`ERROR_CODE_RECOVERY`, `ERROR_CODE_NEXT_ACTION`,
`ERROR_CODE_RETRYABLE`, `ERROR_CODE_CATEGORY`), and its documented row must match
the registry values **verbatim** — the recovery sentence in the table is compared
character-for-character with `ERROR_CODE_RECOVERY[code]`.

Gate: `test_error_code_documentation_matches_public_registry`.

### 2. Bumping the version

The version lives in **five** places and all must agree:

| file | field |
|---|---|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `citeguard/version.py` | `__version__ = "X.Y.Z"` |
| `server.json` | `"version"` (two occurrences) |
| `CITATION.cff` | `version: "X.Y.Z"` |

Gate: `test_citation_cff_matches_current_agent_auditor_package`.

### 3. Adding an environment variable

Document it in `docs/mcp_setup.md`, `docs/configuration.md`, and the README
configuration tables. Gate: `configuration_contract` in the release gate.

### 4. Adding a CLI flag or subcommand

Document it in `docs/cli_reference.md`. Several gates assert that documented
invocations match the real argument parser.

### 5. Historical design documents

Anything under `docs/superpowers/` that mentions the pre-migration `src.*`
package must carry an archived-note header containing all of:

- `Archived historical`
- `pre-migration`
- ``stable public `citeguard.*` package``
- `historical compatibility context`
- `docs/public_api_migration.md`

Planning documents for *current* work do not belong under `docs/superpowers/` —
put them in `docs/plans/`. Gate:
`test_historical_superpowers_docs_do_not_look_like_current_api_guidance`.

### 6. Never write `src.` in tests or public docs

The legacy root package is gone. A release gate greps `tests/`, `scripts/`, and
user-facing docs for the token and fails. Name local variables `source`, not
`src`. Gate: `test_public_docs_tests_and_scripts_do_not_use_src_imports`.

### 7. Positioning language is deliberate

A small set of phrases is pinned because they encode the project's claims, not
its prose style — for example `skeptical citation auditor`,
`not part of the published package surface`, and the safety wording around
`not evidence of fabrication`. Changing them is a positioning decision: update
the gate in the same commit and say why in the PR.

## When a gate fails

Read the assertion, then ask which kind of drift it caught:

- **Contract drift** → fix the code/doc that fell out of sync. The gate is right.
- **Claim drift** → the doc is promising something untrue. Fix the doc.
- **A genuinely stale rule** → the gate encodes an obsolete decision. Change the
  gate *and* explain the reasoning in the PR. Do not weaken a gate just to make
  CI green.

## Scope note

These gates protect claims and contracts, not wording. Rewriting an explanation
for clarity is expected and welcome; only the pinned tokens above are fixed.
