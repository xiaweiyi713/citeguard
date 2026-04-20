"""End-to-end CiteGuard pipeline."""

from __future__ import annotations

from typing import List, Optional, Tuple

from src.audit import AuditReportBuilder
from src.citation import CitationProposer
from src.graph import CCEG, ActionType, ClaimCitationLink, InMemoryGraphStore, RelationType
from src.planner import ClaimDecomposer, OutlinePlanner
from src.retrieval import HybridRetriever, MetadataSourceRetriever
from src.retrieval.scholarly_clients import MetadataSource
from src.verifiers import (
    ContradictionVerifier,
    ExistenceVerifier,
    MetadataVerifier,
    RiskFusion,
    SupportVerifier,
    UncertaintyGate,
)
from src.writer import AbstentionController, ConstrainedWriter

from .policies import RiskPolicy
from .states import AgentRunResult, AgentTask, SectionDraft


class CiteGuardAgent:
    """Main entry point for the Falsification-First writing pipeline."""

    def __init__(
        self,
        metadata_source: MetadataSource,
        retriever: Optional[HybridRetriever] = None,
        planner: Optional[OutlinePlanner] = None,
        claim_decomposer: Optional[ClaimDecomposer] = None,
        proposer: Optional[CitationProposer] = None,
        graph_store: Optional[InMemoryGraphStore] = None,
        risk_policy: Optional[RiskPolicy] = None,
        support_verifier: Optional[SupportVerifier] = None,
    ) -> None:
        self.metadata_source = metadata_source
        records = metadata_source.all_records()
        self.retriever = retriever or (
            HybridRetriever(records) if records else MetadataSourceRetriever(metadata_source)
        )
        self.planner = planner or OutlinePlanner()
        self.claim_decomposer = claim_decomposer or ClaimDecomposer()
        self.proposer = proposer or CitationProposer()
        self.graph_store = graph_store or InMemoryGraphStore()
        self.risk_policy = risk_policy or RiskPolicy()
        self.existence_verifier = ExistenceVerifier()
        self.metadata_verifier = MetadataVerifier()
        self.support_verifier = support_verifier or SupportVerifier()
        self.contradiction_verifier = ContradictionVerifier()
        self.risk_fusion = RiskFusion()
        self.gate = UncertaintyGate(
            cite_threshold=self.risk_policy.cite_threshold,
            rewrite_threshold=self.risk_policy.rewrite_threshold,
        )
        self.abstention_controller = AbstentionController()
        self.writer = ConstrainedWriter()
        self.audit_builder = AuditReportBuilder()

    def run(self, task: AgentTask) -> AgentRunResult:
        self.graph_store.reset()
        graph = self.graph_store.graph
        sections = self.planner.plan(task.topic, section_count=task.section_count)
        section_drafts: List[SectionDraft] = []

        for section in sections:
            claims = self.claim_decomposer.decompose(task.topic, section)
            for claim in claims:
                graph.add_claim(claim)
                self._resolve_claim(graph, claim, task)
            text = self.writer.write_section(
                section=section,
                claims=claims,
                decisions=graph.decisions,
                citations_by_id=graph.citations,
            )
            section_drafts.append(
                SectionDraft(section_id=section.section_id, title=section.title, text=text)
            )

        references = self.writer.build_references(graph.decisions.values(), graph.citations)
        audit_report = self.audit_builder.build(
            graph=graph,
            sections=[{"section_id": draft.section_id, "title": draft.title, "text": draft.text} for draft in section_drafts],
            references=references,
        )
        return AgentRunResult(
            sections=section_drafts,
            references=references,
            audit_report=audit_report,
            graph=self.graph_store.snapshot(),
        )

    def _resolve_claim(self, graph: CCEG, claim, task: AgentTask) -> None:
        retrieved = self.retriever.search(claim.text, top_k=task.retrieval_top_k)
        candidates = self.proposer.propose(claim, retrieved, top_k=task.candidate_top_k)

        best_choice = None
        for candidate in candidates:
            graph.add_citation(candidate.citation)
            graph.add_link(
                ClaimCitationLink(
                    claim_id=claim.claim_id,
                    citation_id=candidate.citation.citation_id,
                    relation=RelationType.RETRIEVED_FROM,
                    score=candidate.retrieval_score,
                )
            )

            findings, canonical, support_evidence = self._verify_candidate(claim, candidate)
            canonical_record = canonical or candidate.citation
            graph.add_citation(canonical_record)
            for finding in findings:
                graph.add_finding(finding)
            graph.add_evidence(support_evidence)

            risk_profile = self.risk_fusion.combine(findings)
            gate_decision = self.gate.evaluate(
                citation_id=canonical_record.citation_id,
                risk_profile=risk_profile,
                findings=findings,
            )

            relation = self._relation_from_findings(findings)
            graph.add_link(
                ClaimCitationLink(
                    claim_id=claim.claim_id,
                    citation_id=canonical_record.citation_id,
                    relation=relation,
                    score=1.0 - risk_profile.risk_score,
                    evidence_id=support_evidence.evidence_id,
                )
            )

            decision = self.abstention_controller.build_decision(claim, gate_decision, risk_profile)
            choice = (
                self._decision_rank(decision.action),
                1.0 - decision.risk_score,
                decision,
            )
            if best_choice is None or choice > best_choice:
                best_choice = choice

        if best_choice is None:
            from src.graph import ClaimDecision

            graph.set_decision(
                ClaimDecision(
                    claim_id=claim.claim_id,
                    action=ActionType.ABSTAIN,
                    reason="No candidate citations were retrieved for this claim.",
                    risk_score=1.0,
                )
            )
            return

        graph.set_decision(best_choice[2])

    def _verify_candidate(self, claim, candidate) -> Tuple[list, object, object]:
        existence_finding, canonical = self.existence_verifier.verify(
            claim=claim,
            candidate=candidate,
            metadata_source=self.metadata_source,
        )
        record = canonical or candidate.citation
        metadata_finding = self.metadata_verifier.verify(claim, candidate, canonical)
        support_finding, evidence = self.support_verifier.verify(claim, record)
        contradiction_finding = self.contradiction_verifier.verify(claim, record)
        return (
            [existence_finding, metadata_finding, support_finding, contradiction_finding],
            canonical,
            evidence,
        )

    def _relation_from_findings(self, findings) -> RelationType:
        support_finding = next(
            (finding for finding in findings if finding.verifier_name == "SupportVerifier"),
            None,
        )
        contradiction_finding = next(
            (finding for finding in findings if finding.verifier_name == "ContradictionVerifier"),
            None,
        )
        if contradiction_finding is not None and not contradiction_finding.passed:
            return RelationType.CONTRADICTS
        if support_finding is not None and support_finding.passed:
            return RelationType.SUPPORTS
        if support_finding is not None and support_finding.score > 0:
            return RelationType.WEAK_SUPPORTS
        return RelationType.UNVERIFIED

    def _decision_rank(self, action: ActionType) -> int:
        if action == ActionType.CITE:
            return 2
        if action == ActionType.REWRITE:
            return 1
        return 0
