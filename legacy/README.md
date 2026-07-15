# Legacy Writing-Agent Prototype

This directory holds CiteGuard's original "falsification-first writing agent"
prototype: an experimental pipeline that planned an outline, decomposed claims,
wrote constrained sections, and abstained from unverifiable citations
(`orchestrator/`, `planner/`, `writer/`), plus its FastAPI surface (`api/`),
writing-benchmark builders (`benchmark_baselines.py`,
`benchmark_dataset_builder.py`), driver scripts (`scripts/`), and test
(`tests/`).

It is **not part of the published `citationguard` package**. CiteGuard's
product is the citation-verification library, CLI, and MCP server under
`citeguard.*`; this prototype only exists in the source checkout for
historical reference and is unmaintained.

Run it from the repository root of a source checkout:

```bash
python3 legacy/scripts/run_agent.py --topic "citation hallucination" --support-mode heuristic
python3 legacy/scripts/evaluate.py --topic "citation hallucination" --support-mode heuristic
python3 -m unittest legacy.tests.test_writer
```

The modules import live `citeguard.*` code (graph, retrieval, verifiers), so
they may break as the product evolves; no compatibility is promised.
