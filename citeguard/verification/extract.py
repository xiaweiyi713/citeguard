"""Extract citation candidates from manuscript-like text files."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Iterable, List
from xml.etree import ElementTree

from .parse import extract_arxiv_id, extract_doi, extract_year

REFERENCE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(references|bibliography|works cited|参考文献)\s*$",
    re.IGNORECASE,
)
NEXT_SECTION_RE = re.compile(r"^\s*(?:#{1,6}\s+\S|\\(?:section|chapter|subsection)\*?\{.+\})")
REFERENCE_ITEM_RE = re.compile(r"^\s*(?:\[\d+\]|\d+[.)]|\-\s+|\*\s+)\s*(.+)$")
BIBTEX_ENTRY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n\s*@\w+\s*\{|\Z)", re.DOTALL)
BIBTEX_FIELD_RE = re.compile(r"(\w+)\s*=\s*(?:\{([^{}]*)\}|\"([^\"]*)\")", re.DOTALL)
BIBITEM_RE = re.compile(
    r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}\s*(.*?)(?=\\bibitem(?:\[[^\]]*\])?\{|\\end\{thebibliography\}|\Z)",
    re.DOTALL,
)


def load_citation_candidates(path: str, source_format: str = "auto") -> List[dict]:
    """Load a text-like file and extract citation candidate objects."""

    active_format = _resolve_format(path, source_format)
    if active_format == "docx":
        text = _read_docx_text(path)
    else:
        text = Path(path).read_text(encoding="utf-8")
    return extract_citation_candidates(text, source_format=active_format)


def extract_citation_candidates(text: str, source_format: str = "auto") -> List[dict]:
    """Extract conservative citation candidates as JSON-ready dictionaries."""

    if not text.strip():
        return []

    candidates = []
    if source_format in {"auto", "bibtex", "latex", "tex"}:
        candidates.extend(_extract_bibtex(text))
    if source_format in {"auto", "latex", "tex"}:
        candidates.extend(_extract_bibitems(text))
    if source_format in {"auto", "markdown", "md", "text", "txt", "docx", "latex", "tex"}:
        candidates.extend(_extract_reference_lines(text))

    return _dedupe_candidates(candidates)


def _resolve_format(path: str, source_format: str) -> str:
    if source_format != "auto":
        return source_format.lower()
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        return "docx"
    if suffix in {".tex", ".latex"}:
        return "latex"
    if suffix in {".bib"}:
        return "bibtex"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    return "text"


def _extract_bibtex(text: str) -> List[dict]:
    candidates = []
    for match in BIBTEX_ENTRY_RE.finditer(text):
        key = match.group(1).strip()
        body = match.group(2).strip().rstrip("}").strip()
        fields = {}
        for field_match in BIBTEX_FIELD_RE.finditer(body):
            value = (field_match.group(2) or field_match.group(3) or "").replace("\n", " ").strip()
            fields[field_match.group(1).lower()] = re.sub(r"\s+", " ", value)
        raw_text = _bibtex_raw_text(fields) or match.group(0).strip()
        item = _candidate(raw_text=raw_text, source_type="bibtex", source_id=key)
        if fields.get("title"):
            item["title"] = fields["title"]
        if fields.get("year"):
            try:
                item["year"] = int(fields["year"])
            except ValueError:
                pass
        if fields.get("doi"):
            item["doi"] = fields["doi"]
        candidates.append(item)
    return candidates


def _extract_bibitems(text: str) -> List[dict]:
    candidates = []
    for match in BIBITEM_RE.finditer(text):
        key = match.group(1).strip()
        raw_text = _clean_reference_text(match.group(2))
        if _looks_like_citation(raw_text):
            candidates.append(_candidate(raw_text=raw_text, source_type="bibitem", source_id=key))
    return candidates


def _extract_reference_lines(text: str) -> List[dict]:
    lines = text.splitlines()
    items = []
    in_refs = False
    current = []

    for line in lines:
        if REFERENCE_HEADING_RE.match(line):
            in_refs = True
            _flush_reference_item(items, current)
            current = []
            continue
        if in_refs and NEXT_SECTION_RE.match(line) and not REFERENCE_ITEM_RE.match(line):
            break
        if not in_refs:
            continue

        stripped = line.strip()
        if not stripped:
            _flush_reference_item(items, current)
            current = []
            continue

        item_match = REFERENCE_ITEM_RE.match(stripped)
        if item_match:
            _flush_reference_item(items, current)
            current = [item_match.group(1)]
        elif current:
            current.append(stripped)
        elif _looks_like_citation(stripped):
            current = [stripped]

    _flush_reference_item(items, current)
    return [_candidate(raw_text=item, source_type="reference_section") for item in items]


def _flush_reference_item(items: List[str], parts: List[str]) -> None:
    text = _clean_reference_text(" ".join(parts))
    if _looks_like_citation(text):
        items.append(text)


def _candidate(raw_text: str, source_type: str, source_id: str = "") -> dict:
    item = {
        "raw_text": raw_text,
        "source_type": source_type,
    }
    if source_id:
        item["source_id"] = source_id
    doi = extract_doi(raw_text)
    if doi:
        item["doi"] = doi
    arxiv_id = extract_arxiv_id(raw_text)
    if arxiv_id:
        item["arxiv_id"] = arxiv_id
    year = extract_year(raw_text)
    if year is not None:
        item["year"] = year
    return item


def _bibtex_raw_text(fields: dict) -> str:
    parts = []
    if fields.get("author"):
        parts.append(fields["author"])
    if fields.get("title"):
        parts.append(fields["title"])
    if fields.get("journal"):
        parts.append(fields["journal"])
    elif fields.get("booktitle"):
        parts.append(fields["booktitle"])
    if fields.get("year"):
        parts.append(fields["year"])
    if fields.get("doi"):
        parts.append(fields["doi"])
    return ". ".join(part for part in parts if part)


def _clean_reference_text(text: str) -> str:
    text = re.sub(r"%.*", "", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?", r"\1", text)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_citation(text: str) -> bool:
    if len(text) < 20:
        return False
    if extract_doi(text) or extract_arxiv_id(text) or extract_year(text):
        return True
    return bool(re.search(r"\b(?:journal|proceedings|conference|arxiv|press)\b", text, re.IGNORECASE))


def _dedupe_candidates(candidates: Iterable[dict]) -> List[dict]:
    seen = set()
    deduped = []
    for candidate in candidates:
        key = json.dumps(
            {
                "raw_text": candidate.get("raw_text", "").lower(),
                "doi": candidate.get("doi", "").lower(),
                "arxiv_id": candidate.get("arxiv_id", "").lower(),
            },
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _read_docx_text(path: str) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", namespace):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        if texts:
            paragraphs.append("".join(texts))
    return "\n".join(paragraphs)
