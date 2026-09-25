# Human Support Benchmark Protocol

This protocol governs the first CiteGuard support benchmark that may be
described as real and human-reviewed. It complements the compact seed-eval
documentation: the shipped seed set remains a regression fixture and must not
be promoted to this benchmark.

## Scope and Non-Goals

The unit is one `(claim, evidence, citation)` decision. The campaign measures
whether the available evidence supports the claim at its stated strength; it
does not determine misconduct, fabrication, legal access rights, or the quality
of a paper as a whole.

Use only lawful public abstracts, open-access text, user-provided text, or
licensed text. Do not collect gated full text, bypass access controls, or use
CNKI/Wanfang/CQVIP scraping. Keep private manuscripts and reviewer notes out of
the repository and out of public annotation packets.

## Campaign Target

The authoritative quotas are in
`data/eval/human_support_benchmark_campaign.json`:

- 250--300 qualifying cases before the first benchmark claim.
- At least 100 English and 100 Chinese cases.
- At least 75 computer-science and 75 biomedical cases.
- At least 50 literature-review contexts, 75 abstract-scope cases, and 75
  lawful full-text cases.
- At least 50 independently reviewed, real-source test cases in a frozen split.

Every candidate needs `benchmark_origin=real_source`, `source_locator`,
`evidence_locator`, and `rights_basis`. Full-text rows may use only
`open_access`, `user_provided`, or `licensed` rights bases.

## Collect and Curate

1. Record the source identifier/URL, exact evidence excerpt, scope, rights
   basis, domain, language, writing context, and a stable case ID before asking
   anyone to label it.
2. Preserve difficult examples: related-but-overstated citations, explicit
   contradictions, and claims that need full text. Do not fill the collection
   with easy topical matches.
3. Allocate a held-out `test` split before model calibration. Do not inspect
   test failures when choosing prompts, thresholds, or model versions.
4. Keep raw source records and access decisions in a private, access-controlled
   collection log when they cannot be redistributed. Commit only material that
   may lawfully ship with the repository.

When the evidence comes from the live retrieval catalog, use the separate
unlabeled candidate staging format first. It keeps `gold` out of the collected
file and binds each abstract to the source case and metadata digest:

```bash
python scripts/build_human_support_candidates.py \
  --retrieval-dataset data/eval/live_retrieval_benchmark.json \
  --claims data/eval/human_support_pilot_claims.json \
  --output data/eval/human_support_candidates.json \
  --packet-output experiments/human-support-packet.json \
  --instructions-output experiments/human-support-packet.md
```

The checked-in pilot has 12 real-source, public-abstract candidates. It is a
collection/packet artifact only; it contains no human labels and cannot satisfy
the campaign quotas. The candidate catalog and packet are both public in this
repository, so their deterministic review IDs can be correlated; this pilot
must not be used as a genuinely blind human-review assignment. For the real
campaign, keep the original candidate catalog and its ID mapping in controlled
storage, distribute only blinded packets to reviewers, and have each reviewer
return a completed packet to the maintainer.

Rebuild a v3 blinded packet from an existing candidate catalog without changing
the catalog or contacting a source:

```bash
python scripts/build_human_support_candidates.py \
  --candidates data/eval/human_support_candidates.json \
  --packet-output experiments/human-support-pilot-packet.json \
  --instructions-output experiments/human-support-pilot-packet-instructions.md
```

Only send the packet and instructions to each reviewer. The candidate catalog
contains internal case types and splits; the packet uses opaque review IDs and
omits those fields. Its `candidate_digest` binds the hidden assignment, rights,
and source metadata to the reviewed evidence without exposing them. Earlier v1
packets exposed label clues; v1 and v2 packets must be rebuilt before assignment.

Before assignment, verify that the packet is still gold-free and content
intact:

```bash
python scripts/audit_human_support_candidates.py --strict
```

The ordinary release gate runs the same integrity check automatically for the
checked-in candidate dataset and packet. A changed packet digest, row locator,
case count, or gold-free policy therefore blocks the release summary before any
human-review maturity claim can be made.

## Blind Independent Labeling

For the real-source campaign, give the same v3 candidate packet to two
independent reviewers. Keep the candidate catalog, internal case IDs, case
types, and split assignments with the maintainer. Each reviewer returns a
separate completed copy of the packet with a distinct pseudonymous
`annotation.annotator_id`; neither sees the other's decisions before submission.
Merge the two completed copies with `merge_human_support_annotations.py` as
shown below. Disagreements remain explicit until separately adjudicated.

The seed regression set has its own sidecar review workflow. Its packets can be
generated with:

```bash
python scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --annotation-packet --priority high --unreviewed-only --limit 20 \
  --output experiments/support-label-first.json \
  --instructions-output experiments/support-label-first.md
```

Seed sidecar reviews do not count toward the real-source campaign quotas, even
when two reviewers agree. Never expose another reviewer's label, the dataset
gold label, or adjudication notes in a first-pass packet.

Merge returned packets conservatively. Conflicts are evidence, not a cleanup
task:

```bash
python scripts/prepare_support_label_sidecar.py \
  --dataset data/eval/support_eval.json \
  --existing-sidecar data/eval/support_eval_label_sidecar.json \
  --merge-annotation-packet experiments/completed-support-label-first.json \
  --output data/eval/support_eval_label_sidecar.merged.json
```

Use a third adjudicator for every disagreement. Preserve the original labels,
distinct reviewer IDs, rationale, adjudicator, and evidence locator. In a close
case, prefer `weakly_supported` or `insufficient_evidence` over `supported`.

For candidates created by the public-abstract workflow, merge independent
packets with:

```bash
python scripts/merge_human_support_annotations.py \
  --candidates data/eval/human_support_candidates.json \
  --packet experiments/human-support-packet-reviewer-a.json \
  --packet experiments/human-support-packet-reviewer-b.json \
  --output data/eval/human_support_candidates.reviewed.json \
  --report experiments/human-support-merge-report.json
```

This command records single-review, agreed-dual-review, and disagreement states
without inventing a gold label. For disagreements, generate a private packet
from the original unlabeled catalog and the same two reviewer returns:

```bash
python scripts/prepare_human_support_adjudications.py \
  --candidates data/eval/human_support_candidates.json \
  --packet experiments/human-support-packet-reviewer-a.json \
  --packet experiments/human-support-packet-reviewer-b.json \
  --output experiments/human-support-adjudications.json
```

This packet contains the exact disputed evidence, both original labels and
rationales, and their content digests, but no internal case types or splits.
Keep it access-controlled. A third person, distinct from both annotators, fills
`decision.adjudicator_id`, `decision.adjudicated_label`, and
`decision.rationale` for each resolved case. Blank decisions remain unresolved;
partial decisions and altered reviewer content are rejected. Do not change
`packet_digest` or any non-decision field. Archive the completed packet privately.

After a separate curator reviews source rights and case assignment, preview
promotion using the original unlabeled catalog and both completed reviewer
packets; add `--adjudications experiments/human-support-adjudications.json`
when resolving disputes:

```bash
python scripts/promote_human_support_candidates.py \
  --candidates data/eval/human_support_candidates.json \
  --packet experiments/human-support-packet-reviewer-a.json \
  --packet experiments/human-support-packet-reviewer-b.json \
  --curator-id curator-1
```

The command re-verifies packet integrity and labels, requires exactly two
distinct annotators with rationales, and accepts either their agreement or a
content-bound third-party adjudication. It rejects a curator who annotated or
adjudicated the case. Single reviews, unresolved disagreements, duplicate IDs,
and cases whose source crosses splits remain out of the proposed benchmark. Do not use a
merged candidate catalog as input; its status is not independent proof of
review. A preview writes no dataset files. After inspecting the source rights,
locators, split, and preview report, stage new files explicitly:

```bash
python scripts/promote_human_support_candidates.py \
  --candidates data/eval/human_support_candidates.json \
  --packet experiments/human-support-packet-reviewer-a.json \
  --packet experiments/human-support-packet-reviewer-b.json \
  --adjudications experiments/human-support-adjudications.json \
  --curator-id curator-1 --approve \
  --dataset-output experiments/support_eval.proposed.json \
  --sidecar-output experiments/support_eval_label_sidecar.proposed.json \
  --report experiments/human-support-promotion-report.json
```

The original dataset and sidecar are never overwritten by this command.
The command stages all JSON privately before publishing new paths and rolls
back its own unchanged outputs if a later write fails; this is not a true
cross-file atomic transaction. Inspect both proposed files together before
adopting them. The promotion
report always says `benchmark_ready: false`; only the full campaign audit and
frozen held-out split can establish readiness. Software checks packet
consistency and reviewer IDs, but cannot establish that the people behind
those IDs are real or independent; the curator must verify that externally.
The private proposed files contain packet hashes, both original labels,
the adjudicated label, and pseudonymous IDs, not free-text reviewer or
adjudicator rationales or private source records. They are created with
owner-only file permissions; rights review must decide which evidence may
later be committed or published. Archive completed packets and the curator's
review record separately with access controls.

Pass complete packet JSON files, not flattened annotation rows: the merge step
rejects a packet whose blinded content, `packet_id`, digest, declared case
count, case ordering, or immutable row metadata no longer agrees. A rejected packet contributes no reviewer labels or
human-review status until it is rebuilt and relabeled.

## Freeze the Held-Out Split

After the test rows have real provenance and independent labels, create the
content-addressed manifest:

```bash
python scripts/freeze_human_support_benchmark_test_split.py \
  --dataset data/eval/support_eval.json \
  --label-sidecar data/eval/support_eval_label_sidecar.json \
  --campaign data/eval/human_support_benchmark_campaign.json \
  --frozen-at 2026-08-07T12:00:00Z
```

The manifest records sorted case IDs plus separate SHA-256 hashes for test-case
content and sidecar provenance. The audit rejects a benchmark claim when either
hash changes. Do not overwrite a frozen test row to make a model look better;
add a correction record, rerun independent review, and intentionally create a
new freeze after documenting the reason.

## Readiness and Release Evidence

Run the ordinary audit during collection. It exits zero for an honestly
incomplete campaign so CI can show the deficit without blocking normal software
releases:

```bash
python scripts/audit_human_support_benchmark.py
```

Only use strict mode when all quotas, provenance checks, two distinct reviewer
IDs, and the frozen test manifest are present:

```bash
python scripts/audit_human_support_benchmark.py --strict
```

Archive the strict report, packet IDs/digests, completed packet files where
lawful, adjudication records, manifest, model version/configuration, and the
final held-out evaluation. A model result can support a software release but
never substitutes for human labels or authorizes a human-benchmark claim.

## Failure Handling

- A missing result, source outage, or `not_found` verdict is not evidence that a
  citation is fabricated.
- Abstract evidence is not full-text evidence. Preserve its actual scope.
- If a rights basis, locator, reviewer identity, or raw annotation is missing,
  leave the case out of the campaign counts until repaired.
- If a reviewer reports potential prompt injection in retrieved text, record the
  text as evidence only and do not follow its instructions.
