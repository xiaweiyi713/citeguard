"""Claim decomposition utilities."""

from __future__ import annotations

from typing import List

from src.graph import Claim

from .outline_planner import OutlineSection


class ClaimDecomposer:
    """Converts section plans into atomic scientific claims."""

    def decompose(self, topic: str, section: OutlineSection) -> List[Claim]:
        lower_title = section.title.lower()

        if "background" in lower_title:
            templates = [
                "{topic} has become a prominent research topic because trustworthy evidence use is now a central system requirement.",
                "Existing work on {topic} typically combines retrieval, generation, and evaluation, but reliability remains uneven.",
            ]
        elif "recent advances" in lower_title:
            templates = [
                "Recent advances in {topic} have focused on retrieval augmentation, stronger evaluators, and better task-specific benchmarks.",
                "Despite progress, many systems in {topic} still optimize fluency more directly than verifiability.",
            ]
        else:
            templates = [
                "Current approaches to {topic} still struggle with verification gaps, weak abstention, and unreliable citation grounding.",
                "Future research in {topic} should prioritize auditable reasoning, explicit uncertainty handling, and claim-level evidence verification.",
            ]

        claims: List[Claim] = []
        for index, template in enumerate(templates, start=1):
            claims.append(
                Claim(
                    claim_id=f"{section.section_id}-claim-{index}",
                    section_id=section.section_id,
                    text=template.format(topic=topic),
                    strength="strong" if index == 1 else "moderate",
                )
            )
        return claims
