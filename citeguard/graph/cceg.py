"""Core Claim-Citation-Evidence Graph models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RelationType(str, Enum):
    """Supported relation types inside the graph."""

    RETRIEVED_FROM = "retrieved_from"
    SUPPORTS = "supports"
    WEAK_SUPPORTS = "weak_supports"
    CONTRADICTS = "contradicts"
    UNVERIFIED = "unverified"


class ActionType(str, Enum):
    """Allowed claim-level actions after verification."""

    CITE = "cite"
    REWRITE = "rewrite"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class Claim:
    """Atomic scientific statement that must be verified before writing."""

    claim_id: str
    section_id: str
    text: str
    strength: str = "strong"


@dataclass(frozen=True)
class CitationRecord:
    """Citation candidate and its metadata."""

    citation_id: str
    title: str
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: str = ""
    abstract: str = ""
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""
    source: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceSpan:
    """Evidence snippet used to support or reject a claim."""

    evidence_id: str
    citation_id: str
    text: str
    source_field: str = "abstract"
    source_url: str = ""
    support_score: float = 0.0


@dataclass(frozen=True)
class VerificationFinding:
    """Output produced by an individual verifier."""

    claim_id: str
    citation_id: str
    verifier_name: str
    passed: bool
    score: float
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaimCitationLink:
    """Edge between a claim and a citation candidate."""

    claim_id: str
    citation_id: str
    relation: RelationType
    score: float
    evidence_id: str = ""


@dataclass(frozen=True)
class ClaimDecision:
    """Final action selected for a claim after verification and gating."""

    claim_id: str
    action: ActionType
    reason: str
    risk_score: float
    selected_citation_ids: List[str] = field(default_factory=list)
    rewritten_claim: str = ""


@dataclass
class CCEG:
    """In-memory Claim-Citation-Evidence Graph."""

    claims: Dict[str, Claim] = field(default_factory=dict)
    citations: Dict[str, CitationRecord] = field(default_factory=dict)
    evidence: Dict[str, EvidenceSpan] = field(default_factory=dict)
    findings: List[VerificationFinding] = field(default_factory=list)
    links: List[ClaimCitationLink] = field(default_factory=list)
    decisions: Dict[str, ClaimDecision] = field(default_factory=dict)

    def add_claim(self, claim: Claim) -> None:
        self.claims[claim.claim_id] = claim

    def add_citation(self, citation: CitationRecord) -> None:
        self.citations[citation.citation_id] = citation

    def add_evidence(self, evidence: EvidenceSpan) -> None:
        self.evidence[evidence.evidence_id] = evidence

    def add_finding(self, finding: VerificationFinding) -> None:
        self.findings.append(finding)

    def add_link(self, link: ClaimCitationLink) -> None:
        self.links.append(link)

    def set_decision(self, decision: ClaimDecision) -> None:
        self.decisions[decision.claim_id] = decision

    def claim_links(self, claim_id: str) -> List[ClaimCitationLink]:
        return [link for link in self.links if link.claim_id == claim_id]

    def claim_findings(self, claim_id: str) -> List[VerificationFinding]:
        return [finding for finding in self.findings if finding.claim_id == claim_id]

    def claim_findings_for_citation(self, claim_id: str, citation_id: str) -> List[VerificationFinding]:
        return [
            finding
            for finding in self.findings
            if finding.claim_id == claim_id and finding.citation_id == citation_id
        ]

    def evidence_for_claim(self, claim_id: str) -> List[EvidenceSpan]:
        evidence_ids = {
            link.evidence_id
            for link in self.links
            if link.claim_id == claim_id and link.evidence_id
        }
        return [self.evidence[evidence_id] for evidence_id in evidence_ids if evidence_id in self.evidence]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claims": {claim_id: asdict(claim) for claim_id, claim in self.claims.items()},
            "citations": {
                citation_id: asdict(citation)
                for citation_id, citation in self.citations.items()
            },
            "evidence": {
                evidence_id: asdict(evidence)
                for evidence_id, evidence in self.evidence.items()
            },
            "findings": [asdict(finding) for finding in self.findings],
            "links": [asdict(link) for link in self.links],
            "decisions": {
                claim_id: asdict(decision)
                for claim_id, decision in self.decisions.items()
            },
        }
