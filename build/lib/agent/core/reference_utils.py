"""Shared reference extraction utilities.

Both the critic (nodes.py) and the validator (validate_run_outputs.py) must
use the **same** logic to count evidence URLs so their results are consistent.
"""
from __future__ import annotations

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ── Patterns for arXiv / DOI identifiers ────────────────────────────────

_ARXIV_ID_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
_DOI_RE = re.compile(r"\b(10\.\d{4,}/[^\s\)\]\"]+)")


def extract_reference_urls(report: str) -> List[str]:
    """Extract deduplicated evidence URLs from the References section of a report.

    Rules (S2 / S3 from the remediation plan):
    1. Only URLs inside a ``References`` / ``Bibliography`` / ``参考文献`` heading
       are counted as evidence references.
    2. URLs in other sections (e.g. Experimental Blueprint dataset links) are
       **not** counted.
    3. If no References section exists, fall back to scanning the whole report
       (graceful degradation for legacy reports).
    4. arXiv identifiers and DOIs are normalised to URLs before counting.
    """
    lines = report.splitlines()
    target_lines: List[str] = []
    in_refs = False
    ref_level = 7
    found_ref_section = False

    for line in lines:
        s = line.strip()
        ref_match = re.match(
            r"^\s{0,3}(#{1,6})\s*(?:\d+\.?\s*)?(References|Bibliography|参考文献)\s*$",
            s,
            flags=re.IGNORECASE,
        )
        if ref_match:
            in_refs = True
            found_ref_section = True
            ref_level = len(ref_match.group(1))
            continue

        if in_refs:
            heading_match = re.match(r"^\s{0,3}(#{1,6})\s+", s)
            if heading_match and len(heading_match.group(1)) <= ref_level:
                in_refs = False
                continue
            target_lines.append(line)

    if not found_ref_section:
        target_lines = lines

    urls: List[str] = []
    for line in target_lines:
        s = line.strip()
        if not s:
            continue
        if re.match(r"^(?:[-*+]|\d+[.)])\s+", s):
            # First, pick up explicit HTTP(S) URLs
            for m in re.finditer(r"https?://[^\s\)\]]+", s):
                urls.append(m.group(0).rstrip(".,"))
            # S3: Also resolve arXiv identifiers to URLs
            for m in _ARXIV_ID_RE.finditer(s):
                url = f"https://arxiv.org/abs/{m.group(1)}"
                urls.append(url)
            # S3: Also resolve bare DOIs to URLs (skip if already captured as doi.org URL)
            for m in _DOI_RE.finditer(s):
                doi = m.group(1).rstrip(".,")
                url = f"https://doi.org/{doi}"
                if url not in urls:
                    urls.append(url)

    deduped: List[str] = []
    seen: set[str] = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)
    return deduped


def normalize_reference_line(line: str) -> Tuple[str, List[str]]:
    """S3: Normalise arXiv / DOI text identifiers into URL form within a single reference line.

    Returns (normalised_line, list_of_warnings).
    """
    warnings: List[str] = []
    result = line

    # Convert arXiv:xxxx to URL if no URL already present for it
    for m in _ARXIV_ID_RE.finditer(line):
        arxiv_id = m.group(1)
        url = f"https://arxiv.org/abs/{arxiv_id}"
        if url not in line:
            result = result.replace(m.group(0), f"[arXiv:{arxiv_id}]({url})")

    # Convert bare DOIs (not already in a doi.org URL) to URL
    for m in _DOI_RE.finditer(result):
        doi = m.group(1).rstrip(".,")
        doi_url = f"https://doi.org/{doi}"
        if doi_url not in result and "doi.org" not in m.group(0):
            result = result.replace(m.group(0), f"[doi:{doi}]({doi_url})")

    return result, warnings


def normalize_references_in_report(report: str) -> str:
    """S3: Post-process report to convert arXiv/DOI identifiers to URLs in the References section."""
    lines = report.splitlines()
    ref_idx = None
    for i, line in enumerate(lines):
        if re.match(
            r"^\s{0,3}#{1,6}\s*(?:\d+\.?\s*)?(References|Bibliography|参考文献)\s*$",
            line.strip(),
            flags=re.IGNORECASE,
        ):
            ref_idx = i
            break

    if ref_idx is None:
        return report

    out = list(lines[: ref_idx + 1])
    for line in lines[ref_idx + 1 :]:
        s = line.strip()
        # Stop at next heading
        if re.match(r"^\s{0,3}#{1,6}\s+", s):
            out.append(line)
            out.extend(lines[lines.index(line) + 1 :])
            break
        if re.match(r"^(?:[-*+]|\d+[.)])\s+", s):
            normalised, warnings = normalize_reference_line(line)
            for w in warnings:
                logger.warning("[S3] %s", w)
            out.append(normalised)
        else:
            out.append(line)
    else:
        # No heading found after references; already added all lines
        pass

    return "\n".join(out)
