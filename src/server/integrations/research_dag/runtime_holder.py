"""DAG runtime 单例 holder——按 active project 缓存 DynamicResearchRuntime。

设计要点
~~~~~~~~
* runtime 实例是**进程级缓存**，按 ``project_root`` (绝对路径) 做 key；
  避免每次 MCP 工具调用都重新 init runtime（冷启动慢，且 storage 状态会丢）。
* 切 active project 时调 :func:`close_runtime`——当前 runtime 没有显式
  资源句柄，仅丢弃缓存条目，靠 GC 回收即可。
* :func:`get_runtime_for_active_project` 是上层主调入口：从 ``ProjectRegistry``
  读 active project，按其 path 拿 / 建 runtime；无 active project 返 ``None``。

锁策略
~~~~~~
模块级 ``threading.Lock`` 串行 ``_HOLDER`` dict 的读写。MCP server 进程
通常是单线程 stdio loop + 偶发 ``asyncio.to_thread`` 调用，争用很轻；不
追求 read/write lock 级别细粒度。
"""
from __future__ import annotations

from pathlib import Path
from threading import Lock

from src.dynamic_os.runtime import DynamicResearchRuntime
from src.server.projects.registry import get_registry


_LOCK = Lock()
_HOLDER: dict[str, DynamicResearchRuntime] = {}


def get_runtime(project_root: str | Path) -> DynamicResearchRuntime:
    """按 ``project_root`` 缓存复用 ``DynamicResearchRuntime``。

    Parameters
    ----------
    project_root : str | Path
        项目根目录绝对路径；用作 runtime 的 ``root`` 入参，runtime 默认
        把 ``<root>/outputs`` 作为产物输出目录。

    Returns
    -------
    DynamicResearchRuntime
        同一 ``project_root``（按 ``Path.resolve()`` 归一化后）多次调用
        复用同一实例。
    """
    key = str(Path(project_root).resolve())
    with _LOCK:
        rt = _HOLDER.get(key)
        if rt is None:
            rt = DynamicResearchRuntime(root=key)
            _HOLDER[key] = rt
        return rt


def get_runtime_for_active_project() -> DynamicResearchRuntime | None:
    """根据 ``ProjectRegistry`` 的 active project 拿 runtime。

    Returns
    -------
    DynamicResearchRuntime | None
        当前无 active project 时返 ``None``；MCP 工具调用方应据此返业务错误。
    """
    project = get_registry().get_active()
    if project is None:
        return None
    return get_runtime(project.path)


def close_runtime(project_root: str | Path) -> None:
    """切 project / project 删除时调；从缓存移除对应 runtime 条目。

    底层 runtime 暂无资源句柄需显式关闭，移除条目让 GC 回收即可。
    未建过的 ``project_root`` 调用本函数是 no-op。
    """
    key = str(Path(project_root).resolve())
    with _LOCK:
        _HOLDER.pop(key, None)


def reset_holder_for_tests() -> None:
    """测试用——清空所有缓存条目。"""
    with _LOCK:
        _HOLDER.clear()
