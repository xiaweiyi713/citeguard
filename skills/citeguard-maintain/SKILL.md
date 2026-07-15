---
name: citeguard-maintain
description: Maintain and release the CiteGuard repository. Use only when working inside a CiteGuard source checkout on support-evaluation datasets, human-review packets, calibration, release gates, package smoke tests, MCP registry metadata, or CiteGuard contributor workflows. Do not use for ordinary citation verification.
---

# Maintain CiteGuard

Keep repository-only evaluation and release work separate from the installed
`citeguard-verify` user skill.

## Evaluation workflow

1. Validate the user-skill trigger set, then score decisions captured from the
   target agent/client:

   ```bash
   python scripts/eval_skill_trigger.py --validate-only
   python scripts/eval_skill_trigger.py --write-template /tmp/citeguard-trigger-predictions.json
   # Fill each triggered value after running the request through the target agent.
   python scripts/eval_skill_trigger.py --predictions /tmp/citeguard-trigger-predictions.json
   ```

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
