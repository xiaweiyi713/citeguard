# Benchmark TODO

This document tracks the concrete next steps needed to turn the current prototype benchmark and calibration setup into a research-grade evaluation package.

## 1. Dataset Structure

- Split support verification examples into `train`, `dev`, and `test`
- Keep calibration on `dev` only and lock `test` for reporting
- Add stable example identifiers and provenance fields for every example
- Record whether evidence comes from title, abstract, or live evidence chunks

## 2. Labeling

- Define clear support labels:
  - `supported`
  - `weakly_supported`
  - `unsupported`
  - `contradicted`
- Write short adjudication guidelines with examples
- Add at least two-reviewer labeling for ambiguous claim-evidence pairs
- Track disagreements instead of silently collapsing them

## 3. Hard Negatives

- Add overclaim negatives where the paper is related but does not justify the stronger statement
- Add causal-overclaim negatives
- Add frequency and quantitative-overclaim negatives
- Add domain-mismatch negatives
- Add metadata-correct but support-incorrect examples

## 4. Source Diversity

- Add examples whose strongest evidence comes from:
  - title only
  - abstract sentence
  - remote evidence chunk
  - merged multi-source metadata
- Track which sources succeed or fail to expose useful evidence chunks
- Separate adapter quality from verifier quality in analysis

## 5. Metrics

- Keep existing citation-integrity metrics:
  - `PCR`
  - `MCR`
  - `CSR`
  - `UCR`
  - `AU`
  - `RIS`
- Add support-verification confusion matrices
- Add calibration diagnostics:
  - precision / recall / F1
  - false-support rate
  - false-reject rate
- Add abstention-sensitive reporting for high-risk claims

## 6. Experiments

- Run threshold and ensemble-weight calibration on labeled `dev`
- Re-run the locked configuration on held-out `test`
- Add ablations for:
  - heuristic only
  - reranker only
  - NLI only
  - heuristic + reranker
  - reranker + NLI
  - full ensemble
- Add retrieval-source ablations:
  - in-memory corpus
  - OpenAlex
  - Crossref
  - arXiv
  - multi-source merged

## 7. Error Analysis

- Create explicit buckets for:
  - fabricated citation accepted
  - real citation with bad metadata accepted
  - unsupported citation accepted
  - supported citation rejected
  - correct abstention
  - incorrect abstention
- Save representative examples for each bucket
- Track failures caused by neutral-heavy NLI outputs
- Track failures caused by missing remote evidence chunks

## 8. Artifact Hygiene

- Save experiments under versioned subfolders in `experiments/`
- Store config snapshots beside results
- Add a compact results schema that downstream scripts can read consistently
- Keep benchmark inputs small enough to ship in-repo, and larger datasets documented separately

## 9. Publication Readiness

- Produce one reproducible benchmark table from repo scripts alone
- Add one error-analysis table and one calibration table
- Add benchmark limitations section that is honest about domain coverage and label scale
- Freeze a benchmark version before making strong comparative claims
