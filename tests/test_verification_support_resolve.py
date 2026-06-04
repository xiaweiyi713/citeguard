"""End-to-end check_claim_support over an in-memory source (no models, no network)."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verifiers import SupportAssessment
from src.verification.parse import parse_citation
from src.verification.support import SupportVerdict, check_claim_support


class _FakeEnsembleBackend:
    def assess(self, claim_text, evidence_text):
        probs = {"entailment": 0.82, "contradiction": 0.05, "neutral": 0.13} if "improves" in evidence_text else {"entailment": 0.1, "contradiction": 0.1, "neutral": 0.8}
        return SupportAssessment(
            backend_name="ensemble_support", score=0.6, passed=True, rationale="x",
            details={"components": [{"backend": "transformers_nli", "score": probs["entailment"], "passed": True, "details": {"probabilities": probs}}]},
        )


class CheckClaimSupportTests(unittest.TestCase):
    def setUp(self):
        self.paper = CitationRecord(
            citation_id="p1", title="Method M for Task T", abstract="We show method M improves task T accuracy.",
            authors=["A. Author"], year=2024, source="memory",
        )
        self.source = InMemoryMetadataSource([self.paper])

    def test_supported_end_to_end(self):
        candidate = parse_citation(title="Method M for Task T", year=2024)
        result = check_claim_support("Method M improves task T.", candidate, self.source, backend=_FakeEnsembleBackend())
        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.resolution["verdict"], "matched")

    def test_unresolved_paper_is_insufficient_not_unsupported(self):
        candidate = parse_citation(title="A Paper That Does Not Exist Anywhere")
        result = check_claim_support("Some claim.", candidate, self.source, backend=_FakeEnsembleBackend())
        self.assertEqual(result.verdict, SupportVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(result.resolution["verdict"], "not_found")


if __name__ == "__main__":
    unittest.main()
