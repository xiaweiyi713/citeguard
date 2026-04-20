# Benchmark Phase 1 Issue Drafts

This file contains the first batch of issue drafts derived from [docs/benchmark_todo.md](../benchmark_todo.md). These are designed to kick off `Milestone 0.2: Evaluation Foundations`.

## Issue 1

Title:

`[Research] Create train/dev/test split for support verification examples`

Suggested labels:

- `research`
- `benchmark`

Suggested milestone:

- `0.2 Evaluation Foundations`

Body:

```md
## Motivation

The current support calibration examples are useful for prototype tuning, but they are not yet organized into a benchmark-grade split. We need a clean `train/dev/test` structure so calibration can happen on `dev` and reporting can stay locked on `test`.

## Deliverables

- Create a benchmark split scheme for support verification examples
- Add explicit split membership to shipped examples
- Document the split policy in `docs/benchmark_todo.md` or a companion dataset note
- Ensure calibration scripts can point to `dev` without touching `test`

## Proposed protocol

- Keep the existing example format as the base schema
- Add a split field or split-specific files
- Reserve `dev` for threshold and ensemble calibration
- Reserve `test` for final reporting only

## Risks or confounders

- Small prototype datasets make leakage easy
- Similar paraphrase pairs may accidentally cross splits

## Definition of done

- `train/dev/test` organization exists in-repo
- Calibration can be run on `dev`
- `test` is documented as locked for reporting
```

## Issue 2

Title:

`[Research] Define support-label schema and adjudication guidelines`

Suggested labels:

- `research`
- `benchmark`
- `documentation`

Suggested milestone:

- `0.2 Evaluation Foundations`

Body:

```md
## Motivation

The benchmark needs a sharper label ontology than plain binary support. We also need adjudication guidance so contributors label examples consistently.

## Deliverables

- Define label meanings for:
  - `supported`
  - `weakly_supported`
  - `unsupported`
  - `contradicted`
- Write short annotation guidelines with examples
- Document how to handle ambiguous or mixed evidence cases

## Proposed protocol

- Start from support-verification examples already in `examples/`
- Add 2-3 examples per label class
- Include explicit rules for overclaims, causal claims, and quantitative claims

## Risks or confounders

- Boundary between `weakly_supported` and `unsupported` may be fuzzy
- Different fields may require different evidence standards

## Definition of done

- A label schema doc exists
- Example-driven annotation guidelines exist
- At least one reviewer can label from the doc without extra clarification
```

## Issue 3

Title:

`[Research] Expand hard negatives for overclaim and domain-mismatch cases`

Suggested labels:

- `research`
- `benchmark`

Suggested milestone:

- `0.2 Evaluation Foundations`

Body:

```md
## Motivation

Current prototype examples include some negatives, but we need a more systematic hard-negative set to stress support verification.

## Deliverables

- Add new negatives for:
  - overclaim
  - causal overclaim
  - quantitative or frequency overclaim
  - domain mismatch
  - metadata-correct but support-incorrect cases
- Save examples in the benchmark input format
- Update any calibration or benchmark docs affected by the new categories

## Proposed protocol

- Add at least 5 examples per hard-negative family
- Keep evidence text realistic and related, not obviously random
- Prefer examples that look plausible enough to fool lexical overlap

## Risks or confounders

- If negatives are too easy, they will not stress the verifier
- If negatives are too adversarial, they may become label-ambiguous

## Definition of done

- Hard-negative families are represented explicitly
- Example counts per family are documented
- New examples are usable by calibration or evaluation scripts
```

## Issue 4

Title:

`[Research] Add provenance fields for evidence origin and source diversity analysis`

Suggested labels:

- `research`
- `benchmark`
- `retrieval`

Suggested milestone:

- `0.2 Evaluation Foundations`

Body:

```md
## Motivation

We now ingest evidence from title, abstract, and live evidence chunks, but benchmark examples should expose where the strongest evidence came from so we can separate adapter quality from verifier quality.

## Deliverables

- Add provenance fields to benchmark examples
- Record whether evidence came from:
  - title
  - abstract sentence
  - remote evidence chunk
  - merged multi-source metadata
- Document the schema and intended use in analysis

## Proposed protocol

- Extend the benchmark example schema with evidence-origin metadata
- Keep fields compact enough for in-repo storage
- Make sure source diversity can be aggregated later in metrics scripts

## Risks or confounders

- Evidence origin may change after adapter upgrades
- Some examples may legitimately have multiple strong sources

## Definition of done

- Provenance fields exist in the benchmark schema
- At least one example exists for each major evidence origin category
- Source-diversity analysis is possible without manual inspection
```

## Issue 5

Title:

`[Research] Add support-verification confusion matrices and calibration diagnostics`

Suggested labels:

- `research`
- `benchmark`
- `metrics`

Suggested milestone:

- `0.2 Evaluation Foundations`

Body:

```md
## Motivation

Current benchmark reporting includes citation-integrity metrics, but we need a more direct lens on support verification quality and threshold behavior.

## Deliverables

- Add confusion-matrix reporting for support verification
- Add precision, recall, F1, false-support rate, and false-reject rate summaries
- Make calibration outputs easier to compare across runs

## Proposed protocol

- Build on the existing support calibration module
- Save metrics in a machine-readable schema under `experiments/`
- Keep output simple enough to use in tables later

## Risks or confounders

- Metrics may be misleading on very small datasets
- Results should stay split-aware once `dev/test` exists

## Definition of done

- Support-specific metrics are computed from scripts
- Confusion matrix outputs are saved in a stable format
- Calibration diagnostics are documented and reproducible
```

## Issue 6

Title:

`[Research] Run first locked dev calibration and held-out test evaluation`

Suggested labels:

- `research`
- `calibration`
- `benchmark`

Suggested milestone:

- `0.2 Evaluation Foundations`

Body:

```md
## Motivation

Once a clean split exists, we need the first proper calibration cycle: tune on `dev`, then evaluate the locked configuration on `test`.

## Deliverables

- Run threshold and ensemble-weight calibration on `dev`
- Freeze the selected configuration
- Re-run the frozen configuration on `test`
- Save results and config snapshots under `experiments/`

## Proposed protocol

- Use the existing `scripts/calibrate_support.py` path as the base
- Store both selected config and final evaluation outputs
- Document exactly which data split was used for each run

## Risks or confounders

- Leakage from `dev` into `test`
- Overfitting to too-small held-out sets

## Definition of done

- A frozen support configuration exists
- `dev` and `test` outputs are saved separately
- Results can be reused for release notes or paper tables
```

## Issue 7

Title:

`[Research] Implement verifier and retrieval-source ablation matrix`

Suggested labels:

- `research`
- `ablation`
- `benchmark`

Suggested milestone:

- `0.2 Evaluation Foundations`

Body:

```md
## Motivation

We need to know which parts of CiteGuard actually drive performance: heuristic support, reranker, NLI, full ensemble, and different retrieval-source combinations.

## Deliverables

- Add ablation runs for:
  - heuristic only
  - reranker only
  - NLI only
  - heuristic + reranker
  - reranker + NLI
  - full ensemble
- Add retrieval-source ablations for:
  - in-memory corpus
  - OpenAlex
  - Crossref
  - arXiv
  - multi-source merged

## Proposed protocol

- Reuse the same evaluation split and metrics where possible
- Save each ablation with a config snapshot
- Keep result naming consistent for later table generation

## Risks or confounders

- Live-source variability may add noise
- Some source combinations may fail due to missing remote evidence

## Definition of done

- A reproducible ablation matrix exists
- Outputs are stored under `experiments/`
- At least one summary table can be built from the saved results
```

## Issue 8

Title:

`[Research] Create error-analysis buckets and representative failure set`

Suggested labels:

- `research`
- `error-analysis`
- `benchmark`

Suggested milestone:

- `0.2 Evaluation Foundations`

Body:

```md
## Motivation

Benchmark scores alone do not explain failure modes. We need stable error buckets and representative examples for each one.

## Deliverables

- Define buckets for:
  - fabricated citation accepted
  - real citation with bad metadata accepted
  - unsupported citation accepted
  - supported citation rejected
  - correct abstention
  - incorrect abstention
- Save representative examples for each bucket
- Track whether failures come from neutral-heavy NLI behavior or missing remote evidence

## Proposed protocol

- Start from current evaluation outputs and hand-curate representative cases
- Save examples in a reusable JSON or Markdown summary format
- Link each bucket to likely remediation directions

## Risks or confounders

- Some failures may span multiple buckets
- Buckets need to stay stable enough for future comparisons

## Definition of done

- Error bucket definitions are documented
- Representative examples are saved
- At least one error-analysis artifact is ready for a future paper table or appendix
```

## Issue 9

Title:

`[Research] Standardize experiment artifact schema under experiments/`

Suggested labels:

- `research`
- `developer experience`
- `benchmark`

Suggested milestone:

- `0.2 Evaluation Foundations`

Body:

```md
## Motivation

Experiment outputs are starting to accumulate, but we need a stable artifact schema so scripts, tables, and analyses do not depend on ad hoc file formats.

## Deliverables

- Define a compact experiment result schema
- Store config snapshots beside each experiment output
- Adopt versioned subfolders under `experiments/`
- Document the schema in the repo

## Proposed protocol

- Keep the schema small and JSON-friendly
- Cover calibration, evaluation, ablation, and error-analysis outputs
- Make sure downstream scripts can read the same fields consistently

## Risks or confounders

- Overdesigning too early may slow iteration
- Different experiment types may need slightly different metadata

## Definition of done

- A documented artifact schema exists
- At least one calibration and one evaluation output use it
- Future experiment scripts can target the same layout
```
