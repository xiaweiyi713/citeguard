"""Reference and inline citation formatting."""

from __future__ import annotations

import re

from citeguard.graph import CitationRecord


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

    def format_bibtex(self, citation: CitationRecord) -> str:
        """Return a conservative, pasteable BibTeX entry from canonical metadata."""

        lead = citation.authors[0].split()[-1] if citation.authors else "citeguard"
        key_seed = re.sub(r"[^a-z0-9]+", "", lead.lower()) or "citeguard"
        year = str(citation.year) if citation.year is not None else "nd"
        title_word = next(iter(re.findall(r"[A-Za-z0-9]+", citation.title)), "record").lower()
        fields = [
            f"  title = {{{_bibtex_escape(citation.title)}}}",
            f"  author = {{{' and '.join(_bibtex_escape(author) for author in citation.authors) or 'Unknown Author'}}}",
            f"  year = {{{year}}}",
        ]
        if citation.venue:
            fields.append(f"  journal = {{{_bibtex_escape(citation.venue)}}}")
        if citation.doi:
            fields.append(f"  doi = {{{citation.doi}}}")
        if citation.url:
            fields.append(f"  url = {{{_bibtex_escape(citation.url)}}}")
        return f"@article{{{key_seed}{year}{title_word},\n" + ",\n".join(fields) + "\n}"

    def format_gbt7714(self, citation: CitationRecord) -> str:
        """Return a pasteable GB/T 7714-style reference from canonical metadata."""

        authors = ", ".join(citation.authors) if citation.authors else "佚名"
        year = str(citation.year) if citation.year is not None else "日期不详"
        type_code = "J" if citation.venue else "EB/OL"
        venue = f". {citation.venue}, {year}" if citation.venue else f", {year}"
        identifier = f". DOI: {citation.doi}" if citation.doi else f". {citation.url}" if citation.url else ""
        return f"{authors}. {citation.title}[{type_code}]{venue}{identifier}."


def _bibtex_escape(value: str) -> str:
    return str(value).replace("\\", "\\textbackslash{} ").replace("{", "\\{").replace("}", "\\}")
