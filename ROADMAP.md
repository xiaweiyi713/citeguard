# CiteGuard Roadmap

This roadmap tracks the most important work needed to move CiteGuard from an early research prototype toward a stronger open-source research system.

## Current Stage

- Status: `Alpha research prototype`
- Strength: end-to-end falsification-first pipeline is working
- Main gap: benchmark scale, labeling rigor, and experiment maturity still lag behind the system architecture

## Milestone 0.1: Public Research Prototype

Status: completed

- Ship a clean public repository with install docs, CI, examples, and governance basics
- Expose the falsification-first architecture, verifier stack, and calibration tooling clearly
- Keep the default workflow conservative and auditable

Definition of done:

- Public README, LICENSE, CITATION, CONTRIBUTING, PR and issue templates
- Reproducible local setup and green CI
- Example corpus and calibration examples included in-repo

## Milestone 0.2: Evaluation Foundations

Status: current

- Expand support verification examples into a real dev/test split
- Add human-reviewed support labels and harder negatives
- Separate calibration data from final reporting data
- Save standardized experiment outputs under `experiments/`

Definition of done:

- At least one benchmark subset with explicit label provenance
- Stable evaluation scripts for calibration and final scoring
- Baseline and CiteGuard comparison tables that can be reproduced from the repo

## Milestone 0.3: Stronger Evidence Verification

Status: planned

- Improve live evidence harvesting beyond title and abstract fallbacks
- Add more robust source-aware chunk filtering and provenance metadata
- Investigate contradiction-aware retrieval and stronger negative evidence handling
- Add better calibration diagnostics for NLI neutral vs entailment behavior

Definition of done:

- Measurable support-verification improvement on held-out examples
- Evidence provenance retained end-to-end in audit outputs
- Source-specific limitations documented

## Milestone 0.4: Research-Grade Benchmarking

Status: planned

- Add cross-domain evaluation slices such as CS, biomedicine, and high-citation-density review writing
- Run verifier ablations and retrieval-source ablations
- Add structured error analysis artifacts for hallucinated, unsupported, and abstained claims

Definition of done:

- Reproducible benchmark protocol with domain slices
- Clear tables for ablation and error categories
- Strong enough evaluation package for paper writing or workshop submission support

## Milestone 0.5: Usability and Extensions

Status: planned

- Expand the API surface and response schemas
- Add better configuration management for source selection, thresholds, and experiment presets
- Improve developer ergonomics around model setup and experiment execution
- Consider lightweight visualization or review tooling for `CCEG`

Definition of done:

- Easier onboarding for external contributors
- Cleaner experiment interfaces
- Better inspection of claim-citation-evidence decisions

## Ongoing Priorities

- Keep uncertainty visible rather than hidden
- Prefer conservative citation acceptance over optimistic unsupported claims
- Strengthen reproducibility every time a new experiment path is added
- Document source-specific caveats whenever a live adapter changes

## What We Are Not Optimizing For Yet

- Production-scale hosted service reliability
- Full-featured UI productization
- Broad benchmark claims before the dataset is mature enough to support them
