"""Tests for verifier modules."""

import unittest

from src.citation.proposer import CandidateCitation
from src.graph import CitationRecord, Claim
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verifiers import (
    ContradictionVerifier,
    EnsembleSupportPolicy,
    ExistenceVerifier,
    MetadataVerifier,
    HeuristicSupportBackend,
    SupportAssessment,
    SupportVerifier,
    combine_support_assessments,
)


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.record = CitationRecord(
            citation_id="ghostcite",
            title="GhostCite: Citation Validity in the Age of Large Language Models",
            authors=["Zhe Xu"],
            year=2026,
            venue="arXiv",
            abstract="This paper studies phantom references and fabricated metadata in large language models.",
        )
        self.source = InMemoryMetadataSource([self.record])
        self.claim = Claim(
            claim_id="claim-1",
            section_id="section-1",
            text="Recent work studies phantom references and fabricated metadata in large language models.",
        )

    def test_existence_and_metadata_verifiers_pass_on_matching_record(self):
        candidate = CandidateCitation(
            claim_id=self.claim.claim_id,
            citation=self.record,
            retrieval_score=0.9,
            rationale="test",
        )
        existence_finding, canonical = ExistenceVerifier().verify(self.claim, candidate, self.source)
        metadata_finding = MetadataVerifier().verify(self.claim, candidate, canonical)
        self.assertTrue(existence_finding.passed)
        self.assertTrue(metadata_finding.passed)

    def test_support_verifier_detects_alignment(self):
        finding, evidence = SupportVerifier().verify(self.claim, self.record)
        self.assertTrue(finding.passed)
        self.assertGreater(evidence.support_score, 0.14)
        self.assertEqual(finding.details["backend"], "ensemble_support")

    def test_contradiction_verifier_flags_negative_evidence(self):
        contradictory = CitationRecord(
            citation_id="contradictory",
            title="Negative Result",
            authors=["A. Author"],
            year=2025,
            abstract="However, evidence is weak and no reliable support was found for the proposed method.",
        )
        finding = ContradictionVerifier().verify(self.claim, contradictory)
        self.assertFalse(finding.passed)

    def test_support_verifier_reranks_sentence_level_evidence(self):
        citation = CitationRecord(
            citation_id="sentence-rerank",
            title="General Paper on Writing Systems",
            authors=["A. Author"],
            year=2025,
            abstract=(
                "This paper surveys unrelated software engineering issues. "
                "It analyzes phantom references and fabricated metadata in large language models."
            ),
        )
        claim = Claim(
            claim_id="claim-2",
            section_id="section-1",
            text="The literature analyzes phantom references and fabricated metadata in large language models.",
        )
        verifier = SupportVerifier(backend=HeuristicSupportBackend())
        finding, evidence = verifier.verify(claim, citation)
        self.assertTrue(finding.passed)
        self.assertTrue(evidence.source_field.startswith("abstract_sentence_"))
        self.assertIn("phantom", evidence.text.lower())

    def test_support_verifier_uses_structured_metadata_evidence_chunks(self):
        citation = CitationRecord(
            citation_id="metadata-chunk",
            title="Generic Paper",
            authors=["A. Author"],
            year=2025,
            abstract="This paper studies unrelated optimization issues.",
            metadata={
                "evidence_chunks": [
                    {
                        "text": "It analyzes phantom references and fabricated metadata in large language models.",
                        "source_field": "openalex_remote_1_paragraph_1",
                        "source_url": "https://example.org/paper",
                    }
                ]
            },
        )
        verifier = SupportVerifier(backend=HeuristicSupportBackend())
        finding, evidence = verifier.verify(self.claim, citation)
        self.assertTrue(finding.passed)
        self.assertEqual(evidence.source_field, "openalex_remote_1_paragraph_1")
        self.assertEqual(evidence.source_url, "https://example.org/paper")

    def test_combine_support_assessments_respects_pairing_policy(self):
        assessment = combine_support_assessments(
            [
                SupportAssessment(
                    backend_name="transformers_nli",
                    score=0.33,
                    passed=False,
                    rationale="nli",
                    details={"probabilities": {"entailment": 0.33, "contradiction": 0.04}},
                ),
                SupportAssessment(
                    backend_name="sentence_transformer_reranker",
                    score=0.82,
                    passed=True,
                    rationale="reranker",
                    details={},
                ),
                SupportAssessment(
                    backend_name="heuristic_support",
                    score=0.24,
                    passed=True,
                    rationale="heuristic",
                    details={"overlap_terms": ["phantom", "metadata"]},
                ),
            ],
            policy=EnsembleSupportPolicy(
                weights={
                    "transformers_nli": 0.55,
                    "sentence_transformer_reranker": 0.30,
                    "heuristic_support": 0.15,
                },
                pair_nli_floor=0.30,
                pair_combined_threshold=0.28,
                contradiction_max=0.10,
                fallback_combined_threshold=0.48,
            ),
        )
        self.assertTrue(assessment.passed)
        self.assertEqual(assessment.details["decision_path"], "paired_reranker_nli")


if __name__ == "__main__":
    unittest.main()
