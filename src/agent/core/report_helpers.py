"""Report generation helpers: critic, rendering, validation, and acceptance metrics."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from src.agent.core.config import DEFAULT_CORE_MIN_A_RATIO
from src.agent.core.reference_utils import (
    extract_reference_urls as _shared_extract_reference_urls,
)
from src.agent.core.source_ranking import (
    _STOPWORDS,
    _normalize_source_url,
    _tokenize,
    _uid_to_resolvable_url,
)


# ── Reference extraction ────────────────────────────────────────────


def _extract_reference_urls(report: str) -> List[str]:
    """S2: Delegate to shared implementation for critic/validator consistency."""
    return _shared_extract_reference_urls(report)


# ── Experiment validation ────────────────────────────────────────────


def _validate_experiment_plan(plan: Dict[str, Any]) -> List[str]:
    """Validate experiment plan completeness and return issue codes."""
    issues: List[str] = []
    rq_experiments = plan.get("rq_experiments", [])
    if not isinstance(rq_experiments, list) or not rq_experiments:
        issues.append("no_rq_experiments")
        return issues

    for i, exp in enumerate(rq_experiments):
        prefix = f"rq_experiments[{i}]"

        datasets = exp.get("datasets", []) if isinstance(exp, dict) else []
        if not isinstance(datasets, list) or not datasets:
            issues.append(f"{prefix}.datasets: missing")
        else:
            for j, ds in enumerate(datasets):
                ds_item = ds if isinstance(ds, dict) else {}
                if not ds_item.get("url"):
                    issues.append(f"{prefix}.datasets[{j}].url: missing")
                if not ds_item.get("name"):
                    issues.append(f"{prefix}.datasets[{j}].name: missing")

        env = exp.get("environment", {}) if isinstance(exp, dict) else {}
        if not isinstance(env, dict):
            env = {}
        if not env.get("python"):
            issues.append(f"{prefix}.environment.python: missing")
        if not env.get("cuda"):
            issues.append(f"{prefix}.environment.cuda: missing")
        if not env.get("pytorch"):
            issues.append(f"{prefix}.environment.pytorch: missing")

        hp = exp.get("hyperparameters", {}) if isinstance(exp, dict) else {}
        if not isinstance(hp, dict):
            hp = {}
        if not hp.get("baseline"):
            issues.append(f"{prefix}.hyperparameters.baseline: missing")
        if not hp.get("search_space"):
            issues.append(f"{prefix}.hyperparameters.search_space: missing")

        cmds = exp.get("run_commands", {}) if isinstance(exp, dict) else {}
        if not isinstance(cmds, dict):
            cmds = {}
        if not cmds.get("train"):
            issues.append(f"{prefix}.run_commands.train: missing")
        if not cmds.get("eval"):
            issues.append(f"{prefix}.run_commands.eval: missing")

        refs = exp.get("evidence_refs", []) if isinstance(exp, dict) else []
        if not isinstance(refs, list) or not refs:
            issues.append(f"{prefix}.evidence_refs: missing")
        if not str(exp.get("split_strategy") or "").strip():
            issues.append(f"{prefix}.split_strategy: missing")
        if not str(exp.get("validation_strategy") or "").strip():
            issues.append(f"{prefix}.validation_strategy: missing")
        if not str(exp.get("ablation_plan") or "").strip():
            issues.append(f"{prefix}.ablation_plan: missing")
        if not str(exp.get("dataset_generalization_plan") or "").strip():
            issues.append(f"{prefix}.dataset_generalization_plan: missing")

    return issues


def _validate_experiment_results(
    results: Dict[str, Any],
    research_questions: List[str],
) -> List[str]:
    """Validate experiment result completeness and coverage."""
    issues: List[str] = []
    runs = results.get("runs", [])
    if not isinstance(runs, list) or not runs:
        issues.append("no_runs")
        return issues

    rq_set = {str(rq).strip() for rq in research_questions if str(rq).strip()}
    covered = {
        str(run.get("research_question", "")).strip()
        for run in runs
        if isinstance(run, dict)
    }
    if rq_set and not rq_set.issubset(covered):
        issues.append("rq_coverage_incomplete")

    for i, run in enumerate(runs):
        run_item = run if isinstance(run, dict) else {}
        if not run_item.get("run_id"):
            issues.append(f"runs[{i}].run_id: missing")
        metrics = run_item.get("metrics", [])
        if not isinstance(metrics, list) or not metrics:
            issues.append(f"runs[{i}].metrics: missing")

    return issues


# ── Report critic ────────────────────────────────────────────────────


def _critic_report(
    *,
    topic: str,
    report: str,
    research_questions: List[str],
    claim_map: List[Dict[str, Any]],
    max_refs: int,
    max_sections: int,
    block_terms: List[str],
    experiment_plan: Dict[str, Any] | None = None,
    experiment_results: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    issues: List[str] = []
    soft_issues: List[str] = []
    refs = _extract_reference_urls(report)
    if not refs:
        issues.append("missing_references")
    if len(refs) > max_refs:
        issues.append("reference_budget_exceeded")

    core_sections = []
    for ln in report.splitlines():
        s = ln.strip()
        if s.startswith("## "):
            name = s[3:].strip().lower()
            if "references" in name or "abstract" in name:
                continue
            core_sections.append(name)
    if len(core_sections) > max_sections:
        issues.append("section_budget_exceeded")

    topic_tokens = {t for t in _tokenize(topic) if t not in _STOPWORDS}
    report_tokens = set(_tokenize(report))
    if topic_tokens and len(topic_tokens & report_tokens) / max(1, len(topic_tokens)) < 0.5:
        issues.append("topic_misalignment")

    if research_questions:
        covered = 0
        for rq in research_questions:
            rq_tokens = [t for t in _tokenize(rq) if t not in _STOPWORDS]
            if not rq_tokens:
                continue
            if any(t in report_tokens for t in rq_tokens):
                covered += 1
        if covered < max(1, int(len(research_questions) * DEFAULT_CORE_MIN_A_RATIO)):
            issues.append("research_question_coverage_low")

    # Check claim-evidence appearance in final text.
    report_l = report.lower()
    missing_claim_evidence = 0
    for c in claim_map:
        claim = str(c.get("claim") or "").strip().lower()
        ev = c.get("evidence", [])
        has_ev = any((str(e.get("url") or "").lower() in report_l) or (str(e.get("title") or "").lower()[:40] in report_l) for e in ev)
        if claim and claim[:40] not in report_l:
            missing_claim_evidence += 1
        if not has_ev:
            missing_claim_evidence += 1
    if missing_claim_evidence > max(1, len(claim_map) // 2):
        issues.append("claim_evidence_mapping_weak")

    lowered = report.lower()
    off_topic_hits = [bt for bt in block_terms if bt and bt.lower() in lowered]
    if off_topic_hits:
        issues.append(f"off_topic_terms:{', '.join(off_topic_hits[:5])}")

    # Validate experiment plan quality (if present).
    if experiment_plan and isinstance(experiment_plan, dict) and experiment_plan.get("rq_experiments"):
        exp_issues = _validate_experiment_plan(experiment_plan)
        for issue in exp_issues:
            issues.append(f"experiment_plan:{issue}")

    # Validate experiment results quality (if present and marked validated).
    if (
        experiment_results
        and isinstance(experiment_results, dict)
        and str(experiment_results.get("status", "")).lower() == "validated"
    ):
        result_issues = _validate_experiment_results(experiment_results, research_questions)
        for issue in result_issues:
            issues.append(f"experiment_results:{issue}")

    # Soft gate: ML experiment plan exists but no validated results yet.
    if (
        experiment_plan
        and isinstance(experiment_plan, dict)
        and experiment_plan.get("rq_experiments")
        and not (
            experiment_results
            and isinstance(experiment_results, dict)
            and str(experiment_results.get("status", "")).lower() == "validated"
        )
    ):
        soft_issues.append("experiment_results_missing")

    return {
        "pass": len(issues) == 0,
        "issues": issues + soft_issues,
        "soft_issues": soft_issues,
    }


# ── Report text manipulation ────────────────────────────────────────


def _clean_reference_section(report: str, max_refs: int) -> str:
    lines = report.splitlines()
    ref_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s*(?:\d+\.?\s*)?(References|参考文献)\s*$", line.strip(), flags=re.IGNORECASE):
            ref_idx = i
            break
    if ref_idx is None:
        return report

    head = lines[: ref_idx + 1]
    tail = lines[ref_idx + 1 :]

    dedup_refs: List[str] = []
    seen: set[str] = set()
    for line in tail:
        s = line.strip()
        if not s:
            continue
        if re.match(r"^\s{0,3}#{1,6}\s+", s):
            # Stop at next heading.
            break
        if not re.match(r"^(-|\d+\.)\s+", s):
            continue

        m_md = re.search(r"\((https?://[^\s)]+)\)", s)
        m_raw = re.search(r"(https?://\S+)", s)
        url = m_md.group(1) if m_md else (m_raw.group(1) if m_raw else "")
        key = _normalize_source_url(url) if url else re.sub(r"\s+", " ", s.lower())
        if key in seen:
            continue
        seen.add(key)
        dedup_refs.append(re.sub(r"^(-|\d+\.)\s+", "", s).strip())
        if len(dedup_refs) >= max(1, int(max_refs)):
            break

    if not dedup_refs:
        return report
    renumbered = [f"{i}. {item}" for i, item in enumerate(dedup_refs, 1)]
    return "\n".join(head + [""] + renumbered) + "\n"


def _strip_outer_markdown_fence(report: str) -> str:
    """Remove a top-level ```markdown wrapper while preserving inner code blocks."""
    lines = report.splitlines()
    first_idx = -1
    for i, line in enumerate(lines):
        if line.strip():
            first_idx = i
            break
    if first_idx < 0:
        return report

    first = lines[first_idx].strip()
    if not first.startswith("```"):
        return report

    close_idx = -1
    for i in range(first_idx + 1, len(lines)):
        if lines[i].strip() == "```":
            close_idx = i
            break
    if close_idx < 0:
        return report

    inner = lines[:first_idx] + lines[first_idx + 1 : close_idx] + lines[close_idx + 1 :]
    cleaned = "\n".join(inner).strip()
    return cleaned + "\n" if cleaned else ""


def _insert_chapter_before_references(report: str, chapter_md: str) -> str:
    """Insert markdown chapter before References heading if present, else append."""
    content = (chapter_md or "").strip()
    if not content:
        return report
    ref_match = re.search(
        r"^(#{1,6}\s*(?:\d+\.?\s*)?(?:References|Bibliography|参考文献)\s*$)",
        report,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    if ref_match:
        insert_pos = ref_match.start()
        return (
            report[:insert_pos].rstrip()
            + "\n\n"
            + content
            + "\n\n"
            + report[insert_pos:]
        )
    return report.rstrip() + "\n\n" + content + "\n"


# ── Claim-evidence mapping in report ─────────────────────────────────


def _claim_mapping_section_exists(report: str) -> bool:
    return bool(
        re.search(
            r"^\s{0,3}#{1,6}\s*(?:Claim[- ]?Evidence(?:\s+Map(?:ping)?)?|Claim-Evidence Mapping)\s*$",
            report,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    )


def _claim_evidence_coverage_ratio(report: str, claim_map: List[Dict[str, Any]]) -> float:
    if not claim_map:
        return 1.0
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


def _render_claim_evidence_mapping(claim_map: List[Dict[str, Any]], *, language: str = "en") -> str:
    if not claim_map:
        return ""
    is_zh = str(language).lower() == "zh"
    header = "### Claim-Evidence Mapping" if not is_zh else "### 论点-证据映射"
    claim_label = "Claim" if not is_zh else "论点"
    rq_label = "RQ" if not is_zh else "研究问题"
    caveat_label = "Caveat" if not is_zh else "注意点"
    ev_label = "Evidence" if not is_zh else "证据"

    parts: List[str] = [header, ""]
    for i, item in enumerate(claim_map, 1):
        claim = str(item.get("claim") or "").strip()
        rq = str(item.get("research_question") or "").strip()
        strength = str(item.get("strength") or "C").strip().upper() or "C"
        caveat = str(item.get("caveat") or "").strip()
        parts.append(f"{i}. **{claim_label}** ({strength}): {claim}")
        if rq:
            parts.append(f"   - **{rq_label}**: {rq}")
        evidence = item.get("evidence", []) if isinstance(item.get("evidence"), list) else []
        for ev in evidence[:2]:
            title = str(ev.get("title") or ev.get("uid") or "Unknown").strip()
            url = str(ev.get("url") or "").strip() or _uid_to_resolvable_url(str(ev.get("uid") or ""))
            tier = str(ev.get("tier") or "C").strip().upper() or "C"
            if url:
                parts.append(f"   - **{ev_label} [{tier}]**: [{title}]({url})")
            else:
                parts.append(f"   - **{ev_label} [{tier}]**: {title}")
        if caveat:
            parts.append(f"   - **{caveat_label}**: {caveat}")
        parts.append("")
    return "\n".join(parts).strip()


def _ensure_claim_evidence_mapping_in_report(
    report: str,
    claim_map: List[Dict[str, Any]],
    *,
    language: str = "en",
    min_coverage: float = 1.0,
) -> str:
    if not claim_map:
        return report
    coverage = _claim_evidence_coverage_ratio(report, claim_map)
    if coverage >= float(min_coverage):
        return report
    if _claim_mapping_section_exists(report):
        return report
    mapping_md = _render_claim_evidence_mapping(claim_map, language=language)
    if not mapping_md:
        return report
    return _insert_chapter_before_references(report, mapping_md)


# ── Experiment rendering ─────────────────────────────────────────────


def _render_experiment_blueprint(plan: Dict[str, Any], language: str = "en") -> str:
    """Render experiment plan as a markdown chapter."""
    rq_experiments = plan.get("rq_experiments", []) if isinstance(plan, dict) else []
    if not isinstance(rq_experiments, list) or not rq_experiments:
        return ""

    is_zh = str(language).lower() == "zh"
    header = "## Experimental Blueprint" if not is_zh else "## 实验蓝图"
    domain_label = "Domain" if not is_zh else "领域"
    subfield_label = "Subfield" if not is_zh else "子领域"
    task_label = "Task Type" if not is_zh else "任务类型"
    planned_label = (
        "_Status: planned protocol (not yet executed)._"
        if not is_zh
        else "_状态：实验计划，尚未执行。_"
    )

    parts: List[str] = [
        header,
        "",
        f"**{domain_label}**: {plan.get('domain', 'N/A')} | "
        f"**{subfield_label}**: {plan.get('subfield', 'N/A')} | "
        f"**{task_label}**: {plan.get('task_type', 'N/A')}",
        "",
        planned_label,
        "",
    ]

    for i, exp in enumerate(rq_experiments, 1):
        exp_item = exp if isinstance(exp, dict) else {}
        rq = exp_item.get("research_question", f"RQ {i}")
        parts.append(f"### Experiment {i}: {rq}")
        parts.append("")
        parts.append(f"**Task**: {exp_item.get('task', 'N/A')}")

        datasets = exp_item.get("datasets", [])
        if isinstance(datasets, list) and datasets:
            parts.append("")
            parts.append("#### Datasets")
            for ds in datasets:
                ds_item = ds if isinstance(ds, dict) else {}
                name = ds_item.get("name", "N/A")
                url = ds_item.get("url", "N/A")
                lic = ds_item.get("license", "N/A")
                reason = ds_item.get("reason", "N/A")
                parts.append(f"- {name} ({url}), license: {lic}; reason: {reason}")

        cmds = exp_item.get("run_commands", {})
        if isinstance(cmds, dict) and (cmds.get("train") or cmds.get("eval")):
            parts.append("")
            parts.append("#### Run Commands")
            if cmds.get("train"):
                parts.append("```bash")
                parts.append(str(cmds.get("train")))
                parts.append("```")
            if cmds.get("eval"):
                parts.append("```bash")
                parts.append(str(cmds.get("eval")))
                parts.append("```")

        ev = exp_item.get("evaluation", {})
        if isinstance(ev, dict) and (ev.get("metrics") or ev.get("protocol")):
            parts.append("")
            parts.append("#### Evaluation")
            metrics = ev.get("metrics", [])
            if isinstance(metrics, list) and metrics:
                parts.append(f"- Metrics: {', '.join(str(x) for x in metrics)}")
            if ev.get("protocol"):
                parts.append(f"- Protocol: {ev.get('protocol')}")

        strategy_fields = [
            ("Split Strategy", exp_item.get("split_strategy")),
            ("Validation Strategy", exp_item.get("validation_strategy")),
            ("Ablation Plan", exp_item.get("ablation_plan")),
            ("Dataset Generalization Plan", exp_item.get("dataset_generalization_plan")),
        ]
        populated_strategy_fields = [(label, value) for label, value in strategy_fields if str(value or "").strip()]
        if populated_strategy_fields:
            parts.append("")
            parts.append("#### Experimental Rigor")
            for label, value in populated_strategy_fields:
                parts.append(f"- {label}: {value}")

        refs = exp_item.get("evidence_refs", [])
        if isinstance(refs, list) and refs:
            parts.append("")
            parts.append("#### Evidence References")
            for ref in refs:
                ref_item = ref if isinstance(ref, dict) else {}
                uid = ref_item.get("uid", "")
                url = ref_item.get("url", "")
                if url:
                    parts.append(f"- [{uid}]({url})")
                elif uid:
                    parts.append(f"- {uid}")
        parts.append("")

    return "\n".join(parts).strip()


def _render_experiment_results(results: Dict[str, Any], language: str = "en") -> str:
    """Render validated experiment results as a markdown chapter."""
    if not isinstance(results, dict):
        return ""
    if str(results.get("status", "")).lower() != "validated":
        return ""
    runs = results.get("runs", [])
    if not isinstance(runs, list) or not runs:
        return ""

    is_zh = str(language).lower() == "zh"
    header = "## Experimental Results" if not is_zh else "## 实验结果"
    submitted_by_label = "Submitted By" if not is_zh else "提交人"
    submitted_at_label = "Submitted At" if not is_zh else "提交时间"

    parts: List[str] = [header, ""]
    if results.get("submitted_by") or results.get("submitted_at"):
        parts.append(
            f"**{submitted_by_label}**: {results.get('submitted_by', 'N/A')} | "
            f"**{submitted_at_label}**: {results.get('submitted_at', 'N/A')}"
        )
        parts.append("")

    summaries = results.get("summaries", [])
    if isinstance(summaries, list) and summaries:
        parts.append("### Result Summaries")
        parts.append("")
        for s in summaries:
            s_item = s if isinstance(s, dict) else {}
            rq = s_item.get("research_question", "N/A")
            best = s_item.get("best_run_id", "N/A")
            conc = s_item.get("conclusion", "N/A")
            conf = s_item.get("confidence", "N/A")
            parts.append(f"- **{rq}**: best_run={best}; confidence={conf}; conclusion={conc}")
        parts.append("")

    parts.append("### Runs")
    parts.append("")
    for i, run in enumerate(runs, 1):
        run_item = run if isinstance(run, dict) else {}
        parts.append(
            f"- Run {i}: id={run_item.get('run_id', 'N/A')}, "
            f"rq={run_item.get('research_question', 'N/A')}, "
            f"name={run_item.get('experiment_name', 'N/A')}"
        )
        metrics = run_item.get("metrics", [])
        if isinstance(metrics, list) and metrics:
            metric_parts = []
            for m in metrics:
                m_item = m if isinstance(m, dict) else {}
                metric_parts.append(f"{m_item.get('name', 'metric')}={m_item.get('value', 'N/A')}")
            parts.append(f"  - metrics: {', '.join(metric_parts)}")
        if run_item.get("notes"):
            parts.append(f"  - notes: {run_item.get('notes')}")
    parts.append("")
    return "\n".join(parts).strip()


# ── Acceptance metrics ───────────────────────────────────────────────


def _compute_acceptance_metrics(
    *,
    evidence_audit_log: List[Dict[str, Any]],
    report_critic: Dict[str, Any],
    experiment_plan: Dict[str, Any] | None = None,
    experiment_results: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Compute quantitative acceptance metrics from audit data.

    Metrics
    -------
    avg_a_evidence_ratio        : mean A-tier evidence ratio across all RQs (target >= 0.70)
    a_ratio_pass                : True if avg_a_evidence_ratio >= 0.70
    rq_min2_evidence_rate       : fraction of RQs with >= 2 evidence items (target >= 0.90)
    rq_coverage_pass            : True if rq_min2_evidence_rate >= 0.90
    rq_min3_high_quality_rate   : fraction of RQs with >= 3 high-quality evidences (target >= 0.90)
    rq_min2_peer_review_rate    : fraction of RQs with >= 2 peer-reviewed evidences (target >= 0.90)
    reference_budget_compliant  : True if critic did not flag reference_budget_exceeded
    run_view_isolation_active   : always True when run_id is in use (marker for cross-contamination tracking)
    """
    if not evidence_audit_log:
        result = {
            "avg_a_evidence_ratio": 0.0,
            "a_ratio_pass": False,
            "rq_min2_evidence_rate": 0.0,
            "rq_coverage_pass": False,
            "rq_min3_high_quality_rate": 0.0,
            "rq_min2_peer_review_rate": 0.0,
            "reference_budget_compliant": "reference_budget_exceeded" not in report_critic.get("issues", []),
            "run_view_isolation_active": True,
            "note": "no evidence_audit_log available",
        }
    else:
        a_ratios = [float(x.get("a_ratio", 0.0)) for x in evidence_audit_log]
        avg_a_ratio = sum(a_ratios) / len(a_ratios)

        rqs_with_2plus = sum(1 for x in evidence_audit_log if int(x.get("evidence_count", 0)) >= 2)
        rq_coverage_rate = rqs_with_2plus / len(evidence_audit_log)
        rqs_with_3_hq = sum(1 for x in evidence_audit_log if int(x.get("high_quality_count", 0)) >= 3)
        rqs_with_2_peer = sum(1 for x in evidence_audit_log if int(x.get("peer_reviewed_count", 0)) >= 2)

        ref_compliant = "reference_budget_exceeded" not in report_critic.get("issues", [])

        result = {
            "avg_a_evidence_ratio": round(avg_a_ratio, 3),
            "a_ratio_pass": avg_a_ratio >= DEFAULT_CORE_MIN_A_RATIO,
            "rq_min2_evidence_rate": round(rq_coverage_rate, 3),
            "rq_coverage_pass": rq_coverage_rate >= 0.90,
            "rq_min3_high_quality_rate": round(rqs_with_3_hq / len(evidence_audit_log), 3),
            "rq_min2_peer_review_rate": round(rqs_with_2_peer / len(evidence_audit_log), 3),
            "reference_budget_compliant": ref_compliant,
            "run_view_isolation_active": True,
            "critic_issues": report_critic.get("issues", []),
        }

    # Experiment plan metrics
    exp_plan = experiment_plan or {}
    exp_rqs = exp_plan.get("rq_experiments", []) if isinstance(exp_plan, dict) else []
    if not isinstance(exp_rqs, list):
        exp_rqs = []
    exp_plan_issues = _validate_experiment_plan(exp_plan) if exp_rqs else []
    result["experiment_plan_present"] = bool(exp_rqs)
    result["experiment_plan_rq_count"] = len(exp_rqs)
    result["experiment_plan_issues"] = exp_plan_issues
    result["experiment_plan_valid"] = bool(exp_rqs) and len(exp_plan_issues) == 0

    # Experiment results metrics
    exp_results = experiment_results or {}
    exp_status = str(exp_results.get("status", "")).lower() if isinstance(exp_results, dict) else ""
    exp_runs = exp_results.get("runs", []) if isinstance(exp_results, dict) else []
    if not isinstance(exp_runs, list):
        exp_runs = []
    result["experiment_results_present"] = bool(exp_runs)
    result["experiment_results_validated"] = exp_status == "validated"
    result["experiment_results_issues"] = (
        _validate_experiment_results(exp_results, [])
        if (isinstance(exp_results, dict) and exp_status == "validated")
        else list(exp_results.get("validation_issues", []))
        if isinstance(exp_results, dict) and isinstance(exp_results.get("validation_issues", []), list)
        else []
    )

    return result
