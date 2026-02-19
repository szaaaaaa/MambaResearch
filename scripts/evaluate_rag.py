from __future__ import annotations

import argparse
import json
import re
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from src.common.arg_utils import add_qa_model_args, add_reranker_args, add_retrieval_args
from src.common.cli_utils import add_config_arg, parse_args_and_cfg, run_cli
from src.common.rag_config import (
    collection_name,
    openai_model,
    openai_temperature,
    outputs_dir,
    persist_dir,
    retrieval_candidate_k,
    retrieval_reranker_model,
    retrieval_top_k,
)
from src.common.report_utils import write_json, write_markdown
from src.common.runtime_utils import ensure_dir, now_tag, to_jsonable


_CITATION_RE = re.compile(r"\[(\d+)\]")
_BULLET_SPLIT_RE = re.compile(r"(?:^|\n)\s*[-*]\s+", re.MULTILINE)


def _safe_mean(xs: List[float]) -> float | None:
    if not xs:
        return None
    return float(sum(xs) / len(xs))


def _dedupe_keep_order(values: List[Any]) -> List[Any]:
    out: List[Any] = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


def _normalize_doc_id(doc_id: Any) -> str:
    s = str(doc_id or "").strip().lower()
    if not s:
        return ""
    if s.startswith("arxiv_"):
        return f"arxiv:{s[len('arxiv_') :]}"
    if s.startswith("arxiv:"):
        return f"arxiv:{s[len('arxiv:') :]}"
    return s


def _load_dataset(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() == ".jsonl":
        out: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("samples"), list):
        return data["samples"]
    raise ValueError("Dataset must be .jsonl, a JSON list, or {'samples': [...]} format.")


def _gold_doc_ids(sample: Dict[str, Any]) -> List[str]:
    raw = sample.get("gold_doc_ids")
    if raw is None and sample.get("gold_doc_id") is not None:
        raw = [sample.get("gold_doc_id")]
    if raw is None:
        return []
    if isinstance(raw, str):
        return [_normalize_doc_id(raw)] if _normalize_doc_id(raw) else []
    if isinstance(raw, list):
        return _dedupe_keep_order(
            [v for v in (_normalize_doc_id(x) for x in raw if x is not None) if v]
        )
    return []


def _retrieved_doc_ids(hits: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for h in hits:
        meta = h.get("meta", {}) if isinstance(h, dict) else {}
        doc_id = meta.get("doc_id")
        if doc_id is None:
            continue
        s = _normalize_doc_id(doc_id)
        if not s:
            continue
        if s not in out:
            out.append(s)
    return out


def _extract_cited_claims(answer: str) -> List[Dict[str, Any]]:
    text = (answer or "").strip()
    if not text:
        return []

    segments = [x.strip() for x in _BULLET_SPLIT_RE.split(text) if x.strip()]
    if len(segments) <= 1:
        segments = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]

    claims: List[Dict[str, Any]] = []
    for seg in segments:
        cites = [int(x) for x in _CITATION_RE.findall(seg)]
        if not cites:
            continue
        claim_text = _CITATION_RE.sub("", seg).strip(" \t-:;,.")
        if not claim_text:
            continue
        claims.append({"claim": claim_text, "citations": cites})
    return claims


def _citation_semantic_stats(
    answer: str,
    hits: List[Dict[str, Any]],
    threshold: float = 0.35,
) -> Dict[str, Any]:
    claims = _extract_cited_claims(answer)
    if not claims:
        return {
            "citation_semantic_total": 0,
            "citation_semantic_aligned": 0,
            "citation_semantic_ratio": None,
            "citation_semantic_threshold": threshold,
            "citation_semantic_pairs": [],
        }

    from src.rag.retriever import embed_texts

    claim_texts = [str(c["claim"]) for c in claims]
    claim_vecs = embed_texts(claim_texts)
    hit_vecs = embed_texts([str((h or {}).get("text") or "") for h in hits]) if hits else np.zeros((0, 0))

    pair_rows: List[Dict[str, Any]] = []
    aligned = 0
    total = 0
    for claim_idx, claim in enumerate(claims):
        cited = claim.get("citations") or []
        for ci in cited:
            if not (1 <= ci <= len(hits)):
                continue
            total += 1
            sim = float(np.dot(claim_vecs[claim_idx], hit_vecs[ci - 1]))
            ok = sim >= threshold
            if ok:
                aligned += 1
            pair_rows.append(
                {
                    "claim": claim["claim"],
                    "citation_index": ci,
                    "similarity": sim,
                    "aligned": ok,
                }
            )

    return {
        "citation_semantic_total": total,
        "citation_semantic_aligned": aligned,
        "citation_semantic_ratio": (aligned / total) if total > 0 else None,
        "citation_semantic_threshold": threshold,
        "citation_semantic_pairs": pair_rows,
    }


def _citation_stats(answer: str, hit_count: int) -> Dict[str, Any]:
    indices = [int(x) for x in _CITATION_RE.findall(answer or "")]
    total = len(indices)
    valid = sum(1 for i in indices if 1 <= i <= hit_count)
    return {
        "citation_total": total,
        "citation_valid": valid,
        "citation_valid_ratio": (valid / total) if total > 0 else None,
        "citation_has_any": total > 0,
    }


def _answer_consistency(answers: List[str]) -> float | None:
    if len(answers) < 2:
        return None
    from src.rag.retriever import embed_texts

    vecs = embed_texts(answers)
    vals: List[float] = []
    for i, j in combinations(range(len(answers)), 2):
        vals.append(float(np.dot(vecs[i], vecs[j])))
    return _safe_mean(vals)


def _coerce_str_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if x is not None and str(x).strip()]
        return _dedupe_keep_order(out)
    return []


def _coerce_int_list(raw: Any) -> List[int]:
    if raw is None:
        return []
    if isinstance(raw, int):
        return [raw] if raw > 0 else []
    if isinstance(raw, list):
        out: List[int] = []
        for x in raw:
            try:
                v = int(x)
            except (TypeError, ValueError):
                continue
            if v > 0 and v not in out:
                out.append(v)
        return out
    return []


def _coerce_optional_int_list(raw: Any) -> List[int | None]:
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: List[int | None] = []
    for x in items:
        if x is None:
            if None not in out:
                out.append(None)
            continue
        if isinstance(x, str) and x.strip().lower() in {"none", "null", ""}:
            if None not in out:
                out.append(None)
            continue
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if v > 0 and v not in out:
            out.append(v)
    return out


def _coerce_reranker_list(raw: Any) -> List[str | None]:
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: List[str | None] = []
    for x in items:
        if x is None:
            if None not in out:
                out.append(None)
            continue
        s = str(x).strip()
        if not s or s.lower() in {"none", "null"}:
            if None not in out:
                out.append(None)
            continue
        if s not in out:
            out.append(s)
    return out


def _group_hit_rate(rows: List[Dict[str, Any]], key: str) -> Dict[str, float | None]:
    bucket: Dict[str, List[float]] = {}
    for row in rows:
        val = row.get(key)
        k = str(val)
        hit = row.get("retrieval_hit")
        if hit is None:
            continue
        bucket.setdefault(k, []).append(1.0 if bool(hit) else 0.0)
    return {k: _safe_mean(vs) for k, vs in bucket.items()}


def _s2_error_analysis(
    *,
    sample: Dict[str, Any],
    persist_dir_v: Path,
    collection: str,
    top_k: int,
    candidate_k: int | None,
    reranker_model: str | None,
) -> Dict[str, Any]:
    from src.rag.retriever import retrieve

    question = str(sample.get("question") or "").strip()
    gold_ids = _gold_doc_ids(sample)
    gold_set = set(gold_ids)

    query_variants = _coerce_str_list(sample.get("analysis_queries")) or [question]
    if question and question not in query_variants:
        query_variants = [question] + query_variants

    top_ks = _coerce_int_list(sample.get("analysis_top_ks")) or _dedupe_keep_order(
        [str(x) for x in [max(3, min(5, top_k)), top_k, max(top_k, 12)]]
    )
    top_ks = [int(x) for x in top_ks]
    if top_k not in top_ks:
        top_ks.append(top_k)
    top_ks = sorted(set(top_ks))

    ck_defaults: List[int | None] = [candidate_k, top_k, max(top_k * 3, top_k)]
    candidate_ks = _coerce_optional_int_list(sample.get("analysis_candidate_ks")) or _dedupe_keep_order(
        [str(x) if x is not None else "None" for x in ck_defaults]
    )
    candidate_ks = [None if str(x) == "None" else int(x) for x in candidate_ks]

    rr_defaults: List[str | None] = [reranker_model, None]
    rerankers = _coerce_reranker_list(sample.get("analysis_reranker_models")) or rr_defaults
    if reranker_model not in rerankers:
        rerankers = [reranker_model] + rerankers if reranker_model else rerankers
    rerankers = _dedupe_keep_order([x if x else None for x in rerankers])

    rows: List[Dict[str, Any]] = []
    for q in query_variants:
        for tk in top_ks:
            for ck in candidate_ks:
                for rr in rerankers:
                    hits = retrieve(
                        persist_dir=str(persist_dir_v),
                        collection_name=collection,
                        query=q,
                        top_k=tk,
                        candidate_k=ck,
                        reranker_model=rr,
                    )
                    doc_ids = _retrieved_doc_ids(hits)
                    hit = any(x in gold_set for x in doc_ids) if gold_set else None
                    top1 = hits[0] if hits else {}
                    top1_meta = top1.get("meta", {}) if isinstance(top1, dict) else {}
                    rows.append(
                        {
                            "query": q,
                            "top_k": tk,
                            "candidate_k": ck,
                            "reranker_model": rr,
                            "retrieved_doc_ids": doc_ids,
                            "retrieval_hit": hit,
                            "top1_doc_id": _normalize_doc_id(top1_meta.get("doc_id")),
                            "top1_distance": top1.get("distance"),
                            "top1_reranker_score": top1.get("reranker_score"),
                        }
                    )

    sorted_rows = sorted(
        rows,
        key=lambda x: (
            bool(x.get("retrieval_hit")),
            float(x.get("top1_reranker_score") or float("-inf")),
            -float(x.get("top1_distance") or 9e9),
        ),
        reverse=True,
    )
    return {
        "sample_id": sample.get("id"),
        "gold_doc_ids": gold_ids,
        "num_trials": len(rows),
        "hit_rate": _safe_mean([1.0 if bool(x.get("retrieval_hit")) else 0.0 for x in rows if x.get("retrieval_hit") is not None]),
        "by_query_hit_rate": _group_hit_rate(rows, "query"),
        "by_top_k_hit_rate": _group_hit_rate(rows, "top_k"),
        "by_candidate_k_hit_rate": _group_hit_rate(rows, "candidate_k"),
        "by_reranker_model_hit_rate": _group_hit_rate(rows, "reranker_model"),
        "best_trials": sorted_rows[:10],
        "trials": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="Path to eval set (.jsonl/.json)")
    ap.add_argument("--limit", type=int, default=None, help="Only evaluate first N samples")
    ap.add_argument("--skip_generation", action="store_true", help="Skip LLM generation and only evaluate retrieval")
    ap.add_argument("--consistency_runs", type=int, default=3, help="Number of generations for consistency")
    ap.add_argument(
        "--consistency_temperature",
        type=float,
        default=None,
        help="Temperature used for consistency runs (default: use --temperature)",
    )
    add_config_arg(ap, __file__)
    ap.add_argument("--persist_dir", default=None, help="Chroma persist dir")
    ap.add_argument("--collection", default=None, help="Chroma collection name")
    add_retrieval_args(ap)
    add_reranker_args(ap)
    add_qa_model_args(ap)
    args, root, cfg = parse_args_and_cfg(ap, __file__)

    from src.rag.cite_prompt import build_cited_prompt
    from src.rag.retriever import retrieve

    dataset_path = Path(args.dataset).resolve()
    samples = _load_dataset(dataset_path)
    if args.limit is not None and args.limit > 0:
        samples = samples[: args.limit]
    if not samples:
        raise RuntimeError("No eval samples loaded.")

    persist_dir_v = persist_dir(root, cfg, args.persist_dir)
    collection = collection_name(cfg, args.collection)
    top_k = retrieval_top_k(cfg, args.top_k)
    candidate_k = retrieval_candidate_k(cfg, args.candidate_k)
    reranker_model = retrieval_reranker_model(cfg, args.reranker_model)
    model = openai_model(cfg, args.model)
    temperature = openai_temperature(cfg, args.temperature)
    consistency_temperature = (
        float(args.consistency_temperature)
        if args.consistency_temperature is not None
        else float(temperature)
    )

    out_dir = outputs_dir(root, cfg)
    ensure_dir(out_dir)
    run_id = now_tag()
    out_json = out_dir / f"eval_rag_{run_id}.json"
    out_md = out_dir / f"eval_rag_{run_id}.md"

    print(">> evaluate_rag start")
    print(f">> dataset = {dataset_path}")
    print(f">> samples = {len(samples)}")
    print(
        f">> retrieval = top_k={top_k}, candidate_k={candidate_k}, reranker={reranker_model}, "
        f"persist_dir={persist_dir_v}, collection={collection}"
    )
    print(
        f">> generation = skip={args.skip_generation}, model={model}, temp={temperature}, "
        f"consistency_runs={args.consistency_runs}, consistency_temp={consistency_temperature}"
    )

    rows: List[Dict[str, Any]] = []
    retrieval_hits: List[float] = []
    citation_presence_vals: List[float] = []
    citation_valid_ratio_vals: List[float] = []
    citation_semantic_ratio_vals: List[float] = []
    consistency_vals: List[float] = []
    s2_row: Dict[str, Any] | None = None

    for idx, sample in enumerate(samples, start=1):
        question = str(sample.get("question") or "").strip()
        if not question:
            raise ValueError(f"sample[{idx}] missing question")

        sid = sample.get("id", f"sample_{idx:04d}")
        if sid == "s2":
            s2_row = sample
        hits = retrieve(
            persist_dir=str(persist_dir_v),
            collection_name=collection,
            query=question,
            top_k=top_k,
            candidate_k=candidate_k,
            reranker_model=reranker_model,
        )
        doc_ids = _retrieved_doc_ids(hits)
        gold_ids = _gold_doc_ids(sample)
        retrieval_hit = None
        if gold_ids:
            gold_set = set(gold_ids)
            retrieval_hit = any(x in gold_set for x in doc_ids)
            retrieval_hits.append(1.0 if retrieval_hit else 0.0)

        answer = None
        prompt = None
        cstats = {
            "citation_total": None,
            "citation_valid": None,
            "citation_valid_ratio": None,
            "citation_has_any": None,
            "citation_semantic_total": None,
            "citation_semantic_aligned": None,
            "citation_semantic_ratio": None,
            "citation_semantic_threshold": None,
            "citation_semantic_pairs": None,
        }
        consistency = None
        consistency_answers: List[str] = []

        if not args.skip_generation:
            from src.rag.answerer import answer_with_openai_chat

            prompt = build_cited_prompt(question=question, hits=hits)
            answer = answer_with_openai_chat(prompt=prompt, model=model, temperature=temperature)
            cstats = _citation_stats(answer, len(hits))
            cstats.update(_citation_semantic_stats(answer, hits))
            citation_presence_vals.append(1.0 if cstats["citation_has_any"] else 0.0)
            if cstats["citation_valid_ratio"] is not None:
                citation_valid_ratio_vals.append(float(cstats["citation_valid_ratio"]))
            if cstats["citation_semantic_ratio"] is not None:
                citation_semantic_ratio_vals.append(float(cstats["citation_semantic_ratio"]))

            if args.consistency_runs > 1:
                for _ in range(args.consistency_runs):
                    consistency_answers.append(
                        answer_with_openai_chat(
                            prompt=prompt,
                            model=model,
                            temperature=consistency_temperature,
                        )
                    )
                consistency = _answer_consistency(consistency_answers)
                if consistency is not None:
                    consistency_vals.append(float(consistency))

        rows.append(
            {
                "id": sid,
                "question": question,
                "gold_doc_ids": gold_ids,
                "retrieved_doc_ids": doc_ids,
                "retrieval_hit": retrieval_hit,
                "hit_count": len(hits),
                "hits": to_jsonable(hits),
                "answer": answer,
                "prompt": prompt,
                "citation_total": cstats["citation_total"],
                "citation_valid": cstats["citation_valid"],
                "citation_valid_ratio": cstats["citation_valid_ratio"],
                "citation_has_any": cstats["citation_has_any"],
                "citation_semantic_total": cstats["citation_semantic_total"],
                "citation_semantic_aligned": cstats["citation_semantic_aligned"],
                "citation_semantic_ratio": cstats["citation_semantic_ratio"],
                "citation_semantic_threshold": cstats["citation_semantic_threshold"],
                "citation_semantic_pairs": cstats["citation_semantic_pairs"],
                "consistency_mean_cosine": consistency,
                "consistency_answers": consistency_answers if consistency_answers else None,
            }
        )
        print(
            f">> [{idx}/{len(samples)}] {sid} retrieval_hit={retrieval_hit} "
            f"citations={cstats['citation_total']} semantic_ratio={cstats['citation_semantic_ratio']}"
        )

    s2_analysis = None
    if s2_row is not None:
        print(">> running focused error analysis for sample id=s2")
        s2_analysis = _s2_error_analysis(
            sample=s2_row,
            persist_dir_v=persist_dir_v,
            collection=collection,
            top_k=top_k,
            candidate_k=candidate_k,
            reranker_model=reranker_model,
        )
        print(
            f">> s2 analysis trials={s2_analysis['num_trials']} "
            f"hit_rate={s2_analysis['hit_rate']}"
        )

    summary = {
        "num_samples": len(rows),
        "num_with_gold": len(retrieval_hits),
        "retrieval_hit_rate": _safe_mean(retrieval_hits),
        "citation_presence_rate": _safe_mean(citation_presence_vals),
        "citation_valid_ratio_mean": _safe_mean(citation_valid_ratio_vals),
        "citation_semantic_ratio_mean": _safe_mean(citation_semantic_ratio_vals),
        "answer_consistency_mean": _safe_mean(consistency_vals),
    }

    payload = {
        "run_id": run_id,
        "dataset": str(dataset_path),
        "settings": {
            "persist_dir": str(persist_dir_v),
            "collection": collection,
            "top_k": top_k,
            "candidate_k": candidate_k,
            "reranker_model": reranker_model,
            "skip_generation": args.skip_generation,
            "model": model,
            "temperature": temperature,
            "consistency_runs": args.consistency_runs,
            "consistency_temperature": consistency_temperature,
        },
        "summary": summary,
        "s2_error_analysis": s2_analysis,
        "samples": rows,
    }

    write_json(out_json, payload)
    write_markdown(
        out_md,
        title=f"evaluate_rag {run_id}",
        sections=[
            ("Dataset", str(dataset_path)),
            (
                "Settings",
                f"top_k={top_k}, candidate_k={candidate_k}, reranker={reranker_model}, "
                f"skip_generation={args.skip_generation}, model={model}, temperature={temperature}, "
                f"consistency_runs={args.consistency_runs}, consistency_temp={consistency_temperature}",
            ),
            (
                "Summary",
                f"num_samples={summary['num_samples']}, num_with_gold={summary['num_with_gold']}, "
                f"retrieval_hit_rate={summary['retrieval_hit_rate']}, "
                f"citation_presence_rate={summary['citation_presence_rate']}, "
                f"citation_valid_ratio_mean={summary['citation_valid_ratio_mean']}, "
                f"citation_semantic_ratio_mean={summary['citation_semantic_ratio_mean']}, "
                f"answer_consistency_mean={summary['answer_consistency_mean']}",
            ),
            (
                "S2 Error Analysis",
                (
                    "not available"
                    if s2_analysis is None
                    else (
                        f"trials={s2_analysis['num_trials']}, hit_rate={s2_analysis['hit_rate']}, "
                        f"by_query={s2_analysis['by_query_hit_rate']}, "
                        f"by_top_k={s2_analysis['by_top_k_hit_rate']}, "
                        f"by_candidate_k={s2_analysis['by_candidate_k_hit_rate']}, "
                        f"by_reranker_model={s2_analysis['by_reranker_model_hit_rate']}"
                    )
                ),
            ),
        ],
    )

    print(f"[OK] wrote:\n- {out_md}\n- {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli("evaluate_rag", main))
