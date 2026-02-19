# src/ingest/fetchers.py
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime
from urllib.parse import quote_plus
import feedparser
import time 
import requests
import sqlite3
from pathlib import Path


@dataclass
class PaperRecord:
    source: str
    title: str
    authors: List[str]
    year: Optional[int]
    uid: str
    pdf_url: Optional[str]
    pdf_path: Optional[str]
    abstract: Optional[str]
    fetched_at: datetime

def make_uid(*, doi: Optional[str] = None, arxiv_id: Optional[str] = None) -> str:
    if doi:
        return f"doi:{doi.strip().lower()}"
    if arxiv_id:
        return f"arxiv:{arxiv_id.strip().lower()}"
    raise ValueError("Either doi or arxiv_id must be provided")

def _pick_arxiv_pdf_url(entry) -> Optional[str]:
    for link in getattr(entry, "links", []):
        if getattr(link, "type", None) == "application/pdf":
            return getattr(link, "href", None)
    return None

def fetch_arxiv(
    query: str,
    max_results: int = 20,
    download: bool = False,
    papers_dir: str = "data/papers",
    polite_delay_sec: float = 1.0,
) -> List[PaperRecord]:
    
    q = quote_plus(query)
    search_url = (
        "http://export.arxiv.org/api/query?"
        f"search_query=all:{q}"
        f"&start=0&max_results={max_results}"
    )

    feed = feedparser.parse(search_url)
    records: List[PaperRecord] = []

    for entry in feed.entries:
        arxiv_id = entry.id.split("/")[-1]
        pdf_url = normalize_arxiv_pdf_url(_pick_arxiv_pdf_url(entry))
        pdf_path = None
        if download and pdf_url:
            pdf_path = download_pdf(pdf_url, papers_dir, make_uid(arxiv_id=arxiv_id), polite_delay_sec=polite_delay_sec)

        record = PaperRecord(
            source="arxiv",
            title=entry.title.strip(),
            authors=[a.name for a in entry.authors],
            year=int(entry.published[:4]) if hasattr(entry, "published") else None,
            uid=make_uid(arxiv_id=arxiv_id),
            pdf_url=pdf_url,
            pdf_path=pdf_path,
            abstract=entry.summary.strip() if hasattr(entry, "summary") else None,
            fetched_at=datetime.now(),
        )
        records.append(record)

    return records

def uid_to_filename(uid:str) -> str:
    safe = uid.replace(":","_").replace("/","_")
    return f"{safe}.pdf"

def download_pdf(pdf_url: str, papers_dir: str, uid: str, polite_delay_sec: float = 1.0) -> str:
    Path(papers_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(papers_dir) / uid_to_filename(uid)

    r = requests.get(pdf_url, timeout=60, headers={"User-Agent": "auto-research-agent/0.1"})
    r.raise_for_status()
    out_path.write_bytes(r.content)

    if polite_delay_sec > 0:
        time.sleep(polite_delay_sec)

    return str(out_path)

def init_metadata_db(sqlite_path: str) -> None:
    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS papers (
            uid TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            authors TEXT,
            year INTEGER,
            pdf_url TEXT,
            pdf_path TEXT,
            abstract TEXT,
            fetched_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()

def upsert_papers(sqlite_path: str, records: List[PaperRecord]) -> None:
    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()
    for r in records:
        cur.execute(
            """
            INSERT OR REPLACE INTO papers
            (uid, source, title, authors, year, pdf_url, pdf_path, abstract, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.uid,
                r.source,
                r.title,
                ",".join(r.authors),
                r.year,
                r.pdf_url,
                r.pdf_path,
                r.abstract,
                r.fetched_at.isoformat(),
            ),
        )
    conn.commit()
    conn.close()

def normalize_arxiv_pdf_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if url.startswith("http://arxiv.org/pdf/") or url.startswith("https://arxiv.org/pdf/"):
        if not url.endswith(".pdf"):
            return url + ".pdf"
    return url

def fetch_arxiv_and_store(
    query: str,
    sqlite_path: str,
    papers_dir: str,
    max_results: int = 20,
    download: bool = True,
    polite_delay_sec: float = 1.0,
) -> List[PaperRecord]:
    init_metadata_db(sqlite_path)
    recs = fetch_arxiv(
        query,
        max_results=max_results,
        download=download,
        papers_dir=papers_dir,
        polite_delay_sec=polite_delay_sec,
    )
    upsert_papers(sqlite_path, recs)
    return recs
