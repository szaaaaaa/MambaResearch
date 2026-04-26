"""Literature contextual tab 后端路由。

端点：
- ``GET  /api/literature/file?path=<abs>``          返回 PDF 字节（用于 <embed>）
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
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from src.server.projects.registry import get_registry
from src.server.workspace.classification import get_db_for_project


router = APIRouter()


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


@router.get("/api/literature/file")
def get_literature_file(path: str = Query(..., description="本地 PDF 绝对路径")):
    project_path = _require_active_project_path()
    entry = _require_indexed_file(project_path, path)
    real = Path(entry.path)
    if not real.exists() or not real.is_file():
        raise HTTPException(status_code=404, detail=f"文件已不存在：{real}")
    suffix = real.suffix.lower()
    media = "application/pdf" if suffix == ".pdf" else "application/octet-stream"
    return FileResponse(str(real), media_type=media, filename=real.name)


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
