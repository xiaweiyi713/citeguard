# Benchmark Phase 1 Issue Posting Pack

This file is the copy-paste pack for creating the first nine benchmark issues on GitHub.

How to use it:

1. Copy the `Title`
2. Apply the `Labels`
3. Set the `Milestone`
4. Paste the `Body`

Recommended milestone for all issues:

- `0.2 Evaluation Foundations`

## Issue 1

Title:

```text
[Research] Create train/dev/test split for support verification examples
```

Labels:

```text
research, benchmark
```

Milestone:

```text
0.2 Evaluation Foundations
```

Body:

```md
## Motivation

The current support examples are useful for prototype tuning, but not yet for benchmark-grade evaluation. We need a clean `train/dev/test` split so calibration happens on `dev` and final reporting stays locked on `test`.

## Scope

- Add a benchmark split scheme for support verification examples
- Mark split membership explicitly in shipped examples
- Document the split policy
- Ensure calibration scripts can target `dev` without touching `test`

## Done when

- `train/dev/test` organization exists in-repo
- `dev` is used for calibration
- `test` is documented as reporting-only
```

## Issue 2

Title:

```text
[Research] Define support-label schema and adjudication guidelines
```

Labels:

```text
research, benchmark, documentation
```

Milestone:

```text
0.2 Evaluation Foundations
```

Body:

```md
## Motivation

The benchmark needs a sharper label ontology than plain binary support, plus annotation guidance so contributors label examples consistently.

## Scope

- Define labels for `supported`, `weakly_supported`, `unsupported`, and `contradicted`
- Add short adjudication guidelines with examples
- Document how to handle ambiguous, mixed, and overclaim cases

## Done when

- A label-schema doc exists
- Example-driven annotation guidance exists
- A reviewer can label from the doc without extra clarification
```

## Issue 3

Title:

```text
[Research] Expand hard negatives for overclaim and domain-mismatch cases
```

Labels:

```text
research, benchmark
```

Milestone:

```text
0.2 Evaluation Foundations
```

Body:

```md
## Motivation

The current benchmark needs a stronger hard-negative set to stress support verification beyond simple lexical overlap.

## Scope

- Add negatives for overclaim, causal overclaim, quantitative or frequency overclaim, domain mismatch, and metadata-correct but support-incorrect cases
- Save them in the benchmark input format
- Document counts or category coverage

## Done when

- Each hard-negative family is represented explicitly
- New examples are usable by calibration or evaluation scripts
- Coverage is documented
```

## Issue 4

Title:

```text
[Research] Add provenance fields for evidence origin and source diversity analysis
```

Labels:

```text
research, benchmark, retrieval
```

Milestone:

```text
0.2 Evaluation Foundations
```

Body:

```md
## Motivation

We now use title, abstract, and live evidence chunks, but benchmark examples should make evidence origin explicit so adapter quality and verifier quality can be analyzed separately.

## Scope

- Extend the benchmark schema with provenance fields
- Record whether evidence came from title, abstract sentence, remote chunk, or merged multi-source metadata
- Document how these fields should be used in analysis

## Done when

- Provenance fields exist in the example schema
- At least one example exists for each major evidence-origin category
- Source-diversity analysis is possible without manual inspection
```

## Issue 5

Title:

```text
[Research] Add support-verification confusion matrices and calibration diagnostics
```

Labels:

```text
research, benchmark, metrics
```

Milestone:

```text
0.2 Evaluation Foundations
```

Body:

```md
## Motivation

Citation-integrity metrics are useful, but we also need direct reporting for support verification quality and threshold behavior.

## Scope

- Add confusion-matrix reporting for support verification
- Add precision, recall, F1, false-support rate, and false-reject rate
- Save calibration outputs in a machine-readable format

## Done when

- Support-specific metrics are computed from scripts
- Confusion matrices are saved in a stable format
- Calibration diagnostics are reproducible
```

## Issue 6

Title:

```text
[Research] Run first locked dev calibration and held-out test evaluation
```

Labels:

```text
research, calibration, benchmark
```

Milestone:

```text
0.2 Evaluation Foundations
```

Body:

```md
## Motivation

Once a clean split exists, we need the first proper benchmark cycle: calibrate on `dev`, freeze the configuration, and evaluate on `test`.

## Scope

- Run threshold and ensemble-weight calibration on `dev`
- Freeze the selected configuration
- Re-run the frozen configuration on `test`
- Save configs and outputs under `experiments/`

## Done when

- A frozen support configuration exists
- `dev` and `test` outputs are saved separately
- Results are reusable for tables and release notes
```

## Issue 7

Title:

```text
[Research] Implement verifier and retrieval-source ablation matrix
```

Labels:

```text
research, ablation, benchmark
```

Milestone:

```text
0.2 Evaluation Foundations
```

Body:

```md
## Motivation

We need to know which parts of CiteGuard actually drive benchmark performance: heuristic support, reranker, NLI, full ensemble, and different retrieval-source combinations.

## Scope

- Add verifier ablations for heuristic-only, reranker-only, NLI-only, pairwise combinations, and full ensemble
- Add retrieval-source ablations for in-memory, OpenAlex, Crossref, arXiv, and multi-source merged
- Save outputs with config snapshots

## Done when

- A reproducible ablation matrix exists
- Outputs are saved under `experiments/`
- At least one summary table can be built from the saved results
```

## Issue 8

Title:

```text
[Research] Create error-analysis buckets and representative failure set
```

Labels:

```text
research, error-analysis, benchmark
```

Milestone:

```text
0.2 Evaluation Foundations
```

Body:

```md
## Motivation

Benchmark scores alone do not explain failure modes. We need stable error buckets and representative examples for each one.

## Scope

- Define buckets for fabricated citations, bad metadata acceptance, unsupported acceptance, supported rejection, correct abstention, and incorrect abstention
- Save representative examples for each bucket
- Track failures related to neutral-heavy NLI behavior and missing remote evidence

## Done when

- Error buckets are documented
- Representative examples are saved
- At least one reusable error-analysis artifact exists
```

## Issue 9

Title:

```text
[Research] Standardize experiment artifact schema under experiments/
```

Labels:

```text
research, developer experience, benchmark
```

Milestone:

```text
0.2 Evaluation Foundations
```

Body:

```md
## Motivation

Experiment outputs are starting to accumulate, but we need a stable artifact schema so calibration, evaluation, and table-generation scripts do not depend on ad hoc file formats.

## Scope

- Define a compact result schema
- Store config snapshots beside outputs
- Adopt versioned subfolders under `experiments/`
- Document the schema in-repo

## Done when

- A documented artifact schema exists
- At least one calibration and one evaluation output use it
- Future experiment scripts can target the same layout
```
