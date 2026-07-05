"""Tiny live demo of CiteGuard citation verification (hits OpenAlex + arXiv).

Run from the repo root:

    python3 scripts/demo_verify.py
"""

from __future__ import annotations

from _bootstrap import ensure_project_root

ensure_project_root()

from citeguard.retrieval.scholarly_clients import build_live_metadata_source
from citeguard.verification import parse_citation, verify_citation

ICON = {"verified": "[OK]", "metadata_mismatch": "[!]", "not_found": "[X]", "ambiguous": "[?]"}


def main() -> None:
    source = build_live_metadata_source(["openalex", "arxiv"], mailto="you@example.com")
    print("Verifying 2 citations against OpenAlex + arXiv ...\n")
    cases = [
        (
            'Vaswani et al., "Attention Is All You Need", arXiv:1706.03762',
            dict(title="Attention Is All You Need", arxiv_id="1706.03762"),
        ),
        (
            '(LLM-fabricated) "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks"',
            dict(title="Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks"),
        ),
    ]
    for label, fields in cases:
        result = verify_citation(parse_citation(**fields), source)
        print(f"{ICON[result.verdict.value]} {result.verdict.value.upper():18} (confidence {result.confidence})")
        print(f"    {label}")
        print(f"    sources checked: {', '.join(result.sources_checked)}")
        print(f"    {result.explanation}\n")


if __name__ == "__main__":
    main()
