"""Reference and inline citation formatting."""

from __future__ import annotations

from src.graph import CitationRecord


class CitationFormatter:
    """Formats citations for prototype outputs."""

    def format_inline(self, citation: CitationRecord) -> str:
        if citation.authors:
            lead_author = citation.authors[0].split()[-1]
        else:
            lead_author = citation.title.split()[0]
        year = citation.year if citation.year is not None else "n.d."
        return f"({lead_author}, {year})"

    def format_reference(self, citation: CitationRecord) -> str:
        authors = ", ".join(citation.authors) if citation.authors else "Unknown Author"
        year = citation.year if citation.year is not None else "n.d."
        venue = f" {citation.venue}." if citation.venue else ""
        return f"{authors} ({year}). {citation.title}.{venue}"
