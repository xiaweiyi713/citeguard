"""Extract citation candidates from manuscript-like text files."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from xml.etree import ElementTree

from .parse import extract_arxiv_id, extract_doi, extract_year, parse_gbt7714_reference

REFERENCE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(references|bibliography|works cited|参考文献)\s*$",
    re.IGNORECASE,
)
NEXT_SECTION_RE = re.compile(r"^\s*(?:#{1,6}\s+\S|\\(?:section|chapter|subsection)\*?\{.+\})")
REFERENCE_ITEM_RE = re.compile(r"^\s*(?:\[\d+\]|\d+[.)]|\-\s+|\*\s+)\s*(.+)$")
BIBTEX_ENTRY_RE = re.compile(r"@\w+\s*[\{\(]\s*([^,\s]+)\s*,(.*?)(?=\n\s*@\w+\s*[\{\(]|\Z)", re.DOTALL)
BIBTEX_STRING_RE = re.compile(r"@string\s*[\{\(]\s*([^=,\s]+)\s*=\s*(.*?)(?=\n\s*@\w+\s*[\{\(]|\Z)", re.DOTALL | re.IGNORECASE)
BIBITEM_RE = re.compile(
    r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}\s*(.*?)(?=\\bibitem(?:\[[^\]]*\])?\{|\\end\{thebibliography\}|\Z)",
    re.DOTALL,
)


def load_citation_candidates(path: str, source_format: str = "auto") -> List[dict]:
    """Load a text-like file and extract citation candidate objects."""

    active_format = _resolve_format(path, source_format)
    if active_format == "docx":
        text = _read_docx_text(path)
        return _annotate_source_path(
            extract_citation_candidates(text, source_format=active_format),
            source_path=path,
        )

    text = Path(path).read_text(encoding="utf-8")
    candidates = _annotate_source_path(
        extract_citation_candidates(text, source_format=active_format),
        source_path=path,
    )
    if active_format in {"latex", "tex"}:
        latex_parts = _latex_document_parts(path, text)
        for tex_path, tex_text in latex_parts[1:]:
            included_candidates = extract_citation_candidates(tex_text, source_format=active_format)
            candidates.extend(_annotate_source_path(included_candidates, source_path=str(tex_path)))
        for tex_path, tex_text in latex_parts:
            for bib_path in _latex_bibliography_paths(tex_text, source_path=str(tex_path)):
                if not bib_path.exists() or not bib_path.is_file():
                    continue
                bib_candidates = extract_citation_candidates(
                    bib_path.read_text(encoding="utf-8"),
                    source_format="bibtex",
                )
                candidates.extend(_annotate_source_path(bib_candidates, source_path=str(bib_path)))
    return _dedupe_candidates(candidates)


def _latex_document_parts(path: str, text: str) -> List[Tuple[Path, str]]:
    root = Path(path)
    parts: List[Tuple[Path, str]] = [(root, text)]
    seen: Set[str] = {str(root.resolve())}

    def visit(source_path: Path, source_text: str) -> None:
        for include_path in _latex_input_paths(source_text, source_path=source_path):
            key = str(include_path.resolve())
            if key in seen:
                continue
            if not include_path.exists() or not include_path.is_file():
                continue
            seen.add(key)
            include_text = include_path.read_text(encoding="utf-8")
            parts.append((include_path, include_text))
            visit(include_path, include_text)

    visit(root, text)
    return parts


def _latex_input_paths(text: str, source_path: Path) -> List[Path]:
    base_dir = source_path.parent
    paths = []
    seen = set()
    for match in re.finditer(r"\\(?:input|include)\{([^}]+)\}", text):
        raw_name = match.group(1).strip()
        if not raw_name or "://" in raw_name:
            continue
        candidate = Path(raw_name)
        if candidate.suffix == "":
            candidate = candidate.with_suffix(".tex")
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        paths.append(candidate)
    return paths


def extract_citation_candidates(text: str, source_format: str = "auto") -> List[dict]:
    """Extract conservative citation candidates as JSON-ready dictionaries."""

    if not text.strip():
        return []

    candidates = []
    if source_format in {"auto", "bibtex", "latex", "tex"}:
        candidates.extend(_extract_bibtex(text))
    if source_format in {"auto", "latex", "tex", "bbl"}:
        candidates.extend(_extract_bibitems(text))
    if source_format in {"auto", "markdown", "md", "text", "txt", "docx", "latex", "tex", "bbl"}:
        candidates.extend(_extract_reference_lines(text))

    return _annotate_extraction_order(_dedupe_candidates(candidates), source_format=source_format)


def _resolve_format(path: str, source_format: str) -> str:
    if source_format != "auto":
        return source_format.lower()
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        return "docx"
    if suffix in {".tex", ".latex"}:
        return "latex"
    if suffix == ".bbl":
        return "bbl"
    if suffix in {".bib"}:
        return "bibtex"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    return "text"


def _extract_bibtex(text: str) -> List[dict]:
    candidates: List[Dict[str, Any]] = []
    string_macros = _parse_bibtex_strings(text)
    for match in BIBTEX_ENTRY_RE.finditer(text):
        key = match.group(1).strip()
        body = _strip_bibtex_entry_tail(match.group(2))
        fields = _parse_bibtex_fields(body, string_macros=string_macros)
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


def _parse_bibtex_strings(text: str) -> Dict[str, str]:
    macros: Dict[str, str] = {}
    for match in BIBTEX_STRING_RE.finditer(text):
        name = match.group(1).strip().lower()
        body = _strip_bibtex_entry_tail(match.group(2))
        value, _ = _read_bibtex_value(body, 0, string_macros=macros)
        normalized = _normalize_bibtex_value(value)
        if name and normalized:
            macros[name] = normalized
    return macros


def _strip_bibtex_entry_tail(body: str) -> str:
    body = body.strip()
    if body.endswith(("}", ")")):
        return body[:-1].strip()
    return body


def _parse_bibtex_fields(body: str, string_macros: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    active_macros = string_macros or {}
    index = 0
    length = len(body)
    while index < length:
        field_match = re.search(r"([A-Za-z][A-Za-z0-9_-]*)\s*=", body[index:])
        if not field_match:
            break
        name = field_match.group(1).lower()
        value_start = index + field_match.end()
        value, value_end = _read_bibtex_value(body, value_start, string_macros=active_macros)
        if value_end <= value_start:
            index = value_start + 1
            continue
        fields[name] = _normalize_bibtex_value(value)
        index = value_end
    return fields


def _read_bibtex_value(
    text: str,
    start: int,
    string_macros: Optional[Dict[str, str]] = None,
) -> Tuple[str, int]:
    parts: List[str] = []
    active_macros = string_macros or {}
    index = start
    length = len(text)
    while index < length:
        value, index = _read_bibtex_value_atom(text, index, string_macros=active_macros)
        if value:
            parts.append(value)
        while index < length and text[index].isspace():
            index += 1
        if index < length and text[index] == "#":
            index += 1
            continue
        break
    return " ".join(part.strip() for part in parts if part.strip()), index


def _read_bibtex_value_atom(
    text: str,
    start: int,
    string_macros: Optional[Dict[str, str]] = None,
) -> Tuple[str, int]:
    active_macros = string_macros or {}
    index = start
    length = len(text)
    while index < length and text[index].isspace():
        index += 1
    if index >= length:
        return "", index
    if text[index] == "{":
        depth = 1
        value_start = index + 1
        index += 1
        while index < length and depth > 0:
            char = text[index]
            if char == "\\":
                index += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            index += 1
        value_end = index - 1 if depth == 0 else index
        return text[value_start:value_end], index
    if text[index] == '"':
        value_start = index + 1
        index += 1
        escaped = False
        while index < length:
            char = text[index]
            if char == '"' and not escaped:
                return text[value_start:index], index + 1
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
            index += 1
        return text[value_start:index], index
    value_start = index
    while index < length and text[index] not in ",\n\r#":
        index += 1
    value = text[value_start:index].strip()
    return active_macros.get(value.lower(), value), index


def _normalize_bibtex_value(value: str) -> str:
    value = _clean_reference_text(value.replace("\n", " "))
    value = value.replace("\\&", "&")
    return re.sub(r"\s+", " ", value).strip()


def _extract_bibitems(text: str) -> List[dict]:
    candidates = []
    for match in BIBITEM_RE.finditer(text):
        key = match.group(1).strip()
        raw_text = _clean_reference_text(match.group(2))
        if _looks_like_citation(raw_text):
            candidates.append(_candidate(raw_text=raw_text, source_type="bibitem", source_id=key))
    return candidates


def _latex_bibliography_paths(text: str, source_path: str) -> List[Path]:
    base_dir = Path(source_path).parent
    paths = []
    seen = set()
    patterns = [
        re.compile(r"\\bibliography\{([^}]+)\}"),
        re.compile(r"\\addbibresource(?:\[[^\]]*\])?\{([^}]+)\}"),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            for raw_name in match.group(1).split(","):
                name = raw_name.strip()
                if not name or "://" in name:
                    continue
                candidate = Path(name)
                if candidate.suffix == "":
                    candidate = candidate.with_suffix(".bib")
                if not candidate.is_absolute():
                    candidate = base_dir / candidate
                key = str(candidate)
                if key in seen:
                    continue
                seen.add(key)
                paths.append(candidate)
    return paths


def _extract_reference_lines(text: str) -> List[dict]:
    lines = text.splitlines()
    items: List[Dict[str, Any]] = []
    in_refs = False
    saw_reference_heading = False
    current: List[str] = []
    current_start: Optional[int] = None
    current_end: Optional[int] = None

    for line_number, line in enumerate(lines, start=1):
        if REFERENCE_HEADING_RE.match(line):
            in_refs = True
            saw_reference_heading = True
            _flush_reference_item(items, current, current_start, current_end)
            current = []
            current_start = None
            current_end = None
            continue
        if in_refs and NEXT_SECTION_RE.match(line) and not REFERENCE_ITEM_RE.match(line):
            break
        if not in_refs:
            continue

        stripped = line.strip()
        if not stripped:
            _flush_reference_item(items, current, current_start, current_end)
            current = []
            current_start = None
            current_end = None
            continue

        item_match = REFERENCE_ITEM_RE.match(stripped)
        if item_match:
            _flush_reference_item(items, current, current_start, current_end)
            current = [item_match.group(1)]
            current_start = line_number
            current_end = line_number
        elif current:
            current.append(stripped)
            current_end = line_number
        elif _looks_like_citation(stripped):
            current = [stripped]
            current_start = line_number
            current_end = line_number

    _flush_reference_item(items, current, current_start, current_end)
    if not saw_reference_heading and not items:
        return _extract_loose_reference_list(lines)
    return [
        _candidate(
            raw_text=item["raw_text"],
            source_type="reference_section",
            source_line_start=item.get("source_line_start"),
            source_line_end=item.get("source_line_end"),
        )
        for item in items
    ]


def _extract_loose_reference_list(lines: List[str]) -> List[dict]:
    items: List[Dict[str, Any]] = []
    current: List[str] = []
    current_indent = 0
    current_start: Optional[int] = None
    current_end: Optional[int] = None
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            _flush_reference_item(items, current, current_start, current_end)
            current = []
            current_indent = 0
            current_start = None
            current_end = None
            continue
        if _is_loose_reference_syntax_line(stripped):
            _flush_reference_item(items, current, current_start, current_end)
            current = []
            current_indent = 0
            current_start = None
            current_end = None
            continue
        item_match = REFERENCE_ITEM_RE.match(stripped)
        if item_match:
            _flush_reference_item(items, current, current_start, current_end)
            current = [item_match.group(1)]
            current_indent = _leading_whitespace_width(line)
            current_start = line_number
            current_end = line_number
        elif current and _leading_whitespace_width(line) > current_indent:
            current.append(stripped)
            current_end = line_number
        elif current and _looks_like_loose_standalone_reference(stripped):
            _flush_reference_item(items, current, current_start, current_end)
            current = []
            current_indent = 0
            current_start = None
            current_end = None
            _flush_reference_item(items, [stripped], line_number, line_number)
        elif current and _looks_like_citation(stripped):
            current.append(stripped)
            current_end = line_number
        elif current:
            _flush_reference_item(items, current, current_start, current_end)
            current = []
            current_indent = 0
            current_start = None
            current_end = None
        elif _looks_like_loose_standalone_reference(stripped):
            _flush_reference_item(items, [stripped], line_number, line_number)
    _flush_reference_item(items, current, current_start, current_end)
    return [
        _candidate(
            raw_text=item["raw_text"],
            source_type="reference_list",
            source_line_start=item.get("source_line_start"),
            source_line_end=item.get("source_line_end"),
        )
        for item in items
    ]


def _leading_whitespace_width(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_loose_reference_syntax_line(text: str) -> bool:
    if text.startswith((r"\bibitem", r"\begin{thebibliography}", r"\end{thebibliography}")):
        return True
    if re.match(r"^@\w+\s*[\{\(]", text):
        return True
    if re.match(r"^[A-Za-z][A-Za-z0-9_-]*\s*=", text):
        return True
    return text in {"}", ")"}


def _flush_reference_item(
    items: List[dict],
    parts: List[str],
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
) -> None:
    text = _clean_reference_text(" ".join(parts))
    if _looks_like_citation(text):
        item: Dict[str, Any] = {"raw_text": text}
        if line_start is not None:
            item["source_line_start"] = line_start
        if line_end is not None:
            item["source_line_end"] = line_end
        items.append(item)


def _candidate(
    raw_text: str,
    source_type: str,
    source_id: str = "",
    source_line_start: Optional[int] = None,
    source_line_end: Optional[int] = None,
) -> dict:
    item: Dict[str, Any] = {
        "raw_text": raw_text,
        "source_type": source_type,
    }
    if source_id:
        item["source_id"] = source_id
    if source_line_start is not None:
        item["source_line_start"] = source_line_start
    if source_line_end is not None:
        item["source_line_end"] = source_line_end
    doi = extract_doi(raw_text)
    if doi:
        item["doi"] = doi
    arxiv_id = extract_arxiv_id(raw_text)
    if arxiv_id:
        item["arxiv_id"] = arxiv_id
    year = extract_year(raw_text)
    if year is not None:
        item["year"] = year
    gbt = parse_gbt7714_reference(raw_text)
    if gbt:
        item["title"] = gbt["title"]
        item["authors"] = list(gbt["authors"])
        if gbt["venue"]:
            item["venue"] = gbt["venue"]
        item["reference_format"] = "gbt7714"
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


def _looks_like_loose_standalone_reference(text: str) -> bool:
    if len(text) < 30:
        return False
    if extract_doi(text) or extract_arxiv_id(text):
        return True
    if extract_year(text) is None:
        return False
    has_author_marker = bool(
        re.search(r"\b[A-Z][A-Za-z'`-]+,\s+(?:[A-Z]\.|[A-Z][A-Za-z'`-]+)", text)
        or re.search(r"\bet\s+al\.", text, re.IGNORECASE)
        or re.search(r"\b[A-Z][A-Za-z'`-]+\s+and\s+[A-Z][A-Za-z'`-]+\b", text)
    )
    has_source_marker = bool(
        re.search(
            r"\b(?:journal|proceedings|conference|transactions|letters|review|arxiv|press|neurips|icml|acl|cvpr)\b",
            text,
            re.IGNORECASE,
        )
    )
    return has_author_marker and has_source_marker


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


def _annotate_extraction_order(candidates: Iterable[dict], source_format: str) -> List[dict]:
    annotated = []
    for index, candidate in enumerate(candidates, start=1):
        item = dict(candidate)
        item.setdefault("source_format", source_format)
        item.setdefault("source_index", index)
        item.setdefault("source_locator", f"citation-{index}")
        annotated.append(item)
    return annotated


def _annotate_source_path(candidates: Iterable[dict], source_path: str) -> List[dict]:
    annotated = []
    for index, candidate in enumerate(candidates, start=1):
        item = dict(candidate)
        item["source_path"] = source_path
        item["source_index"] = int(item.get("source_index") or index)
        item["source_locator"] = f"{source_path}#citation-{item['source_index']}"
        annotated.append(item)
    return annotated


def _read_docx_text(path: str) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise OSError(f"Could not read DOCX file {path!r}: {exc}") from exc
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", namespace):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        if texts:
            paragraphs.append("".join(texts))
    return "\n".join(paragraphs)
