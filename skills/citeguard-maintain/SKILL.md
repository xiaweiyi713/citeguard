---
name: citeguard-maintain
description: Maintain and release the CiteGuard repository. Use only when working inside a CiteGuard source checkout on support-evaluation datasets, human-review packets, calibration, release gates, package smoke tests, MCP registry metadata, or CiteGuard contributor workflows. Do not use for ordinary citation verification.
---

# Maintain CiteGuard

Keep repository-only evaluation and release work separate from the installed
`citeguard-verify` user skill.

## Evaluation workflow

1. Validate the user-skill trigger set, then score decisions captured from the
   target agent/client. Before collecting a run, inspect the exact installed
   Skill directory and carry its digest into the artifact:

   ```bash
   python scripts/eval_skill_trigger.py --validate-only
   python -m citeguard skill status --client codex --scope user
   python scripts/eval_skill_trigger.py --client codex \
     --skill-path /absolute/path/to/.codex/skills/citeguard-verify \
     --write-template /tmp/citeguard-trigger-codex.json
   # Fill each triggered value after running every request through Codex.
   python scripts/eval_skill_trigger.py --client codex \
     --skill-path /absolute/path/to/.codex/skills/citeguard-verify \
     --require-run-metadata \
     --predictions /tmp/citeguard-trigger-codex.json
   ```

   Repeat the capture independently for Claude and Cursor. `--skill-path`
   must point to the installed bundle that the client actually loaded, not the
   source checkout. When the installed directory is unavailable, record its
   `sha256:` value from the target environment and use
   `--expected-skill-digest` instead. Keep every prediction row's
   `request_digest` unchanged; the evaluator rejects altered request text or
   request digests and binds `dataset_digest` to the checked-in suite bytes.
   Record the actual client version, suite id, and timezone-aware collection
   timestamp in the run metadata before scoring.

2. Audit label maturity:

   ```bash
   python scripts/prepare_support_label_sidecar.py --audit
   ```

3. Follow `review_plan.next_phase` and generate blinded packets with the
   returned command template. Never expose hidden gold labels or predictions to
   reviewers.
4. Record packet id, digest, reviewer identity, evidence scope, and whether full
   text was needed.
5. Resolve dual-review disagreements before raising release thresholds.
6. Run deterministic reports on the test split only after calibration choices
   are frozen.

Keep the checked-in real-source candidate packet intact with:

```bash
python scripts/audit_human_support_candidates.py --strict
```

`release_package_gate.py` repeats this packet digest and gold-free policy check;
do not bypass it by substituting flattened JSONL rows.

For the strict publish-gate packet sizes and independent first/second-review
commands, follow `docs/support_labeling_guidelines.md`; do not invent or copy
labels to satisfy thresholds.

Use `python scripts/eval_support.py --help` and
`python scripts/prepare_support_label_sidecar.py --help` for current arguments;
do not copy stale command shapes into this skill.

## Release workflow

Run, in order:

```bash
python -m unittest discover -s tests -v
python scripts/smoke_package.py --install-mode wheel
python scripts/smoke_package.py --install-mode sdist
python -m pip install -e ".[models]"
python scripts/automated_release_review.py --output automated-release-review.json
python scripts/release_package_gate.py --release-claim-mode software --automated-review-report automated-release-review.json
```

Also validate `server.json`, run the MCP stdio smoke in a Python 3.10+
environment, and test the exact published-package command used by registry
clients. Build from a clean copy so stale `build/lib` files cannot enter wheels.

The automated review may authorize an ordinary software release only. It must
retain `human_benchmark_claim_allowed=false`, bind the report to dataset and
implementation digests, and keep model reviewer outputs out of the human-label
sidecar. Do not describe synthetic-only labels as human-reviewed, and do not
call a claim-support benchmark release-safe while its label-maturity gate is
false.

## Change discipline

- Preserve unrelated dirty-worktree changes.
- Keep `README.md`, `README.en.md`, configuration docs, Skill instructions, and
  runtime error messages aligned.
- Add behavioral tests for tool selection and safety invariants, not only phrase
  presence tests.
- Treat live source drift as a canary signal, not deterministic unit-test data.
