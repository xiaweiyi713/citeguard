# Benchmark Phase 1 Issue Quick Reference

This is the one-page operating view for the first nine benchmark issues. Use it when creating issues, assigning priority, or filling project fields by hand.

## Quick Reference Table

| ID | Title | Suggested labels | Priority | Initial status | Track | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Create train/dev/test split for support verification examples | `research`, `benchmark` | `P0` | `Ready` | `dataset` | none |
| 2 | Define support-label schema and adjudication guidelines | `research`, `benchmark`, `documentation` | `P0` | `Ready` | `labeling` | none |
| 3 | Expand hard negatives for overclaim and domain-mismatch cases | `research`, `benchmark` | `P1` | `Backlog` | `dataset` | 2 |
| 4 | Add provenance fields for evidence origin and source diversity analysis | `research`, `benchmark`, `retrieval` | `P0` | `Backlog` | `dataset` | 1, 2 |
| 5 | Add support-verification confusion matrices and calibration diagnostics | `research`, `benchmark`, `metrics` | `P1` | `Backlog` | `metrics` | 1 |
| 6 | Run first locked dev calibration and held-out test evaluation | `research`, `calibration`, `benchmark` | `P1` | `Backlog` | `experiments` | 1, 5, 9 |
| 7 | Implement verifier and retrieval-source ablation matrix | `research`, `ablation`, `benchmark` | `P2` | `Backlog` | `experiments` | 6, 9 |
| 8 | Create error-analysis buckets and representative failure set | `research`, `error-analysis`, `benchmark` | `P2` | `Backlog` | `analysis` | 6, 7 |
| 9 | Standardize experiment artifact schema under experiments/ | `research`, `developer experience`, `benchmark` | `P1` | `Backlog` | `infrastructure` | 1 |

## Recommended Creation Order

1. Issue 1: train/dev/test split
2. Issue 2: support-label schema
3. Issue 4: provenance fields
4. Issue 5: confusion matrices and calibration diagnostics
5. Issue 9: experiment artifact schema
6. Issue 3: hard negatives
7. Issue 6: locked dev/test calibration
8. Issue 7: ablation matrix
9. Issue 8: error-analysis buckets

## Recommended First `In Progress` Set

If you are working solo:

- keep only one issue `In Progress` at a time
- start with Issue 1
- move Issue 2 to `Ready`

If you have two contributors:

- Contributor A: Issue 1
- Contributor B: Issue 2
- Keep Issues 4 and 5 in `Ready`

If you have three contributors:

- Contributor A: Issue 1
- Contributor B: Issue 2
- Contributor C: Issue 9

## Suggested Project Field Values

- `Milestone`: `0.2 Evaluation Foundations`
- `Status`: `Ready` for Issues 1 and 2, `Backlog` for the rest
- `Priority`: use the table above
- `Track`: use the table above
- `Dependency`: store issue IDs or GitHub issue numbers once created

## Short Notes by Issue

- Issue 1 is the benchmark gatekeeper. Do this before serious calibration work.
- Issue 2 defines the labeling ontology. It should shape Issue 3 and Issue 4.
- Issue 3 should stress the verifier, not just increase example count.
- Issue 4 helps separate adapter quality from verifier quality.
- Issue 5 turns support verification into a measurable target instead of a black box.
- Issue 6 is the first real benchmark cycle and should use locked settings.
- Issue 7 matters for paper-ready ablation tables.
- Issue 8 is where benchmark failures become publishable insights.
- Issue 9 prevents experiment outputs from turning into one-off artifacts.
