"""组件注册表 —— 实验工作区的核心扩展机制。

所有可插拔组件（数据集、模型、指标、训练器）通过此注册表管理。
AI agent 在实验迭代中可以注册新组件，train.py 通过注册表名称查找并实例化。

用法：
    from registry import register, create

    # 注册组件
    register("model", "my_transformer", MyTransformerClass)

    # 通过名称创建实例
    model = create("model", "my_transformer", **kwargs)
"""

from __future__ import annotations

from typing import Any, Callable

# 全局注册表：category -> name -> factory
_REGISTRY: dict[str, dict[str, Any]] = {}


def register(category: str, name: str, factory: Any) -> None:
    """注册一个组件工厂到指定类别。"""
    _REGISTRY.setdefault(category, {})[name] = factory


def get(category: str, name: str) -> Any:
    """获取已注册的组件工厂。"""
    bucket = _REGISTRY.get(category, {})
    if name not in bucket:
        available = list(bucket.keys())
        raise KeyError(
            f"'{name}' not registered in '{category}'. "
            f"Available: {available}"
        )
    return bucket[name]


def create(category: str, name: str, **kwargs: Any) -> Any:
    """获取工厂并调用它创建实例。"""
    factory = get(category, name)
    return factory(**kwargs)


def list_registered(category: str) -> list[str]:
    """列出某类别下所有已注册的名称。"""
    return list(_REGISTRY.get(category, {}).keys())
