"""技能管理 API —— 列出、查询、删除已注册技能及其执行指标。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from src.dynamic_os.skills.discovery import discover_skill_packages
from src.dynamic_os.skills.loader import load_skill
from src.dynamic_os.skills.registry import SkillRegistry
from src.dynamic_os.storage.skill_metrics import SqliteSkillMetricsStore, InMemorySkillMetricsStore, SkillMetrics
from src.dynamic_os.storage.sqlite_store import init_knowledge_db
from src.common.config_utils import load_yaml
from src.server.settings import ROOT, CONFIG_PATH

router = APIRouter()

# 技能搜索根目录
_BUILTINS_ROOT = Path(__file__).resolve().parents[2] / "dynamic_os" / "skills" / "builtins"
_USER_SKILLS_ROOT = ROOT / "skills"
_EVOLVED_SKILLS_ROOT = ROOT / "evolved_skills"
_SKILL_ROOTS = [_BUILTINS_ROOT, _USER_SKILLS_ROOT, _EVOLVED_SKILLS_ROOT]

# 可删除的目录（仅进化技能）
_DELETABLE_ROOTS = {str(_EVOLVED_SKILLS_ROOT.resolve())}


def _build_registry() -> SkillRegistry:
    """构建当前的技能注册表快照。"""
    return SkillRegistry.discover(roots=_SKILL_ROOTS)


def _get_metrics_store():
    """获取指标存储（优先 SQLite，fallback 内存）。"""
    config = load_yaml(CONFIG_PATH)
    persistence_mode = str((config.get("knowledge_graph") or {}).get("persistence_mode", "memory")).strip()
    if persistence_mode == "sqlite":
        kg_path = str((config.get("knowledge_graph") or {}).get("sqlite_path", "")).strip()
        if not kg_path:
            kg_path = str(ROOT / "data" / "knowledge_graph.db")
        if Path(kg_path).exists():
            conn = init_knowledge_db(kg_path)
            return SqliteSkillMetricsStore(conn)
    return InMemorySkillMetricsStore()


def _skill_source(loaded_skill) -> str:
    """判断技能来源：builtin / user / evolved。"""
    spec_path = str(getattr(loaded_skill, "package_dir", "") or "")
    if not spec_path:
        return "builtin"
    resolved = str(Path(spec_path).resolve())
    if resolved.startswith(str(_EVOLVED_SKILLS_ROOT.resolve())):
        return "evolved"
    if resolved.startswith(str(_USER_SKILLS_ROOT.resolve())):
        return "user"
    return "builtin"


def _serialize_skill(loaded_skill, metrics: SkillMetrics | None = None) -> dict[str, Any]:
    """将 LoadedSkill 序列化为 API 响应格式。"""
    spec = loaded_skill.spec
    result: dict[str, Any] = {
        "id": spec.id,
        "name": spec.name,
        "version": spec.version,
        "description": spec.description,
        "applicable_roles": [r.value for r in spec.applicable_roles],
        "input_contract": {
            "required": list(spec.input_contract.required),
            "optional": list(spec.input_contract.optional),
        },
        "output_artifacts": list(spec.output_artifacts),
        "allowed_tools": list(spec.allowed_tools),
        "timeout_sec": spec.timeout_sec,
        "source": _skill_source(loaded_skill),
        "deletable": _skill_source(loaded_skill) == "evolved",
    }
    if metrics is not None:
        result["metrics"] = {
            "execution_count": metrics.execution_count,
            "success_count": metrics.success_count,
            "fail_count": metrics.fail_count,
            "avg_duration_ms": round(metrics.avg_duration_ms, 1),
            "utility_score": round(metrics.utility_score, 3),
        }
    else:
        result["metrics"] = None
    return result


@router.get("/api/skills")
async def list_skills():
    """列出所有已注册技能。"""
    registry = _build_registry()
    metrics_store = _get_metrics_store()
    all_metrics = metrics_store.get_all_metrics()

    skills = []
    for loaded_skill in registry.list():
        m = all_metrics.get(loaded_skill.spec.id)
        skills.append(_serialize_skill(loaded_skill, m))
    return {"skills": skills, "count": len(skills)}


@router.get("/api/skills/metrics")
async def list_skill_metrics():
    """返回所有技能的执行指标。"""
    metrics_store = _get_metrics_store()
    all_metrics = metrics_store.get_all_metrics()
    return {
        skill_id: {
            "execution_count": m.execution_count,
            "success_count": m.success_count,
            "fail_count": m.fail_count,
            "avg_duration_ms": round(m.avg_duration_ms, 1),
            "utility_score": round(m.utility_score, 3),
        }
        for skill_id, m in all_metrics.items()
    }


@router.get("/api/skills/{skill_id}")
async def get_skill(skill_id: str):
    """获取单个技能的详细信息（含文档和指标）。"""
    registry = _build_registry()
    try:
        loaded_skill = registry.get(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"skill '{skill_id}' not found")

    metrics_store = _get_metrics_store()
    all_metrics = metrics_store.get_all_metrics()
    m = all_metrics.get(skill_id)

    result = _serialize_skill(loaded_skill, m)
    result["documentation"] = loaded_skill.documentation or ""
    return result


@router.delete("/api/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """删除进化生成的技能（仅 evolved_skills 目录下的可删）。"""
    registry = _build_registry()
    try:
        loaded_skill = registry.get(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"skill '{skill_id}' not found")

    source = _skill_source(loaded_skill)
    if source != "evolved":
        raise HTTPException(status_code=403, detail=f"only evolved skills can be deleted, this skill is '{source}'")

    package_dir = getattr(loaded_skill, "package_dir", None)
    if package_dir is None or not Path(package_dir).is_dir():
        raise HTTPException(status_code=404, detail="skill directory not found on disk")

    # 安全检查：确认目录在 evolved_skills 下
    resolved = str(Path(package_dir).resolve())
    if not any(resolved.startswith(root) for root in _DELETABLE_ROOTS):
        raise HTTPException(status_code=403, detail="skill directory is outside deletable roots")

    shutil.rmtree(package_dir)
    return {"deleted": skill_id}
