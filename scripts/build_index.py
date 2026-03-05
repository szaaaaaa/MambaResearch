from __future__ import annotations

import argparse
from pathlib import Path
from src.common.arg_utils import add_index_build_args, add_index_store_args, add_retrieval_args
from src.common.cli_utils import add_config_arg, parse_args_and_cfg, run_cli
from src.common.rag_config import collection_name, papers_dir, persist_dir, retrieval_embedding_model, retrieval_hybrid
from src.workflows.traditional_rag import index_pdfs, list_pdfs


def main() -> int:
    ap = argparse.ArgumentParser()
    add_config_arg(ap, __file__)
    ap.add_argument("--papers_dir", default=None, help="PDF directory")
    ap.add_argument("--pdf_path", default=None, help="Single PDF path (absolute or under papers_dir)")
    ap.add_argument("--doc_id", default=None, help="Doc ID for single PDF mode")
    add_index_store_args(ap)
    add_index_build_args(ap)
    add_retrieval_args(ap)
    args, root, cfg = parse_args_and_cfg(ap, __file__)

    papers_dir_v = papers_dir(root, cfg, args.papers_dir)
    persist_dir_v = persist_dir(root, cfg, args.persist_dir)
    collection = collection_name(cfg, args.collection)

    emb_model = retrieval_embedding_model(cfg, getattr(args, "embedding_model", None))
    hybrid = retrieval_hybrid(cfg, getattr(args, "hybrid", None))

    persist_dir_v.mkdir(parents=True, exist_ok=True)

    pdfs = list_pdfs(papers_dir=papers_dir_v, pdf_path=args.pdf_path)

    print(">> build_index start")
    print(f">> papers_dir = {papers_dir_v}")
    print(f">> persist_dir = {persist_dir_v}")
    print(f">> collection = {collection}")
    print(f">> embedding_model = {emb_model}")
    print(f">> hybrid = {hybrid}")
    print(f">> pdf_count = {len(pdfs)}")

    result = index_pdfs(
        persist_dir=str(persist_dir_v),
        collection_name=collection,
        pdfs=pdfs,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        max_pages=args.max_pages,
        keep_old=args.keep_old,
        single_doc_id=args.doc_id,
        embedding_model=emb_model,
        build_bm25=hybrid,
    )

    for row in result["rows"]:
        print(
            f">> indexed {Path(row['pdf_path']).name}: "
            f"doc_id={row['doc_id']} pages={row['num_pages']} chunks={row['chunks']}"
        )

    print(f"[OK] indexed docs={result['total_docs']}, chunks={result['total_chunks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli("build_index", main))
