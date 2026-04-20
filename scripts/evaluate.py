"""Run a simple CiteGuard evaluation over the built-in demo corpus."""

from __future__ import annotations

import argparse
import json

from _bootstrap import ensure_project_root

ensure_project_root()

from src.benchmark import EvaluationRecord, MetricsCalculator
from src.graph import CitationRecord
from src.orchestrator import AgentTask, CiteGuardAgent
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verifiers import build_production_support_backend, SupportVerifier


def demo_records():
    return [
        CitationRecord(
            citation_id="ghostcite-2026",
            title="GhostCite: A Large-Scale Analysis of Citation Validity in the Age of Large Language Models",
            authors=["Zhe Xu"],
            year=2026,
            venue="arXiv",
            abstract="We analyze citation validity, phantom references, and fabricated bibliographic metadata.",
            source="demo",
        ),
        CitationRecord(
            citation_id="openscholar-2024",
            title="OpenScholar: Synthesizing Scientific Literature with Retrieval-Augmented Language Models",
            authors=["Akari Asai"],
            year=2024,
            venue="arXiv",
            abstract="This work studies scientific literature synthesis and citation hallucinations.",
            source="demo",
        ),
    ]


def build_eval_records(result) -> list:
    records = []
    for claim_id, decision in result.graph.decisions.items():
        cited = bool(decision.selected_citation_ids)
        findings = []
        if cited:
            for citation_id in decision.selected_citation_ids:
                findings.extend(result.graph.claim_findings_for_citation(claim_id, citation_id))
        else:
            findings = result.graph.claim_findings(claim_id)
        existence_fail = any(
            finding.verifier_name == "ExistenceVerifier" and not finding.passed for finding in findings
        )
        metadata_fail = any(
            finding.verifier_name == "MetadataVerifier" and not finding.passed for finding in findings
        )
        support_fail = any(
            finding.verifier_name == "SupportVerifier" and not finding.passed for finding in findings
        )
        records.append(
            EvaluationRecord(
                phantom_citation=cited and existence_fail,
                metadata_error=cited and metadata_fail,
                claim_supported=not support_fail and cited,
                unsupported_citation=cited and support_fail,
                abstained=decision.action.value == "abstain",
            )
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CiteGuard on a demo topic.")
    parser.add_argument("--topic", required=True, help="Topic to evaluate.")
    parser.add_argument(
        "--support-mode",
        default="production",
        choices=["production", "heuristic"],
        help="Use real semantic models or the lightweight heuristic fallback.",
    )
    args = parser.parse_args()

    support_verifier = (
        SupportVerifier()
        if args.support_mode == "heuristic"
        else SupportVerifier(backend=build_production_support_backend())
    )
    agent = CiteGuardAgent(InMemoryMetadataSource(demo_records()), support_verifier=support_verifier)
    result = agent.run(AgentTask(topic=args.topic))
    records = build_eval_records(result)
    metrics = MetricsCalculator().compute(records)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
