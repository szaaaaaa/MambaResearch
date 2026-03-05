from __future__ import annotations

import argparse

from src.common.arg_utils import add_qa_model_args, add_reranker_args, add_retrieval_args
from src.common.cli_utils import add_config_arg, parse_args_and_cfg, run_cli
from src.common.rag_config import (
    collection_name,
    openai_model,
    openai_temperature,
    outputs_dir,
    persist_dir,
    retrieval_candidate_k,
    retrieval_embedding_model,
    retrieval_hybrid,
    retrieval_reranker_model,
    retrieval_top_k,
)
from src.common.runtime_utils import ensure_dir, now_tag, to_jsonable
from src.common.report_utils import write_json, write_markdown
from src.workflows.traditional_rag import answer_question


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True, help="User question")
    add_retrieval_args(ap)
    add_reranker_args(ap)
    add_config_arg(ap, __file__)
    add_qa_model_args(ap)
    args, root, cfg = parse_args_and_cfg(ap, __file__)
    print(">> demo_query start")
    print(f">> config = {args.config}")

    persist_dir_v = persist_dir(root, cfg, None)
    collection = collection_name(cfg, None)
    top_k = retrieval_top_k(cfg, args.top_k)
    candidate_k = retrieval_candidate_k(cfg, args.candidate_k)
    reranker_model = retrieval_reranker_model(cfg, args.reranker_model)
    emb_model = retrieval_embedding_model(cfg, getattr(args, "embedding_model", None))
    hybrid = retrieval_hybrid(cfg, getattr(args, "hybrid", None))
    model = openai_model(cfg, args.model)
    temperature = openai_temperature(cfg, args.temperature)
    out_dir = outputs_dir(root, cfg)
    ensure_dir(out_dir)
    print(f">> outputs_dir = {out_dir} (exists={out_dir.exists()})")

    run_id = now_tag()
    out_md = out_dir / f"demo_query_{run_id}.md"
    out_json = out_dir / f"demo_query_{run_id}.json"

    print(
        f">> retrieve: persist_dir={persist_dir_v} collection={collection} "
        f"top_k={top_k} candidate_k={candidate_k} reranker={reranker_model}"
    )
    qa = answer_question(
        persist_dir=str(persist_dir_v),
        collection_name=collection,
        question=args.query,
        top_k=top_k,
        candidate_k=candidate_k,
        reranker_model=reranker_model,
        model=model,
        temperature=float(temperature),
        embedding_model=emb_model,
        hybrid=hybrid,
    )
    hits = qa["hits"]
    cited_prompt = qa["prompt"]
    answer_text = qa["answer"]
    print(f">> retrieved hits = {len(hits)}")
    print(">> got answer")

    payload = {
        "run_id": run_id,
        "openai_model": model,
        "temperature": float(temperature),
        "persist_dir": str(persist_dir_v),
        "collection": collection,
        "top_k": int(top_k),
        "candidate_k": candidate_k,
        "reranker_model": reranker_model,
        "query": args.query,
        "answer": answer_text,
        "prompt": cited_prompt,
        "hits": to_jsonable(hits),
    }
    write_json(out_json, payload)
    write_markdown(
        out_md,
        title=f"demo_query run {run_id}",
        sections=[
            ("Query", args.query),
            ("OpenAI", f"model={model}, temperature={float(temperature)}"),
            ("Answer", answer_text),
        ],
        prompt=cited_prompt,
    )

    print(f"[OK] wrote:\n- {out_md}\n- {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli("demo_query", main))
