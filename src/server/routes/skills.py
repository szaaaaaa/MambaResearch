"""Pipeline SKILL.md / Sub-agent .md 列表 API。

settings UI 的 "Skills & Agents" 视图（D+E 重构 task 4）通过这两个端点列出可用的
pipeline skill 与 sub-agent。两者都是 git 管的 markdown 文件，UI 只读 + 跳转复制
路径，不通过 HTTP 编辑（编辑走 IDE / git 流程，避免 schema drift）。

端点
----

- ``GET /api/skills``               列 ``.claude/skills/*/SKILL.md``（NTFS junction
                                    指向 ``.skills-shared/``，物理源头同一份）
- ``GET /api/skills/{name}``        单个 SKILL.md 的完整 markdown
- ``GET /api/agents``               列 ``.claude/agents/*.md`` sub-agent 定义
- ``GET /api/agents/{name}``        单个 agent .md 的完整 markdown
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from src.server.settings import ROOT

router = APIRouter()

_SKILLS_ROOT = ROOT / ".claude" / "skills"
_AGENTS_ROOT = ROOT / ".claude" / "agents"


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


def _file_metadata(path: Path) -> dict[str, Any]:
    """返回 size / mtime（unix epoch float），文件不存在则返回 0/0。"""
    try:
        stat = path.stat()
        return {"size": stat.st_size, "mtime": stat.st_mtime}
    except OSError:
        return {"size": 0, "mtime": 0.0}


def _list_skill_dirs() -> list[Path]:
    if not _SKILLS_ROOT.is_dir():
        return []
    return sorted(p for p in _SKILLS_ROOT.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def _list_agent_files() -> list[Path]:
    if not _AGENTS_ROOT.is_dir():
        return []
    return sorted(p for p in _AGENTS_ROOT.glob("*.md") if p.is_file())


def _serialize_skill(skill_dir: Path) -> dict[str, Any]:
    skill_md = skill_dir / "SKILL.md"
    return {
        "name": skill_dir.name,
        "path": str(skill_md.relative_to(ROOT)).replace("\\", "/"),
        "summary": _read_skill_summary(skill_md),
        **_file_metadata(skill_md),
    }


def _serialize_agent(agent_md: Path) -> dict[str, Any]:
    """读 agent .md 的 frontmatter description 作 summary，回退到正文首段。"""
    summary = ""
    try:
        text = agent_md.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if text.startswith("---"):
        # frontmatter 段：抽 description: 行
        for raw_line in text.splitlines()[1:]:
            stripped = raw_line.strip()
            if stripped == "---":
                break
            if stripped.startswith("description:"):
                summary = stripped[len("description:"):].strip().strip('"').strip("'")
                break
    if not summary:
        summary = _read_skill_summary(agent_md)
    return {
        "name": agent_md.stem,
        "path": str(agent_md.relative_to(ROOT)).replace("\\", "/"),
        "summary": summary[:240],
        **_file_metadata(agent_md),
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


@router.get("/api/agents")
async def list_agents() -> dict[str, Any]:
    """列出 ``.claude/agents/`` 下所有 sub-agent .md 定义。"""
    agents = [_serialize_agent(p) for p in _list_agent_files()]
    return {"agents": agents, "count": len(agents)}


@router.get("/api/agents/{agent_name}")
async def get_agent(agent_name: str) -> dict[str, Any]:
    """获取单个 sub-agent .md 的完整 markdown。"""
    safe_name = Path(agent_name).name
    if safe_name != agent_name or not safe_name:
        raise HTTPException(status_code=400, detail="invalid agent name")
    agent_md = _AGENTS_ROOT / f"{safe_name}.md"
    if not agent_md.is_file():
        raise HTTPException(status_code=404, detail=f"agent '{safe_name}' not found")
    return {
        **_serialize_agent(agent_md),
        "documentation": agent_md.read_text(encoding="utf-8"),
    }
