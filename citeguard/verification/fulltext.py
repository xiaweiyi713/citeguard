"""Section-aware full-text units and claim evidence location."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

from citeguard.citation import tokenize_text


HEADING_REGIONS = (
    ("abstract", re.compile(r"^(?:abstract|摘要)\s*$", re.I)),
    ("introduction", re.compile(r"^\d+(?:\.\d+)*\s+introduction\s*$", re.I)),
    ("related_work", re.compile(r"^\d+(?:\.\d+)*\s+(?:related work|background|prior work)\s*$", re.I)),
    ("methods", re.compile(r"^\d+(?:\.\d+)*\s+(?:method|methods|approach|architecture)\s*$", re.I)),
    ("experiments", re.compile(r"^\d+(?:\.\d+)*\s+(?:experiment|experiments|results|evaluation)\s*$", re.I)),
    ("limitations", re.compile(r"^\d+(?:\.\d+)*\s+(?:limitation|limitations|discussion|conclusion|conclusions)\s*$", re.I)),
    ("references", re.compile(r"^(?:references|bibliography|works cited|参考文献)\s*$", re.I)),
)
BARE_INTRODUCTION = re.compile(r"^introduction\s*$", re.I)
QUANT_RE = re.compile(r"\d|%|\berror\b|\baccuracy\b|\bbleu\b|\boutperform|\bbenchmark\b|\bdataset\b", re.I)
UNIVERSAL_RE = re.compile(r"\bevery\b|\ball\b|\balways\b|所有|全部", re.I)
LIMITING_RE = re.compile(r"\bonly\b|\blimited\b|\bcannot\b|仅|只报告", re.I)


def split_fulltext_units(text: str) -> List[Dict[str, Any]]:
    """Split manuscript text into region-tagged units with character offsets."""

    if not text:
        return []
    lines = text.splitlines(keepends=True)
    units: List[Dict[str, Any]] = []
    current_region = "other"
    current_heading = ""
    current_start = 0
    current_parts: List[str] = []
    offset = 0

    def flush(end: int) -> None:
        nonlocal current_start, current_parts, current_heading
        body = "".join(current_parts)
        stripped = body.strip()
        if stripped:
            lead = len(body) - len(body.lstrip())
            units.append(
                {
                    "region": current_region,
                    "heading": current_heading,
                    "text": stripped,
                    "char_start": current_start + lead,
                    "char_end": current_start + lead + len(stripped),
                }
            )
        current_parts = []
        current_heading = ""
        current_start = end

    for line in lines:
        heading_region = _heading_region(line.strip())
        if heading_region:
            flush(offset)
            current_region = heading_region
            current_heading = line.strip()
            current_start = offset + len(line)
            offset += len(line)
            continue
        if not current_parts:
            current_start = offset
        current_parts.append(line)
        offset += len(line)
    flush(offset)
    if not units and text.strip():
        stripped = text.strip()
        lead = len(text) - len(text.lstrip())
        units.append(
            {
                "region": "other",
                "heading": "",
                "text": stripped,
                "char_start": lead,
                "char_end": lead + len(stripped),
            }
        )
    return units


def locate_claim_evidence(claim: str, text: str, *, retrieved_at: str = "") -> Dict[str, Any]:
    """Return supporting and conflicting full-text spans without claiming a full-paper review."""

    units = split_fulltext_units(text)
    quantitative = bool(QUANT_RE.search(claim))
    universal = bool(UNIVERSAL_RE.search(claim))
    scored = []
    for unit in units:
        score = _overlap_score(claim, unit["text"])
        if quantitative and unit["region"] == "experiments":
            score += 0.35
        if unit["region"] == "references":
            score -= 0.5
        scored.append((score, unit))
    scored.sort(key=lambda item: item[0], reverse=True)

    supporting: List[Dict[str, Any]] = []
    conflicting: List[Dict[str, Any]] = []
    for score, unit in scored:
        item = dict(unit)
        item["score"] = round(max(score, 0.0), 4)
        if unit["region"] == "references":
            continue
        if universal and unit["region"] == "limitations" and LIMITING_RE.search(unit["text"]):
            conflicting.append(item)
            continue
        if score > 0:
            supporting.append(item)

    if quantitative:
        supporting.sort(key=lambda item: (item["region"] != "experiments", -item["score"]))
    inspected = sorted({unit["region"] for unit in units})
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "supporting_spans": supporting[:5],
        "conflicting_spans": conflicting[:5],
        "units": units,
        "evidence_coverage": {
            "scope": "full_text",
            "complete_paper_reviewed": False,
            "regions_inspected": inspected,
            "note": "Finding a supporting span is not a complete-paper review.",
        },
        "snapshot": {
            "sha256": digest,
            "retrieved_at": retrieved_at or None,
            "char_count": len(text),
        },
    }


def build_located_fulltext_chunks(
    text: str,
    *,
    source_url: str = "",
    source_name: str = "",
    max_chunks: int = 60,
) -> List[Dict[str, Any]]:
    """Turn region-tagged units into evidence chunks the support pipeline already consumes."""

    chunks: List[Dict[str, Any]] = []
    for index, unit in enumerate(split_fulltext_units(text), start=1):
        if len(chunks) >= max_chunks:
            break
        if unit["region"] == "references":
            continue
        chunks.append(
            {
                "text": unit["text"],
                "source_field": f"oa_full_text_{unit['region']}_{index}",
                "source_url": source_url,
                "source_name": source_name,
                "evidence_scope": "full_text",
                "region": unit["region"],
                "heading": unit["heading"],
                "char_start": unit["char_start"],
                "char_end": unit["char_end"],
                "source_locator": (
                    f"{source_url}#chars-{unit['char_start']}-{unit['char_end']}"
                    if source_url
                    else f"fulltext-{unit['region']}-{index}"
                ),
            }
        )
    return chunks


def _heading_region(line: str) -> Optional[str]:
    stripped = line.strip()
    if not stripped:
        return None
    for region, pattern in HEADING_REGIONS:
        if pattern.match(stripped):
            return region
    if BARE_INTRODUCTION.match(stripped):
        return "introduction"
    numbered = re.match(r"^\d+(?:\.\d+)*\s+(.+)$", stripped)
    if numbered:
        title = numbered.group(1).strip().lower()
        mapping = {
            "introduction": "introduction",
            "related work": "related_work",
            "background": "related_work",
            "method": "methods",
            "methods": "methods",
            "approach": "methods",
            "architecture": "methods",
            "experiment": "experiments",
            "experiments": "experiments",
            "results": "experiments",
            "evaluation": "experiments",
            "limitation": "limitations",
            "limitations": "limitations",
            "discussion": "limitations",
            "conclusion": "limitations",
            "conclusions": "limitations",
        }
        return mapping.get(title)
    return None


def _overlap_score(claim: str, evidence: str) -> float:
    claim_tokens = set(tokenize_text(claim))
    evidence_tokens = set(tokenize_text(evidence))
    if not claim_tokens or not evidence_tokens:
        return 0.0
    overlap = claim_tokens & evidence_tokens
    return len(overlap) / max(len(claim_tokens), 1)
