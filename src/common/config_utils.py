from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import yaml


def project_root(from_file: str | Path) -> Path:
    return Path(from_file).resolve().parents[1]


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_by_dotted(cfg: Dict[str, Any], dotted_key: str) -> Any:
    cur: Any = cfg
    for part in dotted_key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def expand_vars(value: str, cfg: Dict[str, Any]) -> str:
    out = value
    pattern = re.compile(r"\$\{([^}]+)\}")
    for _ in range(6):
        matches = pattern.findall(out)
        if not matches:
            break
        changed = False
        for key in matches:
            raw = get_by_dotted(cfg, key)
            if raw is None:
                continue
            out = out.replace("${" + key + "}", str(raw))
            changed = True
        if not changed:
            break
    return out


def pick_str(*candidates: Any, default: str) -> str:
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s
    return default


def resolve_path(root: Path, raw: str, cfg: Dict[str, Any] | None = None) -> Path:
    expanded = expand_vars(raw, cfg) if cfg is not None else raw
    p = Path(expanded)
    if p.is_absolute():
        return p
    return (root / p).resolve()


def as_bool(v: Any, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def read_env_file(env_path: Path) -> Dict[str, str]:
    """将 dotenv 格式文件解析为字典，跳过注释行和空行。"""
    if not env_path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed_value = value.strip().strip('"').strip("'")
        if parsed_value:
            values[key.strip()] = parsed_value
    return values
