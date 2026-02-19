from __future__ import annotations

import argparse


def add_fetch_storage_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sqlite_path", default=None, help="SQLite path for metadata")
    parser.add_argument("--papers_dir", default=None, help="Directory storing PDFs")


def add_fetch_control_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max_results", type=int, default=None, help="Maximum arXiv results")
    parser.add_argument("--polite_delay_sec", type=float, default=None, help="Delay between PDF downloads")
    parser.add_argument("--download", dest="download", action="store_true", help="Download PDFs from arXiv")
    parser.add_argument("--no-download", dest="download", action="store_false", help="Do not download PDFs")
    parser.set_defaults(download=None)


def add_index_store_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--persist_dir", default=None, help="Chroma persist dir")
    parser.add_argument("--collection", default=None, help="Chroma collection name")


def add_index_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--chunk_size", type=int, default=1200, help="Chunk size")
    parser.add_argument("--overlap", type=int, default=200, help="Chunk overlap")
    parser.add_argument("--max_pages", type=int, default=None, help="Read first N pages per PDF")
    parser.add_argument("--keep_old", action="store_true", help="Keep existing chunks for same doc_id")


def add_qa_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", type=str, default=None, help="OpenAI model")
    parser.add_argument("--temperature", type=float, default=None, help="OpenAI temperature")


def add_retrieval_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--top_k", type=int, default=None, help="Retriever top_k")


def add_reranker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate_k", type=int, default=None, help="Retriever candidate_k before reranking")
    parser.add_argument("--reranker_model", type=str, default=None, help="Local reranker model (CrossEncoder)")
