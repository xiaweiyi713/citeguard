# Contributing to CiteGuard

Thanks for considering a contribution. CiteGuard is currently an early-stage research prototype, so the best contributions are the ones that improve rigor, reproducibility, and failure transparency.

## Good First Contributions

- Add harder support-verification examples and adversarial negatives.
- Improve scholarly adapters or evidence chunk extraction robustness.
- Tighten verifier calibration or error analysis tooling.
- Add reproducible experiment scripts and documentation.
- Improve docs, tests, and developer ergonomics.

## Development Setup

1. Create and activate a Python virtual environment.
2. Upgrade `pip` inside the virtual environment.
3. Install the project in editable mode:

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

4. If you want model-backed support verification, install the optional model stack:

```bash
python -m pip install -r requirements-optional.txt
```

5. Run tests:

```bash
python3 -m unittest discover -s tests -v
```

## Coding Guidelines

- Keep the project falsification-first. When in doubt, prefer conservative behavior over optimistic citation acceptance.
- Add or update tests for behavior changes.
- Keep docs aligned with the actual implementation.
- Make assumptions explicit, especially around retrieval sources, thresholds, and evidence provenance.
- Avoid introducing heavyweight dependencies into the base install unless they are clearly required.

## Pull Requests

- Keep pull requests focused and well-scoped.
- Include a short summary of the problem, approach, and verification steps.
- If your change affects verifier thresholds, evidence extraction, or benchmark behavior, include before/after results.
- If your change touches scholarly sources, note any source-specific limitations or rate-limit assumptions.

## Research Caveat

This repository is a research prototype, not a production citation service. Contributions that make uncertainty visible are more valuable than contributions that only make outputs look smoother.
