"""Claim-evidence mapping construction and auditing."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from src.agent.core.source_ranking import (
    _GENERIC_TOPIC_ANCHOR_TERMS,
    _STOPWORDS,
    _has_traceable_source,
    _source_dedupe_key,
    _source_tier,
    _tokenize,
    _uid_to_resolvable_url,
)


def _analysis_score_for_rq(rq: str, a: Dict[str, Any]) -> float:
    rq_tokens = {t for t in _tokenize(rq) if t not in _STOPWORDS}
    text = " ".join(
        [
            str(a.get("title") or ""),
            str(a.get("summary") or ""),
            " ".join(a.get("key_findings", []) if isinstance(a.get("key_findings"), list) else []),
        ]
    )
    overlap = len(rq_tokens & set(_tokenize(text)))
    relevance = float(a.get("relevance_score", 0.0) or 0.0)
    tier = _source_tier(a)
    tier_bonus = 0.35 if tier == "A" else (0.15 if tier == "B" else 0.0)
    return relevance + overlap * 0.08 + tier_bonus


def _claim_candidates(src: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    kf = src.get("key_findings", [])
    if isinstance(kf, list):
        for item in kf[:5]:
            s = re.sub(r"\s+", " ", str(item or "")).strip()
            if s:
                out.append(s)
    summary = re.sub(r"\s+", " ", str(src.get("summary") or "")).strip()
    if summary:
        first = re.split(r"(?<=[\.\!\?。！？])\s+", summary)[0].strip()
        if first:
            out.append(first)
    # De-duplicate while preserving order
    seen = set()
    deduped: List[str] = []
    for x in out:
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(x)
    return deduped


def _claim_has_rq_signal(rq: str, claim: str) -> bool:
    rq_tokens = {t for t in _tokenize(rq) if t not in _STOPWORDS}
    if not rq_tokens:
        return True
    claim_tokens = set(_tokenize(claim))
    return bool(rq_tokens & claim_tokens)


def _claim_relevance_ratio(rq: str, claim: str) -> float:
    rq_tokens = {t for t in _tokenize(rq) if t not in _STOPWORDS}
    if not rq_tokens:
        return 1.0
    claim_tokens = set(_tokenize(claim))
    return len(rq_tokens & claim_tokens) / max(1, len(rq_tokens))


def _rq_anchor_terms(rq: str, *, max_terms: int = 4) -> List[str]:
    tokens = [t for t in _tokenize(rq) if t not in _STOPWORDS]
    primary = [t for t in tokens if t not in _GENERIC_TOPIC_ANCHOR_TERMS]
    ordered = primary or tokens
    seen = set()
    out: List[str] = []
    for tok in ordered:
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= max(1, int(max_terms)):
            break
    return out


def _align_claim_to_rq(
    *,
    rq: str,
    claim: str,
    min_relevance: float = 0.20,
    anchor_terms_max: int = 4,
) -> str:
    base = re.sub(r"\s+", " ", str(claim or "")).strip()
    if not base:
        return base
    if _claim_relevance_ratio(rq, base) >= float(min_relevance):
        return base

    anchors = _rq_anchor_terms(rq, max_terms=anchor_terms_max)
    if not anchors:
        return base
    anchor_text = ", ".join(anchors)
    aligned = f"Regarding {anchor_text}, evidence suggests that {base[0].lower() + base[1:]}"
    if _claim_relevance_ratio(rq, aligned) >= _claim_relevance_ratio(rq, base):
        return aligned
    return base


def _ensure_unique_claim_text(*, claim_text: str, rq: str, used: set[str]) -> str:
    base = re.sub(r"\s+", " ", str(claim_text or "")).strip()
    if not base:
        base = f"Evidence indicates a meaningful difference related to: {rq}"
    if base.lower() not in used:
        return base

    rq_short = re.sub(r"\s+", " ", str(rq or "")).strip()
    if len(rq_short) > 80:
        rq_short = rq_short[:77] + "..."
    scoped = f"[RQ] {rq_short}: {base}"
    if scoped.lower() not in used:
        return scoped

    i = 2
    while True:
        candidate = f"{scoped} ({i})"
        if candidate.lower() not in used:
            return candidate
        i += 1


def _build_claim_evidence_map(
    *,
    research_questions: List[str],
    analyses: List[Dict[str, Any]],
    core_min_a_ratio: float,
    min_evidence_per_rq: int = 2,
    allow_graceful_degrade: bool = True,
    align_claim_to_rq: bool = True,
    min_claim_rq_relevance: float = 0.20,
    claim_anchor_terms_max: int = 4,
) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    used_claims: set[str] = set()
    min_required = max(1, int(min_evidence_per_rq))
    for rq in research_questions:
        ranked = sorted(analyses, key=lambda a: _analysis_score_for_rq(rq, a), reverse=True)
        if not ranked:
            claims.append(
                {
                    "research_question": rq,
                    "claim": f"Insufficient evidence collected for: {rq}",
                    "evidence": [],
                    "strength": "C",
                    "caveat": "No usable sources were mapped to this question.",
                }
            )
            continue

        def _is_peer_reviewed(a: Dict[str, Any]) -> bool:
            if bool(a.get("peer_reviewed", False)):
                return True
            venue = str(a.get("venue") or a.get("journal") or "").strip()
            src = str(a.get("source") or "").lower()
            if venue and src not in {"arxiv", "web"}:
                return True
            return False

        def _is_arxiv_only(a: Dict[str, Any]) -> bool:
            return str(a.get("source") or "").lower() == "arxiv" and not _is_peer_reviewed(a)

        def _is_high_quality(a: Dict[str, Any]) -> bool:
            tier = _source_tier(a)
            rel = float(a.get("relevance_score", 0.0) or 0.0)
            return _has_traceable_source(a) and tier in {"A", "B"} and rel >= 0.30

        hq_ranked = [a for a in ranked if _is_high_quality(a)]
        peer_ranked = [a for a in hq_ranked if _is_peer_reviewed(a)]
        arxiv_only_ranked = [a for a in hq_ranked if _is_arxiv_only(a)]

        selected: List[Dict[str, Any]] = []
        selected_keys: set[str] = set()

        def _pick(cand: Dict[str, Any]) -> bool:
            k = _source_dedupe_key(cand)
            if k in selected_keys:
                return False
            if _is_arxiv_only(cand):
                arxiv_only_cnt = sum(1 for x in selected if _is_arxiv_only(x))
                if arxiv_only_cnt >= 1:
                    return False
            selected.append(cand)
            selected_keys.add(k)
            return True

        # Priority 1: at least two peer-reviewed evidences if possible.
        for cand in peer_ranked:
            _pick(cand)
            if len(selected) >= 2:
                break

        # Priority 2: at most one arXiv-only supplemental evidence.
        for cand in arxiv_only_ranked:
            if _pick(cand):
                break

        # Priority 3: fill to 3 with remaining high-quality evidences.
        for cand in hq_ranked:
            if len(selected) >= 3:
                break
            _pick(cand)

        # Fallback: keep traceable and diversified if high-quality pool is insufficient.
        for cand in ranked:
            if len(selected) >= 3:
                break
            if not _has_traceable_source(cand):
                continue
            _pick(cand)

        if not selected and ranked:
            selected = [ranked[0]]
            selected_keys = {_source_dedupe_key(ranked[0])}

        # Enforce per-RQ minimum evidence count with relaxed diversity constraints.
        if len(selected) < min_required:
            for cand in ranked:
                if len(selected) >= min_required:
                    break
                if not _has_traceable_source(cand):
                    continue
                k = _source_dedupe_key(cand)
                if k in selected_keys:
                    continue
                selected.append(cand)
                selected_keys.add(k)

        # Strict mode: if still insufficient, allow non-traceable fallback before giving up.
        if len(selected) < min_required and not allow_graceful_degrade:
            for cand in ranked:
                if len(selected) >= min_required:
                    break
                k = _source_dedupe_key(cand)
                if k in selected_keys:
                    continue
                selected.append(cand)
                selected_keys.add(k)
        best = selected[0]
        claim_candidates_list: List[str] = []
        for src in selected:
            claim_candidates_list.extend(_claim_candidates(src))

        claim_text = ""
        for cand in claim_candidates_list:
            if _claim_has_rq_signal(rq, cand) and cand.lower() not in used_claims:
                claim_text = cand
                break
        if not claim_text:
            for cand in claim_candidates_list:
                if cand.lower() not in used_claims:
                    claim_text = cand
                    break
        if align_claim_to_rq:
            claim_text = _align_claim_to_rq(
                rq=rq,
                claim=claim_text,
                min_relevance=min_claim_rq_relevance,
                anchor_terms_max=claim_anchor_terms_max,
            )
        claim_text = _ensure_unique_claim_text(claim_text=claim_text, rq=rq, used=used_claims)
        used_claims.add(claim_text.lower())

        evidence = []
        for src in selected:
            src_url = str(src.get("url") or "").strip() or _uid_to_resolvable_url(str(src.get("uid") or ""))
            src_kf = src.get("key_findings", [])
            snippet = src_kf[0] if isinstance(src_kf, list) and src_kf else str(src.get("summary") or "")[:180]
            peer_reviewed = bool(src.get("peer_reviewed", False)) or bool(
                str(src.get("venue") or src.get("journal") or "").strip()
                and str(src.get("source") or "").lower() not in {"arxiv", "web"}
            )
            is_arxiv_only = str(src.get("source") or "").lower() == "arxiv" and not peer_reviewed
            high_quality = _is_high_quality(src)
            evidence.append(
                {
                    "uid": src.get("uid"),
                    "title": src.get("title"),
                    "url": src_url,
                    "tier": _source_tier(src),
                    "snippet": str(snippet).strip(),
                    "peer_reviewed": peer_reviewed,
                    "is_arxiv_only": is_arxiv_only,
                    "high_quality": high_quality,
                    "venue": str(src.get("venue") or src.get("journal") or ""),
                    "pdf_source": str(src.get("pdf_source") or ""),
                }
            )

        a_count = sum(1 for e in evidence if e["tier"] == "A")
        ab_count = sum(1 for e in evidence if e["tier"] in {"A", "B"})
        peer_count = sum(1 for e in evidence if e.get("peer_reviewed"))
        hq_count = sum(1 for e in evidence if e.get("high_quality"))
        arxiv_only_count = sum(1 for e in evidence if e.get("is_arxiv_only"))
        a_ratio = (a_count / max(1, len(evidence)))
        if hq_count >= 3 and peer_count >= 2 and arxiv_only_count <= 1 and a_ratio >= core_min_a_ratio:
            strength = "A"
        elif hq_count >= 2 and peer_count >= 1:
            strength = "B"
        else:
            strength = "C"

        limitations = best.get("limitations", [])
        caveat = limitations[0] if isinstance(limitations, list) and limitations else "Evidence may be domain-specific."
        if len(evidence) < min_required:
            shortfall_note = (
                f"Evidence below minimum ({len(evidence)}/{min_required}) after retrieval; "
                "treat this claim as provisional."
            )
            caveat = f"{caveat} {shortfall_note}".strip()

        claims.append(
            {
                "research_question": rq,
                "claim": claim_text,
                "evidence": evidence[:3],
                "strength": strength,
                "caveat": caveat,
            }
        )
    return claims


def _build_evidence_audit_log(
    *,
    research_questions: List[str],
    claim_map: List[Dict[str, Any]],
    core_min_a_ratio: float,
) -> List[Dict[str, Any]]:
    logs: List[Dict[str, Any]] = []
    for rq in research_questions:
        rq_claims = [c for c in claim_map if c.get("research_question") == rq]
        evidences = [e for c in rq_claims for e in c.get("evidence", [])]
        a_cnt = sum(1 for e in evidences if e.get("tier") == "A")
        ab_cnt = sum(1 for e in evidences if e.get("tier") in {"A", "B"})
        peer_cnt = sum(1 for e in evidences if bool(e.get("peer_reviewed", False)))
        hq_cnt = sum(1 for e in evidences if bool(e.get("high_quality", False)))
        arxiv_only_cnt = sum(1 for e in evidences if bool(e.get("is_arxiv_only", False)))
        a_ratio = (a_cnt / max(1, len(evidences))) if evidences else 0.0
        gaps: List[str] = []
        if len(evidences) < 3:
            gaps.append("evidence_count_below_3")
        if hq_cnt < 3:
            gaps.append("high_quality_evidence_below_3")
        if peer_cnt < 2:
            gaps.append("peer_reviewed_evidence_below_2")
        if arxiv_only_cnt > 1:
            gaps.append("arxiv_only_exceeds_1")
        if len(evidences) < 2:
            gaps.append("evidence_count_below_2")
        if ab_cnt < 2:
            gaps.append("ab_evidence_below_2")
        if a_ratio < core_min_a_ratio:
            gaps.append("a_ratio_below_threshold")
        logs.append(
            {
                "research_question": rq,
                "claims_count": len(rq_claims),
                "evidence_count": len(evidences),
                "a_count": a_cnt,
                "ab_count": ab_cnt,
                "peer_reviewed_count": peer_cnt,
                "high_quality_count": hq_cnt,
                "arxiv_only_count": arxiv_only_cnt,
                "a_ratio": round(a_ratio, 3),
                "gaps": gaps,
            }
        )
    return logs


def _format_claim_map(claim_map: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for i, c in enumerate(claim_map, 1):
        parts.append(f"{i}. Claim ({c.get('strength', 'C')}): {c.get('claim', '')}")
        parts.append(f"   RQ: {c.get('research_question', '')}")
        for e in c.get("evidence", []):
            parts.append(
                f"   - [{e.get('tier', 'C')}] {e.get('title', 'Unknown')} "
                f"({e.get('url') or e.get('uid') or 'no-id'})"
            )
        parts.append(f"   Caveat: {c.get('caveat', '')}")
    return "\n".join(parts) if parts else "(no claim-evidence map)"
