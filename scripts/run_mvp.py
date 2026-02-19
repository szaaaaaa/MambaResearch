from __future__ import annotations

import argparse
from pathlib import Path

from src.common.arg_utils import (
    add_fetch_control_args,
    add_fetch_storage_args,
    add_index_build_args,
    add_index_store_args,
    add_qa_model_args,
    add_reranker_args,
    add_retrieval_args,
)
from src.common.cli_utils import add_config_arg, parse_args_and_cfg, run_cli
from src.common.rag_config import (
    collection_name,
    fetch_delay,
    fetch_download,
    fetch_max_results,
    openai_model,
    openai_temperature,
    outputs_dir,
    papers_dir,
    persist_dir,
    retrieval_candidate_k,
    retrieval_reranker_model,
    retrieval_top_k,
    sqlite_path,
)
from src.common.runtime_utils import ensure_dir, now_tag, to_jsonable
from src.common.report_utils import write_json, write_markdown
from src.workflows.traditional_rag import (
    answer_question,
    fetch_arxiv_records,
    index_pdfs,
    list_pdfs,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch_query", required=True, help="arXiv query for fetching papers")
    ap.add_argument("--question", required=True, help="RAG question for final answer")
    add_config_arg(ap, __file__)
    add_fetch_control_args(ap)
    add_fetch_storage_args(ap)
    add_index_store_args(ap)
    ap.add_argument("--index_from", choices=["all", "fetched"], default="all", help="Index all local PDFs or only fetched PDFs")
    add_index_build_args(ap)
    add_retrieval_args(ap)
    add_reranker_args(ap)
    add_qa_model_args(ap)
    args, root, cfg = parse_args_and_cfg(ap, __file__)

    papers_dir_v = papers_dir(root, cfg, args.papers_dir)
    sqlite_path_v = sqlite_path(root, cfg, args.sqlite_path)
    persist_dir_v = persist_dir(root, cfg, args.persist_dir)
    outputs_dir_v = outputs_dir(root, cfg)
    collection = collection_name(cfg, args.collection)
    max_results = fetch_max_results(cfg, args.max_results)
    polite_delay_sec = fetch_delay(cfg, args.polite_delay_sec)
    download = fetch_download(cfg, args.download)
    top_k = retrieval_top_k(cfg, args.top_k)
    candidate_k = retrieval_candidate_k(cfg, args.candidate_k)
    reranker_model = retrieval_reranker_model(cfg, args.reranker_model)
    model = openai_model(cfg, args.model)
    temperature = openai_temperature(cfg, args.temperature)

    ensure_dir(papers_dir_v)
    ensure_dir(persist_dir_v)
    ensure_dir(outputs_dir_v)
    ensure_dir(sqlite_path_v.parent)

    run_id = now_tag()
    out_json = outputs_dir_v / f"run_mvp_{run_id}.json"
    out_md = outputs_dir_v / f"run_mvp_{run_id}.md"

    print(">> run_mvp start")
    print(f">> fetch_query = {args.fetch_query}")
    print(f">> question = {args.question}")
    print(f">> papers_dir = {papers_dir_v}")
    print(f">> sqlite_path = {sqlite_path_v}")
    print(f">> persist_dir = {persist_dir_v}")
    print(f">> collection = {collection}")
    print(f">> retrieval = top_k={top_k}, candidate_k={candidate_k}, reranker={reranker_model}")

    print(">> step1 fetch_arxiv")
    records = fetch_arxiv_records(
        query=args.fetch_query,
        sqlite_path=str(sqlite_path_v),
        papers_dir=str(papers_dir_v),
        max_results=max_results,
        download=download,
        polite_delay_sec=polite_delay_sec,
    )
    print(f">> fetched records = {len(records)}")

    print(">> step2 build_index")
    if args.index_from == "fetched":
        pdfs = [
            Path(r.pdf_path).resolve()
            for r in records
            if getattr(r, "pdf_path", None) and Path(r.pdf_path).exists()
        ]
        if not pdfs:
            raise RuntimeError("No downloaded PDF in fetched records. Use --download or switch to --index_from all.")
    else:
        pdfs = list_pdfs(papers_dir=papers_dir_v, pdf_path=None)

    index_result = index_pdfs(
        persist_dir=str(persist_dir_v),
        collection_name=collection,
        pdfs=pdfs,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        max_pages=args.max_pages,
        keep_old=args.keep_old,
        single_doc_id=None,
    )
    for row in index_result["rows"]:
        print(
            f">> indexed {Path(row['pdf_path']).name}: "
            f"doc_id={row['doc_id']} pages={row['num_pages']} chunks={row['chunks']}"
        )
    print(f">> indexed docs={index_result['total_docs']} chunks={index_result['total_chunks']}")

    print(">> step3 retrieve + answer")
    qa = answer_question(
        persist_dir=str(persist_dir_v),
        collection_name=collection,
        question=args.question,
        top_k=top_k,
        candidate_k=candidate_k,
        reranker_model=reranker_model,
        model=model,
        temperature=temperature,
    )
    hits = qa["hits"]
    prompt = qa["prompt"]
    answer = qa["answer"]
    print(f">> retrieved hits = {len(hits)}")

    payload = {
        "run_id": run_id,
        "fetch_query": args.fetch_query,
        "question": args.question,
        "max_results": max_results,
        "download": download,
        "polite_delay_sec": polite_delay_sec,
        "index_from": args.index_from,
        "indexed_doc_count": index_result["total_docs"],
        "indexed_chunk_count": index_result["total_chunks"],
        "indexed_docs": index_result["indexed_docs"],
        "persist_dir": str(persist_dir_v),
        "collection": collection,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "reranker_model": reranker_model,
        "openai_model": model,
        "temperature": temperature,
        "answer": answer,
        "hits": to_jsonable(hits),
        "prompt": prompt,
        "fetched_records": to_jsonable(records),
    }
    write_json(out_json, payload)
    write_markdown(
        out_md,
        title=f"run_mvp {run_id}",
        sections=[
            ("Fetch Query", args.fetch_query),
            ("Question", args.question),
            (
                "Summary",
                f"fetched={len(records)}, "
                f"indexed_docs={index_result['total_docs']}, "
                f"indexed_chunks={index_result['total_chunks']}, "
                f"hits={len(hits)}",
            ),
            ("OpenAI", f"model={model}, temperature={temperature}"),
            ("Answer", answer),
        ],
        prompt=prompt,
    )

    print(f"[OK] wrote:\n- {out_md}\n- {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli("run_mvp", main))
