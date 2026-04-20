# Benchmark Phase 1 GitHub Project Draft

This board draft turns the first benchmark wave into an executable `Milestone 0.2` plan.

## Recommended Project Name

- `CiteGuard Benchmark Phase 1`

## Recommended Project Description

> Phase 1 evaluation foundations for CiteGuard: benchmark splits, label schema, hard negatives, calibration, ablations, and error analysis.

## Suggested Project Fields

- `Status`
  - `Backlog`
  - `Ready`
  - `In Progress`
  - `Blocked`
  - `In Review`
  - `Done`
- `Priority`
  - `P0`
  - `P1`
  - `P2`
- `Track`
  - `dataset`
  - `labeling`
  - `metrics`
  - `experiments`
  - `analysis`
  - `infrastructure`
- `Milestone`
  - `0.2 Evaluation Foundations`
- `Dependency`
  - free-text dependency field for issue numbers

## Suggested Iteration Order

The best order is to build the benchmark base first, then metrics and experiment machinery, then ablations and error analysis.

### Wave 1: unblock benchmark structure

1. Create train/dev/test split for support verification examples
2. Define support-label schema and adjudication guidelines
3. Add provenance fields for evidence origin and source diversity analysis

Why first:

- these three issues define the benchmark schema
- they reduce leakage and labeling ambiguity before running larger experiments
- later metrics and calibration work depend on them

### Wave 2: strengthen data difficulty and reporting

4. Expand hard negatives for overclaim and domain-mismatch cases
5. Add support-verification confusion matrices and calibration diagnostics
6. Standardize experiment artifact schema under `experiments/`

Why second:

- hard negatives make the evaluation meaningful
- metrics and artifact schema give us stable reporting outputs
- calibration runs should not start before outputs are structured

### Wave 3: run locked evaluations and ablations

7. Run first locked dev calibration and held-out test evaluation
8. Implement verifier and retrieval-source ablation matrix

Why third:

- these tasks depend on the split, label schema, metrics, and artifact layout
- ablations are much easier once the first locked eval path is stable

### Wave 4: analyze failure modes

9. Create error-analysis buckets and representative failure set

Why last:

- error analysis is more useful after initial locked eval and ablation outputs exist
- representative examples are easier to curate from saved experiment artifacts

## Priority Table

| Priority | Issue | Track | Depends on |
| --- | --- | --- | --- |
| P0 | Create train/dev/test split for support verification examples | dataset | none |
| P0 | Define support-label schema and adjudication guidelines | labeling | none |
| P0 | Add provenance fields for evidence origin and source diversity analysis | dataset | split, label schema |
| P1 | Expand hard negatives for overclaim and domain-mismatch cases | dataset | label schema |
| P1 | Add support-verification confusion matrices and calibration diagnostics | metrics | split |
| P1 | Standardize experiment artifact schema under `experiments/` | infrastructure | split |
| P1 | Run first locked dev calibration and held-out test evaluation | experiments | split, metrics, artifact schema |
| P2 | Implement verifier and retrieval-source ablation matrix | experiments | locked eval, artifact schema |
| P2 | Create error-analysis buckets and representative failure set | analysis | locked eval, ablations |

## Suggested Initial Status

| Issue | Initial status |
| --- | --- |
| Create train/dev/test split for support verification examples | Ready |
| Define support-label schema and adjudication guidelines | Ready |
| Add provenance fields for evidence origin and source diversity analysis | Backlog |
| Expand hard negatives for overclaim and domain-mismatch cases | Backlog |
| Add support-verification confusion matrices and calibration diagnostics | Backlog |
| Standardize experiment artifact schema under `experiments/` | Backlog |
| Run first locked dev calibration and held-out test evaluation | Backlog |
| Implement verifier and retrieval-source ablation matrix | Backlog |
| Create error-analysis buckets and representative failure set | Backlog |

## Suggested Assignees Pattern

- one owner for benchmark schema and labeling
- one owner for experiment scripts and metrics
- one owner for error analysis and write-up

If you are working solo, keep only one issue `In Progress` at a time and use the wave order above.

## Recommended First Three Issues to Open

1. Create train/dev/test split for support verification examples
2. Define support-label schema and adjudication guidelines
3. Add support-verification confusion matrices and calibration diagnostics

Reason:

- these three give the fastest path to a real dev/test workflow
- they create a base that later negative expansion and calibration can reuse
