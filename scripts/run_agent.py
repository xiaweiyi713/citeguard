"""Run CiteGuard on a local or built-in corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from _bootstrap import ensure_project_root

ensure_project_root()

from src.graph import CitationRecord
from src.orchestrator import AgentTask, CiteGuardAgent
from src.retrieval.scholarly_clients import InMemoryMetadataSource, build_live_metadata_source
from src.verifiers import (
    DEFAULT_NLI_MODEL,
    DEFAULT_RERANKER_MODEL,
    SupportVerifier,
    build_production_support_backend,
)


def demo_corpus() -> List[CitationRecord]:
    return [
        CitationRecord(
            citation_id="openscholar-2024",
            title="OpenScholar: Synthesizing Scientific Literature with Retrieval-Augmented Language Models",
            authors=["Akari Asai", "Yizhong Wang"],
            year=2024,
            venue="arXiv",
            abstract=(
                "This work synthesizes scientific literature with retrieval-augmented language models "
                "and studies citation hallucinations in academic writing."
            ),
            source="demo",
        ),
        CitationRecord(
            citation_id="ghostcite-2026",
            title="GhostCite: A Large-Scale Analysis of Citation Validity in the Age of Large Language Models",
            authors=["Zhe Xu"],
            year=2026,
            venue="arXiv",
            abstract=(
                "We measure phantom references, fabricated metadata, and citation validity across "
                "many large language models."
            ),
            source="demo",
        ),
        CitationRecord(
            citation_id="reasons-2024",
            title="REASONS: A Benchmark for Retrieval and Automated Citations of Scientific Sentences",
            authors=["Deepak Tilwani"],
            year=2024,
            venue="arXiv",
            abstract=(
                "This benchmark studies retrieval, citation selection, and scientific sentence attribution."
            ),
            source="demo",
        ),
    ]


def load_corpus(path: Path) -> List[CitationRecord]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [CitationRecord(**row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CiteGuard on a topic.")
    parser.add_argument("--topic", required=True, help="Research topic to write about.")
    parser.add_argument("--corpus", help="Optional path to a JSON corpus file.")
    parser.add_argument("--section-count", type=int, default=3, help="Number of sections to generate.")
    parser.add_argument(
        "--live-sources",
        default="",
        help="Comma-separated scholarly sources: openalex,crossref,arxiv,semantic-scholar",
    )
    parser.add_argument("--mailto", default="research@example.com", help="Contact email for Crossref requests.")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL, help="Sentence-transformers model name.")
    parser.add_argument("--nli-model", default=DEFAULT_NLI_MODEL, help="Transformers NLI model name.")
    parser.add_argument(
        "--support-mode",
        default="production",
        choices=["production", "heuristic"],
        help="Use real semantic models or the lightweight heuristic fallback.",
    )
    args = parser.parse_args()

    if args.live_sources:
        metadata_source = build_live_metadata_source(
            [item for item in args.live_sources.split(",") if item.strip()],
            mailto=args.mailto,
        )
    else:
        records = load_corpus(Path(args.corpus)) if args.corpus else demo_corpus()
        metadata_source = InMemoryMetadataSource(records)

    if args.support_mode == "heuristic":
        support_verifier = SupportVerifier()
    else:
        support_verifier = SupportVerifier(
            backend=build_production_support_backend(
                reranker_model_name=args.reranker_model,
                nli_model_name=args.nli_model,
            )
        )
    agent = CiteGuardAgent(metadata_source, support_verifier=support_verifier)
    result = agent.run(AgentTask(topic=args.topic, section_count=args.section_count))
    print(json.dumps(result.audit_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
