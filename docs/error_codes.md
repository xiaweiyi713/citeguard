# CiteGuard Error Codes

CiteGuard returns expected user/configuration errors as machine-readable JSON so
agents do not need to parse prose.

The stable code registry is also exported from `citeguard.errors` as
`ERROR_SCHEMA_VERSION`, `STABLE_ERROR_CODES`, `ERROR_CODE_RECOVERY`,
`ERROR_CODE_NEXT_ACTION`, and `is_stable_error_code()`.

```json
{
  "ok": false,
  "schema_version": 1,
  "error": {
    "code": "missing_citation_input",
    "message": "Provide --raw-text, --title, --doi, or --arxiv-id.",
    "details": {},
    "recovery": "Ask for a DOI, arXiv id, title, or pasted reference.",
    "next_action": "provide_missing_input"
  },
  "exit_code": 2
}
```

CLI commands write this shape to stderr and exit non-zero. MCP tools return the
same shape as the tool result for expected input errors, not as a transport
exception. `schema_version` versions the error payload contract. `error.code`
is the stable branch key, while `error.recovery` mirrors the public recovery
registry and `error.next_action` mirrors the public error-to-action registry, so
agents can choose the next step without parsing prose.

Non-error verification/support results may also include `recovery_code` using
the same registry. For example, an `ambiguous` verification result uses
`ambiguous_citation`, and a source-limited `not_found` result can use `timeout`
or `source_unavailable`. Treat this as structured recovery guidance, not as a
failed tool call.

Non-error verification/support results also include `next_action`, a stable
machine-readable action such as `keep`, `review_metadata`,
`resolve_identifier_or_replace`, `disambiguate_identifier`,
`retry_or_check_source_health`, `review_counterevidence_leads`, `keep_claim`,
`inspect_full_text_or_find_stronger_citation`, or
`rewrite_or_replace_evidence`. Prefer `next_action` for workflow branching;
preserve `recovery_code` as the stable reason/error-code hint when present.

## Stable next_action Values

| action | meaning |
|---|---|
| `continue` | Continue; no immediate remediation is required. |
| `fix_configuration` | Fix CiteGuard configuration before running the check again. |
| `provide_missing_input` | Provide required claim, citation, or file input before retrying. |
| `repair_input` | Repair malformed input, JSON, files, or CLI arguments before retrying. |
| `install_or_configure_dependency` | Install or configure a required optional dependency before retrying. |
| `keep` | Keep a verified citation. |
| `keep_claim` | Keep a claim whose citation evidence supports it. |
| `review_metadata` | Review mismatched citation metadata and the suggested correction. |
| `resolve_identifier_or_replace` | Ask for a DOI/arXiv id or replace an unverified citation. |
| `resolve_citation_identity` | Resolve citation identity before judging claim support. |
| `disambiguate_identifier` | Ask for a DOI/arXiv id or stronger metadata to disambiguate. |
| `inspect_source_health` | Inspect source health because one or more checked sources failed. |
| `retry_or_check_source_health` | Retry later or inspect source health after a source-limited result. |
| `review_counterevidence_leads` | Review counter-evidence candidates before changing the claim or citation. |
| `tighten_claim_or_inspect_full_text` | Tighten the claim or inspect full text for weak support. |
| `inspect_full_text_or_find_stronger_citation` | Inspect full text or find stronger evidence before using the claim. |
| `rewrite_or_replace_evidence` | Rewrite the claim or replace evidence because available evidence contradicts it. |

## Stable Codes

| code | meaning | typical recovery |
|---|---|---|
| `missing_citation_input` | No usable citation identifier, title, or raw text was provided. | Ask for a DOI, arXiv id, title, or pasted reference. |
| `missing_claim` | A support check was requested without a non-empty claim. | Ask for the sentence that the citation is supposed to support. |
| `invalid_input` | The request shape is valid JSON but does not match CiteGuard's contract. | Fix the field type, object shape, or required item. |
| `invalid_json` | A JSON/JSONL input file could not be parsed. | Repair the JSON; `details.line` and `details.column` point to the parse location when available. |
| `argument_parse_error` | CLI flags are missing or malformed. | Show the command help or fix the CLI invocation. |
| `file_error` | The CLI could not read an input file or prepare a filesystem path. | Check the path and permissions. |
| `source_unavailable` | A scholarly source could not be reached or responded unreliably. | Retry later, inspect source health, and avoid treating `not_found` as fabricated. |
| `model_unavailable` | Deep support models are not installed or failed to load. | Install the `models` extra or treat support output as heuristic/weak. |
| `ambiguous_citation` | Multiple plausible records match the citation. | Ask for a DOI/arXiv id or more metadata. |
| `timeout` | A source or model operation exceeded its configured timeout. | Retry, raise the timeout, or continue with reduced confidence. |
| `unsupported_command` | The CLI parser accepted a command name that has no handler. | Upgrade CiteGuard or fix the invocation. |

## Details Contract

- CLI errors include `details.command` when the failed command is known.
- MCP tool errors include `details.tool`.
- Batch input errors include 1-based `details.index` for the failing item.
- Batch file shape errors include `details.command`, `details.expected`, and
  `details.received`; item shape errors also include 1-based `details.index`.
- JSON/JSONL parse errors include `details.command` when the parser knows the
  CLI command, plus `details.line` and `details.column`.
- Citation field validation errors include `details.field`; for example,
  `authors` must be a list of strings and `year` must be an integer year or a
  digit string.
- Full-text evidence file validation errors use `details.field=full_text_file`.
  In batch commands, they also include 1-based `details.index` and
  `details.command` so agents can identify the broken item.
- Missing or unreadable CLI input files return `file_error` with
  `details.field=path`, `details.command`, `details.filename`, and
  `details.errno`.
- Missing or unreadable full-text evidence files return `file_error` with
  `details.field=full_text_file`, `details.filename`, and the same batch
  `details.index` / `details.command` context.
- Missing fields use specific codes (`missing_claim` or
  `missing_citation_input`) instead of generic `invalid_input`, so agents can
  ask only for the missing data.
- `error.recovery` is present on every error payload. It is non-empty for stable
  documented codes and empty for unknown/private codes.
- `error.next_action` is present on every error payload. It is non-empty for
  stable documented codes and empty for unknown/private codes. The mapping is
  exported as `ERROR_CODE_NEXT_ACTION`.

## Agent Policy

- Never translate `not_found`, `source_unavailable`, or `timeout` into
  "fabricated". Say "could not verify" and ask for stronger metadata.
- If verification output sets `outage_limited=true` or
  `source_failure_mode=all_sources_failed`, the check is source-limited and
  should be treated as inconclusive even when the verdict is `not_found`.
- Use `sources_available` to identify checked sources that did not fail; use
  `sources_responded` only for sources that returned candidate records.
- Prefer identifiers over title-only checks when recovering from ambiguity or
  metadata mismatch.
- Prefer `next_action` over parsing `explanation` when deciding whether to ask
  for identifiers, retry later, inspect source health, inspect full text, or
  rewrite/replace evidence. Preserve `recovery_code` when present as the
  underlying stable reason.
- For support checks, `insufficient_evidence` means the available evidence did
  not confirm the claim; it is not a final full-text judgment.
- Preserve `error.code` in logs and UI output so downstream automation can branch
  on it.
- Prefer `error.next_action` for workflow branching on expected errors, just as
  you would for non-error verification/support results.
- Prefer `error.recovery` for concise next-step copy when displaying expected
  errors to users.
- Preserve `schema_version` with the payload when storing or forwarding errors.
