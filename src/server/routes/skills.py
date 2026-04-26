"""Pipeline SKILL.md 列表 API —— 列出 ``.claude/skills/`` 下的可用 skill。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from src.server.settings import ROOT

router = APIRouter()

_SKILLS_ROOT = ROOT / ".claude" / "skills"


def _read_skill_summary(skill_md: Path) -> str:
    """从 SKILL.md 头部抽取一句话摘要——第一段非空、非标题的连续行。"""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return ""
    summary_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if summary_lines:
                break
            continue
        if line.startswith("#"):
            if summary_lines:
                break
            continue
        if line.startswith("---"):
            if summary_lines:
                break
            continue
        summary_lines.append(line)
        if len(" ".join(summary_lines)) > 240:
            break
    return " ".join(summary_lines)[:240]


def _list_skill_dirs() -> list[Path]:
    if not _SKILLS_ROOT.is_dir():
        return []
    return sorted(p for p in _SKILLS_ROOT.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def _serialize_skill(skill_dir: Path) -> dict[str, Any]:
    skill_md = skill_dir / "SKILL.md"
    return {
        "name": skill_dir.name,
        "path": str(skill_md.relative_to(ROOT)).replace("\\", "/"),
        "summary": _read_skill_summary(skill_md),
    }


@router.get("/api/skills")
async def list_skills() -> dict[str, Any]:
    """列出 ``.claude/skills/`` 下所有 pipeline SKILL.md。"""
    skills = [_serialize_skill(d) for d in _list_skill_dirs()]
    return {"skills": skills, "count": len(skills)}


@router.get("/api/skills/{skill_name}")
async def get_skill(skill_name: str) -> dict[str, Any]:
    """获取单个 SKILL.md 的完整 markdown 文档。"""
    safe_name = Path(skill_name).name
    if safe_name != skill_name or not safe_name:
        raise HTTPException(status_code=400, detail="invalid skill name")
    skill_dir = _SKILLS_ROOT / safe_name
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise HTTPException(status_code=404, detail=f"skill '{safe_name}' not found")
    return {
        **_serialize_skill(skill_dir),
        "documentation": skill_md.read_text(encoding="utf-8"),
    }
