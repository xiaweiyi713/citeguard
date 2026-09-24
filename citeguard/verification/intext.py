"""Link in-text citation markers to extracted bibliography entries."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .extract import NEXT_SECTION_RE, REFERENCE_HEADING_RE, _line_number_at_offset
from .parse import extract_year


LATEX_CITE_RE = re.compile(
    r"\\(?P<cmd>cite|citep|citet|citealp|citealt|parencite|textcite|autocite)"
    r"(?:\[[^\]]*\]){0,2}"
    r"\{(?P<keys>[^}]+)\}"
)
MD_NUMERIC_RE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\](?!\()")
CN_NUMERIC_RE = re.compile(r"[【［](\d+(?:\s*[,;，、]\s*\d+)*)[】］]")
MD_PANDOC_RE = re.compile(r"\[@([A-Za-z][\w:.-]*(?:\s*;\s*@?[A-Za-z][\w:.-]*)*)\]")
AUTHOR_YEAR_RE = re.compile(
    r"[（(](?P<authors>[^()（）]{1,80}?)[，,]\s*(?P<year>(?:19|20)\d{2}[a-z]?)[）)]"
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")
LATEX_COMMENT_RE = re.compile(r"(?<!\\)%.*?$", re.MULTILINE)
THEBIBLIOGRAPHY_RE = re.compile(
    r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}",
    re.DOTALL | re.IGNORECASE,
)

SKIP_INTEXT_SUFFIXES = frozenset({".bib", ".bbl", ".docx"})


def link_document_citations(
    documents: Sequence[Mapping[str, Any]],
    bibliography: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return in-text links and unresolved markers for Markdown/LaTeX bodies."""

    catalog = _bibliography_catalog(bibliography)
    links: List[Dict[str, Any]] = []
    unlinked: List[Dict[str, Any]] = []
    seen = set()
    for document in documents:
        path = str(document.get("path", ""))
        text = str(document.get("text", ""))
        source_format = str(document.get("source_format") or _format_from_path(path))
        if Path(path).suffix.lower() in SKIP_INTEXT_SUFFIXES:
            continue
        if source_format in {"bibtex", "bbl", "docx"}:
            continue
        body, _refs, _start = _split_body_and_references(text, source_format)
        for marker in _extract_markers(body, source_format, path):
            key = (
                marker["path"],
                marker["line_start"],
                marker["char_start"],
                marker["raw_marker"],
                marker["cite_key"],
            )
            if key in seen:
                continue
            seen.add(key)
            linked = _link_marker(marker, catalog, bibliography)
            if linked["link_status"] == "unlinked":
                unlinked.append(linked)
            else:
                links.append(linked)
    return {
        "schema_version": 1,
        "body_links": links,
        "unlinked_markers": unlinked,
        "bibliography_count": len(bibliography),
        "in_text_count": len(links) + len(unlinked),
    }


def _format_from_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".tex", ".latex"}:
        return "latex"
    if suffix == ".bib":
        return "bibtex"
    if suffix == ".bbl":
        return "bbl"
    return "text"


def _split_body_and_references(text: str, source_format: str) -> Tuple[str, str, int]:
    if source_format in {"latex", "tex"}:
        stripped = THEBIBLIOGRAPHY_RE.sub("", text)
        return stripped, "", 1
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if REFERENCE_HEADING_RE.match(line):
            body = "\n".join(lines[:index])
            refs = "\n".join(lines[index:])
            return body, refs, index + 1
        if source_format in {"markdown", "md", "text", "txt"} and NEXT_SECTION_RE.match(line):
            continue
    return text, "", 1


def _strip_latex_comments(text: str) -> str:
    return LATEX_COMMENT_RE.sub("", text)


def _extract_markers(text: str, source_format: str, path: str) -> List[Dict[str, Any]]:
    if source_format in {"latex", "tex"}:
        searchable = _strip_latex_comments(text)
        return _markers_from_regex(searchable, LATEX_CITE_RE, path, source_format, kind="latex_key")
    markers: List[Dict[str, Any]] = []
    markers.extend(_markers_from_regex(text, MD_NUMERIC_RE, path, source_format, kind="numeric"))
    markers.extend(_markers_from_regex(text, CN_NUMERIC_RE, path, source_format, kind="numeric"))
    markers.extend(_markers_from_regex(text, MD_PANDOC_RE, path, source_format, kind="pandoc_key"))
    markers.extend(_author_year_markers(text, path, source_format))
    markers.sort(key=lambda item: (item["line_start"], item["char_start"]))
    return markers


def _markers_from_regex(
    text: str,
    pattern: re.Pattern[str],
    path: str,
    source_format: str,
    *,
    kind: str,
) -> List[Dict[str, Any]]:
    markers: List[Dict[str, Any]] = []
    for match in pattern.finditer(text):
        raw_keys = match.group("keys") if "keys" in match.groupdict() and match.group("keys") else match.group(1)
        keys = _split_cite_keys(raw_keys, kind=kind)
        sentence, paragraph, attachment, candidates = _context_for_offset(text, match.start())
        for key in keys:
            markers.append(
                _marker_payload(
                    path=path,
                    source_format=source_format,
                    kind=kind,
                    raw_marker=match.group(0),
                    cite_key=key,
                    line_start=_line_number_at_offset(text, match.start()),
                    char_start=match.start(),
                    char_end=match.end(),
                    sentence=sentence,
                    paragraph=paragraph,
                    attachment=attachment,
                    attachment_candidates=candidates,
                )
            )
    return markers


def _author_year_markers(text: str, path: str, source_format: str) -> List[Dict[str, Any]]:
    markers: List[Dict[str, Any]] = []
    for match in AUTHOR_YEAR_RE.finditer(text):
        sentence, paragraph, attachment, candidates = _context_for_offset(text, match.start())
        year = match.group("year")
        authors = match.group("authors").strip()
        markers.append(
            _marker_payload(
                path=path,
                source_format=source_format,
                kind="author_year",
                raw_marker=match.group(0),
                cite_key=f"{authors}|{year}",
                line_start=_line_number_at_offset(text, match.start()),
                char_start=match.start(),
                char_end=match.end(),
                sentence=sentence,
                paragraph=paragraph,
                attachment=attachment,
                attachment_candidates=candidates,
                extra={"authors": authors, "year": year},
            )
        )
    return markers


def _marker_payload(
    *,
    path: str,
    source_format: str,
    kind: str,
    raw_marker: str,
    cite_key: str,
    line_start: int,
    char_start: int,
    char_end: int,
    sentence: str,
    paragraph: str,
    attachment: str,
    attachment_candidates: List[str],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "path": path,
        "source_format": source_format,
        "kind": kind,
        "raw_marker": raw_marker,
        "cite_key": cite_key,
        "line_start": line_start,
        "char_start": char_start,
        "char_end": char_end,
        "sentence": sentence,
        "paragraph": paragraph,
        "attachment": attachment,
        "attachment_candidates": attachment_candidates,
        "locator": f"{path}#line-{line_start}" if path else f"line-{line_start}",
    }
    if extra:
        payload.update(extra)
    return payload


def _split_cite_keys(raw: str, *, kind: str) -> List[str]:
    if kind == "numeric":
        return [part.strip() for part in re.split(r"[,;，、]", raw) if part.strip()]
    if kind == "pandoc_key":
        return [part.strip().lstrip("@") for part in raw.split(";") if part.strip()]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _context_for_offset(text: str, offset: int) -> Tuple[str, str, str, List[str]]:
    paragraphs = re.split(r"\n\s*\n", text)
    cursor = 0
    paragraph = text.strip()
    paragraph_start = 0
    for block in paragraphs:
        end = cursor + len(block)
        if cursor <= offset <= end:
            paragraph = block.strip()
            paragraph_start = cursor
            break
        cursor = end + 2
    sentences = [part.strip() for part in SENTENCE_SPLIT_RE.split(paragraph) if part.strip()]
    if not sentences:
        return paragraph, paragraph, "paragraph", [paragraph] if paragraph else []
    relative = max(0, offset - paragraph_start)
    walked = 0
    chosen = sentences[0]
    for sentence in sentences:
        walked += len(sentence)
        if relative <= walked + 2:
            chosen = sentence
            break
        walked += 1
    attachment = "sentence"
    candidates = [chosen]
    if len(sentences) > 1 and chosen != paragraph:
        candidates.append(paragraph)
        # A citation after a blank-line-free paragraph can belong to the
        # previous sentence; keep both candidates visible instead of guessing.
        if relative > 0 and not chosen.endswith((".", "!", "?", "。", "！", "？")):
            attachment = "ambiguous"
    return chosen, paragraph, attachment, candidates


def _bibliography_catalog(bibliography: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_key: Dict[str, List[int]] = {}
    by_numeric: Dict[str, List[int]] = {}
    for index, candidate in enumerate(bibliography):
        source_id = str(candidate.get("source_id") or "").strip()
        if source_id:
            by_key.setdefault(source_id.lower(), []).append(index)
        source_index = candidate.get("source_index")
        if isinstance(source_index, int) and source_index > 0:
            by_numeric.setdefault(str(source_index), []).append(index)
        raw = str(candidate.get("raw_text") or "")
        numbered = re.match(r"^\s*(?:\[(\d+)\]|【(\d+)】|［(\d+)］|(\d+)[.)])\s+", raw)
        if numbered:
            number = next(group for group in numbered.groups() if group)
            by_numeric.setdefault(number, []).append(index)
    return {"by_key": by_key, "by_numeric": by_numeric}


def _link_marker(
    marker: Mapping[str, Any],
    catalog: Mapping[str, Any],
    bibliography: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    kind = str(marker.get("kind", ""))
    matches: List[int] = []
    if kind in {"latex_key", "pandoc_key"}:
        matches = list(catalog["by_key"].get(str(marker.get("cite_key", "")).lower(), []))
    elif kind == "numeric":
        matches = list(catalog["by_numeric"].get(str(marker.get("cite_key", "")), []))
    elif kind == "author_year":
        matches = _match_author_year(bibliography, str(marker.get("authors", "")), str(marker.get("year", "")))

    payload = dict(marker)
    if not matches:
        payload.update(
            {
                "link_status": "unlinked",
                "bibliography_index": None,
                "bibliography_indexes": [],
                "reason": "no_bibliography_match",
            }
        )
        return payload
    if len(matches) > 1:
        payload.update(
            {
                "link_status": "ambiguous",
                "bibliography_index": None,
                "bibliography_indexes": matches,
                "reason": "multiple_bibliography_matches",
            }
        )
        return payload
    index = matches[0]
    candidate = bibliography[index]
    payload.update(
        {
            "link_status": "linked",
            "bibliography_index": index,
            "bibliography_indexes": [index],
            "bibliography_locator": candidate.get("source_locator") or candidate.get("document_locator") or "",
            "bibliography_source_id": candidate.get("source_id", ""),
            "reason": "matched",
        }
    )
    return payload


def _match_author_year(bibliography: Sequence[Mapping[str, Any]], authors: str, year: str) -> List[int]:
    year_value = _year_int(year)
    if year_value is None:
        return []
    needle = authors.lower()
    matches: List[int] = []
    for index, candidate in enumerate(bibliography):
        candidate_year = candidate.get("year")
        if not isinstance(candidate_year, int):
            candidate_year = extract_year(str(candidate.get("raw_text") or ""))
        if candidate_year != year_value:
            continue
        names = _candidate_last_names(candidate)
        raw = str(candidate.get("raw_text") or "").lower()
        if any(name.lower() in needle for name in names if len(name) >= 3) or any(
            part.lower() in raw for part in re.split(r"\s+and\s+|,|;|&", authors) if len(part.strip()) >= 3
        ):
            matches.append(index)
    return matches


def _candidate_last_names(candidate: Mapping[str, Any]) -> List[str]:
    names: List[str] = []
    for author in candidate.get("authors") or []:
        parts = [part for part in re.split(r"\s+", str(author).replace(",", " ")) if part]
        if parts:
            names.append(parts[-1])
    raw = str(candidate.get("raw_text") or "")
    leading = re.match(r"^\s*(?:\[\d+\]|\d+[.)])?\s*([^.,]+)", raw)
    if leading:
        token = leading.group(1).strip().split()
        if token:
            names.append(token[0])
    return names


def _year_int(value: str) -> Optional[int]:
    match = re.search(r"((?:19|20)\d{2})", str(value or ""))
    if not match:
        return None
    return int(match.group(1))
