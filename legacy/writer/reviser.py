"""Conservative rewriting helpers."""

from __future__ import annotations


class ConservativeReviser:
    """Rewrites strong claims into softer, evidence-aware statements."""

    REPLACEMENTS = (
        ("has become", "has emerged as"),
        ("has focused on", "often focuses on"),
        ("typically", "often"),
        ("still struggle", "can struggle"),
        ("should prioritize", "could prioritize"),
    )

    def rewrite(self, claim_text: str) -> str:
        rewritten = claim_text
        for old, new in self.REPLACEMENTS:
            rewritten = rewritten.replace(old, new)
        if rewritten == claim_text:
            rewritten = f"Available evidence suggests that {claim_text[0].lower()}{claim_text[1:]}"
        return rewritten
