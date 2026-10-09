"""Literature contextual tab 后端路由。

端点：
- ``GET  /api/literature/pdf-page?path=<abs>``      返回页面 PNG 与可选择文本
- ``GET  /api/literature/summary?path=<abs>``       从 classification.db 取 summary + 元信息
- ``GET  /api/literature/annotation?path=<abs>``    读 ``.mambaresearch/annotations/<sha>.md``
- ``PUT  /api/literature/annotation?path=<abs>``    写 ``.mambaresearch/annotations/<sha>.md``

安全
~~~~
``path`` 必须是已入 classification.db 的文件——避免任意路径读取。Annotation
保存到 active project 的 ``.mambaresearch/annotations/`` 下，文件名用
``sha256[:16]``——避免长路径 / 非 ASCII 文件名引起的 IO 麻烦。
"""
from __future__ import annotations

import hashlib
import base64
import io
import threading
from contextlib import closing
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
import pypdfium2 as pdfium

from src.server.projects.registry import get_registry
from src.server.workspace.classification import get_db_for_project


router = APIRouter()
_PDF_LOCK = threading.Lock()


def _require_active_project_path() -> Path:
    project = get_registry().get_active()
    if project is None:
        raise HTTPException(status_code=409, detail="no active project")
    return Path(project.path)


def _require_indexed_file(project_path: Path, raw_path: str):
    """确认 ``path`` 在分类索引内；返回 FileEntry。"""
    db = get_db_for_project(project_path)
    norm = raw_path.strip()
    entry = db.get_file(norm)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"path 未在分类索引内：{norm}。先调 workspace.scan / classify_one "
                "把它入库再操作。"
            ),
        )
    return entry


def _annotation_path(project_path: Path, sha256: str) -> Path:
    """``<project>/.mambaresearch/annotations/<sha[:16]>.md``。"""
    folder = project_path / ".mambaresearch" / "annotations"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{sha256[:16]}.md"


@router.get("/api/literature/pdf-page")
def get_pdf_page(path: str = Query(...), page: int = Query(default=0, ge=0)):
    project_path = _require_active_project_path()
    entry = _require_indexed_file(project_path, path)
    if Path(entry.path).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="文件不是 PDF")
    try:
        with _PDF_LOCK, pdfium.PdfDocument(entry.path) as document:
            count = len(document)
            if page >= count:
                raise HTTPException(status_code=400, detail="PDF 页码越界")
            with closing(document[page]) as pdf_page:
                with closing(pdf_page.get_textpage()) as text_page:
                    text = text_page.get_text_range()
                with closing(pdf_page.render(scale=1.5)) as bitmap:
                    image = bitmap.to_pil()
                    try:
                        buffer = io.BytesIO()
                        image.save(buffer, format="PNG")
                    finally:
                        image.close()
            return {"pages": count, "page": page, "text": text, "png": base64.b64encode(buffer.getvalue()).decode()}
    except (OSError, pdfium.PdfiumError) as exc:
        raise HTTPException(status_code=400, detail=f"无法读取 PDF：{exc}") from exc


@router.get("/api/literature/summary")
def get_literature_summary(path: str = Query(...)):
    project_path = _require_active_project_path()
    entry = _require_indexed_file(project_path, path)
    return {
        "path": entry.path,
        "primary_bucket": entry.primary_bucket,
        "subtype": entry.subtype,
        "summary": entry.summary,
        "tags": entry.tags,
        "size": entry.size,
        "mtime": entry.mtime,
        "sha256_short": entry.sha256[:16] if entry.sha256 else "",
    }


@router.get("/api/literature/annotation", response_class=PlainTextResponse)
def get_literature_annotation(path: str = Query(...)):
    project_path = _require_active_project_path()
    entry = _require_indexed_file(project_path, path)
    if not entry.sha256:
        return PlainTextResponse("", media_type="text/plain")
    target = _annotation_path(project_path, entry.sha256)
    if not target.exists():
        return PlainTextResponse("", media_type="text/plain")
    return PlainTextResponse(target.read_text(encoding="utf-8"), media_type="text/plain")


@router.put("/api/literature/annotation")
async def put_literature_annotation(request: Request, path: str = Query(...)):
    project_path = _require_active_project_path()
    entry = _require_indexed_file(project_path, path)
    if not entry.sha256:
        raise HTTPException(status_code=409, detail="文件 sha256 未计算，无法保存标注")
    body = (await request.body()).decode("utf-8", errors="replace")
    target = _annotation_path(project_path, entry.sha256)
    target.write_text(body, encoding="utf-8")
    return {"ok": True, "path": str(target), "bytes": len(body.encode("utf-8"))}
