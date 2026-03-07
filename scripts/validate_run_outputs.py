#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

from src.agent.core.reference_utils import extract_reference_urls as _shared_extract_reference_urls


REQUIRED_STATE_KEYS: Sequence[str] = (
    "topic",
    "research_questions",
    "budget",
    "claim_evidence_map",
    "report_critic",
    "acceptance_metrics",
    "iterations",
    "sources_enabled",
)

ACADEMIC_DOMAINS = {
    "arxiv.org",
    "doi.org",
    "aclanthology.org",
    "openreview.net",
    "ieeexplore.ieee.org",
    "dl.acm.org",
    "link.springer.com",
    "springer.com",
    "semanticscholar.org",
    "jmlr.org",
    "neurips.cc",
}

NOISY_WEB_DOMAINS = {
    "medium.com",
    "reddit.com",
    "linkedin.com",
    "hackernoon.com",
    "dev.to",
    "xcubelabs.com",
}

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "are",
    "what",
    "how",
    "when",
    "where",
    "which",
    "between",
    "agentic",
    "traditional",
    "systems",
    "system",
    "rag",
}


@dataclass
class ValidationConfig:
    min_claim_support_rate: float = 0.80
    min_claim_rq_relevance: float = 0.20
    min_claim_traceability: float = 0.70
    max_web_noise_ratio: float = 0.25
    max_non_academic_ref_ratio: float = 0.15
    min_non_academic_ref_count: int = 3
    require_critic_pass: bool = False
    metrics_tolerance: float = 0.05


@dataclass
class CheckResult:
    name: str
    status: str  # pass | warn | fail
    detail: str


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]{2,}", (text or "").lower())


def _normalize_domain(url: str) -> str:
    if not url:
        return ""
    try:
        netloc = urlparse(url).netloc.lower().strip()
    except Exception:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _is_academic_domain(domain: str) -> bool:
    return domain in ACADEMIC_DOMAINS or domain.endswith(".arxiv.org")


def _looks_mojibake(text: str) -> bool:
    if not text:
        return False
    # "replace char" and common mojibake symbols seen in mis-decoded UTF-8 text.
    if "\ufffd" in text:
        return True
    bad_markers = ("鈹", "锛", "涓", "銆", "鈥", "闂", "瀵", "澶")
    marker_hits = sum(text.count(m) for m in bad_markers)
    return marker_hits >= 2


def _norm_section_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def extract_report_sections(report: str) -> List[str]:
    out: List[str] = []
    for line in report.splitlines():
        s = line.strip()
        if s.startswith("## "):
            out.append(s[3:].strip())
    return out


def core_sections(report: str) -> List[str]:
    sections = []
    for sec in extract_report_sections(report):
        key = sec.lower()
        if "abstract" in key or "reference" in key:
            continue
        sections.append(sec)
    return sections


def extract_reference_urls(report: str) -> List[str]:
    """S2: Delegate to shared implementation for critic/validator consistency."""
    return _shared_extract_reference_urls(report)


def _infer_report_path_from_state_path(state_path: Path) -> Optional[Path]:
    if state_path.name == "research_state.json":
        candidate = state_path.parent / "research_report.md"
        return candidate if candidate.exists() else None

    m = re.search(r"research_state_(\d{8}_\d{6})\.json$", state_path.name)
    if not m:
        return None
    report_name = f"research_report_{m.group(1)}.md"
    legacy_candidate = state_path.parent / report_name
    if legacy_candidate.exists():
        return legacy_candidate

    run_candidate = state_path.parent / f"run_{m.group(1)}" / "research_report.md"
    return run_candidate if run_candidate.exists() else None


def _claim_relevance_ratio(research_question: str, claim: str) -> float:
    rq_tokens = {t for t in _tokenize(research_question) if t not in STOPWORDS}
    claim_tokens = set(_tokenize(claim))
    if not rq_tokens:
        return 1.0
    return len(rq_tokens & claim_tokens) / max(1, len(rq_tokens))


def _claim_report_coverage(report: str, claim_map: Sequence[Dict[str, Any]]) -> float:
    if not claim_map:
        return 0.0
    report_l = report.lower()
    covered = 0
    for item in claim_map:
        claim = str(item.get("claim") or "").strip().lower()
        evidence = item.get("evidence", []) if isinstance(item.get("evidence"), list) else []
        has_claim = bool(claim and claim[:40] in report_l)
        has_ev = False
        for ev in evidence:
            ev_url = str(ev.get("url") or "").strip().lower()
            ev_title = str(ev.get("title") or "").strip().lower()
            if (ev_url and ev_url in report_l) or (ev_title and ev_title[:40] in report_l):
                has_ev = True
                break
        if has_claim and has_ev:
            covered += 1
    return covered / max(1, len(claim_map))


def _compute_metrics_from_evidence_audit(
    evidence_audit_log: Sequence[Dict[str, Any]],
    report_critic: Dict[str, Any],
) -> Dict[str, Any]:
    if not evidence_audit_log:
        return {
            "avg_a_evidence_ratio": 0.0,
            "rq_min2_evidence_rate": 0.0,
            "reference_budget_compliant": "reference_budget_exceeded"
            not in (report_critic.get("issues") or []),
        }

    ratios: List[float] = []
    covered = 0
    for item in evidence_audit_log:
        try:
            ratios.append(float(item.get("a_ratio", 0.0)))
        except Exception:
            ratios.append(0.0)
        if int(item.get("evidence_count", 0) or 0) >= 2:
            covered += 1
    return {
        "avg_a_evidence_ratio": sum(ratios) / max(1, len(ratios)),
        "rq_min2_evidence_rate": covered / max(1, len(evidence_audit_log)),
        "reference_budget_compliant": "reference_budget_exceeded"
        not in (report_critic.get("issues") or []),
    }


def _format_ratio(x: float) -> str:
    return f"{x:.0%}"


def evaluate_run_outputs(
    state: Dict[str, Any],
    report: str,
    cfg: Optional[ValidationConfig] = None,
) -> Dict[str, Any]:
    cfg = cfg or ValidationConfig()
    checks: List[CheckResult] = []

    missing_keys = [k for k in REQUIRED_STATE_KEYS if k not in state]
    if missing_keys:
        checks.append(CheckResult("state_required_fields", "fail", f"Missing keys: {missing_keys}"))
    else:
        checks.append(CheckResult("state_required_fields", "pass", "All required top-level keys present."))

    topic = str(state.get("topic", ""))
    if _looks_mojibake(topic):
        checks.append(CheckResult("topic_encoding", "warn", "Topic appears mojibake/corrupted."))
    else:
        checks.append(CheckResult("topic_encoding", "pass", "Topic encoding looks normal."))

    budget = state.get("budget", {}) if isinstance(state.get("budget"), dict) else {}
    max_sections = int(budget.get("max_sections", 0) or 0)
    report_core_sections = core_sections(report)
    if max_sections > 0 and len(report_core_sections) > max_sections:
        checks.append(
            CheckResult(
                "section_budget",
                "fail",
                f"Core sections {len(report_core_sections)} > budget {max_sections}.",
            )
        )
    else:
        checks.append(
            CheckResult(
                "section_budget",
                "pass",
                f"Core sections {len(report_core_sections)}, budget {max_sections or 'N/A'}.",
            )
        )

    scope = state.get("scope", {}) if isinstance(state.get("scope"), dict) else {}
    allowed_sections = scope.get("allowed_sections", []) if isinstance(scope.get("allowed_sections"), list) else []
    if allowed_sections:
        allowed_norm = {_norm_section_name(s) for s in allowed_sections}
        out_of_scope = [s for s in report_core_sections if _norm_section_name(s) not in allowed_norm]
        if out_of_scope:
            checks.append(
                CheckResult(
                    "scope_section_alignment",
                    "warn",
                    f"{len(out_of_scope)} core section(s) not in allowed scope: {out_of_scope[:3]}",
                )
            )
        else:
            checks.append(CheckResult("scope_section_alignment", "pass", "Report sections align with scope."))
    else:
        checks.append(CheckResult("scope_section_alignment", "pass", "No explicit scope section list provided."))

    max_refs = int(budget.get("max_references", 0) or 0)
    refs = extract_reference_urls(report)
    if max_refs > 0 and len(refs) > max_refs:
        checks.append(CheckResult("reference_budget", "fail", f"References {len(refs)} > budget {max_refs}."))
    else:
        checks.append(CheckResult("reference_budget", "pass", f"References {len(refs)}, budget {max_refs or 'N/A'}."))

    rq_list = state.get("research_questions", []) if isinstance(state.get("research_questions"), list) else []
    claim_map = state.get("claim_evidence_map", []) if isinstance(state.get("claim_evidence_map"), list) else []
    claim_by_rq = {str(x.get("research_question")): x for x in claim_map if isinstance(x, dict)}
    missing_rq_claim = [rq for rq in rq_list if rq not in claim_by_rq]
    if missing_rq_claim:
        checks.append(
            CheckResult(
                "rq_claim_coverage",
                "fail",
                f"Missing claim mapping for {len(missing_rq_claim)} RQ(s).",
            )
        )
    else:
        checks.append(CheckResult("rq_claim_coverage", "pass", f"Claim mapping covers all {len(rq_list)} RQ(s)."))

    min2_support = 0
    low_relevance = 0
    claims = []
    for item in claim_map:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        if claim:
            claims.append(claim.lower())
        evidence = item.get("evidence", []) if isinstance(item.get("evidence"), list) else []
        if len(evidence) >= 2:
            min2_support += 1
        relevance = _claim_relevance_ratio(str(item.get("research_question", "")), claim)
        if relevance < cfg.min_claim_rq_relevance:
            low_relevance += 1
    support_rate = (min2_support / max(1, len(claim_map))) if claim_map else 0.0
    if claim_map and support_rate < cfg.min_claim_support_rate:
        checks.append(
            CheckResult(
                "claim_evidence_support",
                "fail",
                (
                    f"Support rate {_format_ratio(support_rate)} < threshold "
                    f"{_format_ratio(cfg.min_claim_support_rate)}."
                ),
            )
        )
    else:
        checks.append(
            CheckResult(
                "claim_evidence_support",
                "pass",
                f"Support rate {_format_ratio(support_rate)}.",
            )
        )

    duplicate_claims = len(claims) - len(set(claims))
    if duplicate_claims > 0:
        checks.append(CheckResult("claim_uniqueness", "warn", f"Found {duplicate_claims} duplicate claim text(s)."))
    else:
        checks.append(CheckResult("claim_uniqueness", "pass", "Claim texts are unique."))

    if claim_map and low_relevance > 0:
        checks.append(
            CheckResult(
                "claim_rq_relevance",
                "warn",
                (
                    f"{low_relevance}/{len(claim_map)} claims have relevance < "
                    f"{cfg.min_claim_rq_relevance:.2f}."
                ),
            )
        )
    else:
        checks.append(CheckResult("claim_rq_relevance", "pass", "Claim-to-RQ relevance looks good."))

    coverage = _claim_report_coverage(report, claim_map)
    if claim_map and coverage < cfg.min_claim_traceability:
        checks.append(
            CheckResult(
                "claim_report_traceability",
                "warn",
                (
                    f"Traceability {_format_ratio(coverage)} < threshold "
                    f"{_format_ratio(cfg.min_claim_traceability)}."
                ),
            )
        )
    else:
        checks.append(CheckResult("claim_report_traceability", "pass", f"Traceability {_format_ratio(coverage)}."))

    critic = state.get("report_critic", {}) if isinstance(state.get("report_critic"), dict) else {}
    critic_pass = bool(critic.get("pass", False))
    critic_issues = critic.get("issues", []) if isinstance(critic.get("issues"), list) else []
    if critic_pass:
        checks.append(CheckResult("critic_gate", "pass", "Report critic passed."))
    else:
        critic_status = "fail" if cfg.require_critic_pass else "warn"
        checks.append(CheckResult("critic_gate", critic_status, f"Critic did not pass: {critic_issues}"))

    # Critic issue consistency against independent checks.
    section_issue = "section_budget_exceeded" in critic_issues
    section_failed = len(report_core_sections) > max_sections if max_sections > 0 else False
    if section_issue == section_failed:
        checks.append(CheckResult("critic_issue_consistency", "pass", "Critic issues are consistent with checks."))
    else:
        checks.append(
            CheckResult(
                "critic_issue_consistency",
                "warn",
                "Mismatch between critic section issue and independent section-budget check.",
            )
        )

    # Acceptance metrics consistency.
    evidence_audit = state.get("evidence_audit_log", []) if isinstance(state.get("evidence_audit_log"), list) else []
    acceptance = state.get("acceptance_metrics", {}) if isinstance(state.get("acceptance_metrics"), dict) else {}
    computed_metrics = _compute_metrics_from_evidence_audit(evidence_audit, critic)
    missing_metric_fields = [
        k
        for k in ("avg_a_evidence_ratio", "rq_min2_evidence_rate", "reference_budget_compliant")
        if k not in acceptance
    ]
    if missing_metric_fields:
        checks.append(
            CheckResult(
                "acceptance_metrics_consistency",
                "warn",
                f"Missing acceptance metric fields: {missing_metric_fields}",
            )
        )
    else:
        avg_diff = abs(float(acceptance.get("avg_a_evidence_ratio", 0.0)) - computed_metrics["avg_a_evidence_ratio"])
        cov_diff = abs(float(acceptance.get("rq_min2_evidence_rate", 0.0)) - computed_metrics["rq_min2_evidence_rate"])
        ref_match = bool(acceptance.get("reference_budget_compliant")) == bool(
            computed_metrics["reference_budget_compliant"]
        )
        if avg_diff > cfg.metrics_tolerance or cov_diff > cfg.metrics_tolerance or not ref_match:
            checks.append(
                CheckResult(
                    "acceptance_metrics_consistency",
                    "warn",
                    (
                        "State acceptance_metrics differ from recomputed values "
                        f"(avg_diff={avg_diff:.3f}, cov_diff={cov_diff:.3f}, ref_match={ref_match})."
                    ),
                )
            )
        else:
            checks.append(
                CheckResult(
                    "acceptance_metrics_consistency",
                    "pass",
                    "acceptance_metrics consistent with evidence_audit_log and critic issues.",
                )
            )

    papers = state.get("papers", []) if isinstance(state.get("papers"), list) else []
    web_sources = state.get("web_sources", []) if isinstance(state.get("web_sources"), list) else []

    paper_academic = 0
    for p in papers:
        if not isinstance(p, dict):
            continue
        source = str(p.get("source") or "").lower().strip()
        if source in {"arxiv", "semantic_scholar", "google_scholar"}:
            paper_academic += 1
    paper_academic_ratio = (paper_academic / max(1, len(papers))) if papers else 0.0
    if papers and paper_academic_ratio < 0.60:
        checks.append(
            CheckResult(
                "paper_source_mix",
                "warn",
                f"Academic paper ratio {_format_ratio(paper_academic_ratio)} ({paper_academic}/{len(papers)}).",
            )
        )
    else:
        checks.append(
            CheckResult(
                "paper_source_mix",
                "pass",
                f"Academic paper ratio {_format_ratio(paper_academic_ratio)} ({paper_academic}/{len(papers)}).",
            )
        )

    noisy_count = 0
    for w in web_sources:
        if not isinstance(w, dict):
            continue
        domain = _normalize_domain(str(w.get("url") or ""))
        if any(domain == d or domain.endswith(f".{d}") for d in NOISY_WEB_DOMAINS):
            noisy_count += 1
    noisy_ratio = (noisy_count / max(1, len(web_sources))) if web_sources else 0.0
    if web_sources and noisy_ratio > cfg.max_web_noise_ratio:
        checks.append(
            CheckResult(
                "web_noise_ratio",
                "warn",
                (
                    f"Noisy-domain ratio {_format_ratio(noisy_ratio)} > "
                    f"{_format_ratio(cfg.max_web_noise_ratio)} ({noisy_count}/{len(web_sources)})."
                ),
            )
        )
    else:
        checks.append(
            CheckResult(
                "web_noise_ratio",
                "pass",
                f"Noisy-domain ratio {_format_ratio(noisy_ratio)} ({noisy_count}/{len(web_sources)}).",
            )
        )

    ref_domains = [_normalize_domain(u) for u in refs]
    non_academic_refs = [d for d in ref_domains if d and not _is_academic_domain(d)]
    non_acad_ratio = (len(non_academic_refs) / max(1, len(ref_domains))) if ref_domains else 0.0
    if (
        ref_domains
        and len(non_academic_refs) >= cfg.min_non_academic_ref_count
        and non_acad_ratio > cfg.max_non_academic_ref_ratio
    ):
        checks.append(
            CheckResult(
                "reference_domain_profile",
                "warn",
                (
                    f"Non-academic refs {_format_ratio(non_acad_ratio)} ({len(non_academic_refs)}/{len(ref_domains)}) "
                    f"> {_format_ratio(cfg.max_non_academic_ref_ratio)}."
                ),
            )
        )
    else:
        checks.append(
            CheckResult(
                "reference_domain_profile",
                "pass",
                f"Non-academic refs {_format_ratio(non_acad_ratio)} ({len(non_academic_refs)}/{len(ref_domains)}).",
            )
        )

    status_counts = {"pass": 0, "warn": 0, "fail": 0}
    for c in checks:
        status_counts[c.status] += 1
    overall = "fail" if status_counts["fail"] > 0 else ("warn" if status_counts["warn"] > 0 else "pass")
    return {
        "overall": overall,
        "summary": status_counts,
        "config": asdict(cfg),
        "checks": [asdict(x) for x in checks],
    }


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _format_human_report(result: Dict[str, Any], state_path: Path, report_path: Path) -> str:
    lines = [
        "Run Output Validation",
        f"- state: {state_path}",
        f"- report: {report_path}",
        f"- overall: {result['overall']}",
        (
            f"- summary: pass={result['summary']['pass']} "
            f"warn={result['summary']['warn']} fail={result['summary']['fail']}"
        ),
        "",
    ]
    for item in result["checks"]:
        tag = item["status"].upper().ljust(4)
        lines.append(f"[{tag}] {item['name']}: {item['detail']}")
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate research run outputs against acceptance checklist.")
    p.add_argument(
        "--state",
        required=True,
        help="Path to run-scoped research_state.json (or legacy research_state_*.json)",
    )
    p.add_argument(
        "--report",
        default=None,
        help="Path to run-scoped research_report.md (or legacy research_report_*.md)",
    )
    p.add_argument("--json", action="store_true", help="Print JSON result instead of human-readable report")
    p.add_argument("--strict", action="store_true", help="Return non-zero when warnings exist.")
    p.add_argument("--require-critic-pass", action="store_true", help="Treat critic pass=false as failure.")
    p.add_argument("--min-claim-support-rate", type=float, default=0.80)
    p.add_argument("--min-claim-rq-relevance", type=float, default=0.20)
    p.add_argument("--min-claim-traceability", type=float, default=0.70)
    p.add_argument("--max-web-noise-ratio", type=float, default=0.25)
    p.add_argument("--max-non-academic-ref-ratio", type=float, default=0.15)
    p.add_argument("--min-non-academic-ref-count", type=int, default=3)
    p.add_argument("--metrics-tolerance", type=float, default=0.05)
    return p.parse_args(argv)


def _build_config_from_args(args: argparse.Namespace) -> ValidationConfig:
    return ValidationConfig(
        min_claim_support_rate=float(args.min_claim_support_rate),
        min_claim_rq_relevance=float(args.min_claim_rq_relevance),
        min_claim_traceability=float(args.min_claim_traceability),
        max_web_noise_ratio=float(args.max_web_noise_ratio),
        max_non_academic_ref_ratio=float(args.max_non_academic_ref_ratio),
        min_non_academic_ref_count=int(args.min_non_academic_ref_count),
        require_critic_pass=bool(args.require_critic_pass),
        metrics_tolerance=float(args.metrics_tolerance),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    state_path = Path(args.state).resolve()
    if not state_path.exists():
        raise SystemExit(f"State file not found: {state_path}")

    report_path: Optional[Path]
    if args.report:
        report_path = Path(args.report).resolve()
    else:
        report_path = _infer_report_path_from_state_path(state_path)
    if report_path is None or not report_path.exists():
        raise SystemExit("Report file not found. Provide --report explicitly.")

    state = _read_json(state_path)
    report = _read_text(report_path)
    cfg = _build_config_from_args(args)
    result = evaluate_run_outputs(state, report, cfg=cfg)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_human_report(result, state_path, report_path))

    if result["overall"] == "fail":
        return 2
    if args.strict and result["overall"] == "warn":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
