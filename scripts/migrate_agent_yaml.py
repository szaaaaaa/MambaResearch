"""一次性迁移脚本：把 configs/agent.yaml 拆成 3 个 json 注册表。

枢转后 ``configs/agent.yaml`` 只剩 3 段还是活的：

============================ ====================================================
yaml 字段                    迁移目标
============================ ====================================================
``claude_code.providers``    ``configs/claude_code/providers.json``（整段 1:1）
``mcp.servers[*].env``       ``configs/mcp/env_overrides.json``（仅 env keys 子集）
``auth.openai_codex``        ``configs/codex/auth.json``（整段 1:1）
============================ ====================================================

**为什么 mcp 段只迁 env 而不是整个 servers list？**

枢转后 server 命令行（command/args）由 ``src/server/integrations/<name>/
mcp_server.py:default_mcp_config`` 程序级提供——它们 hardcode 在 git 管的
代码里，user 不能通过 settings UI 改动（安全边界：避免 PATCH 把 command
重定向到任意脚本）。yaml 里的 server_id/command/args 因此**作废**——
只有 env keys 是 user 级敏感配置（API keys），需要 user override 层。
迁出来的 env_overrides.json 形状：

::

    {
      "paper_search": {
        "PAPER_SEARCH_MCP_CORE_API_KEY": "",
        ...
      }
    }

具体合并由 ``src/server/mcp/env_overrides.py:load_env_overrides`` 负责。

其它 90% 字段在 ``src/`` 里 0 引用（旧 in-process 研究/实验/审查循环、旧 RAG
索引器、旧检索栈），yaml 整体随 1b 物理删除自然消失。

本脚本只做"读 yaml → 写 3 个 json"。**不动 yaml**，loader 切换在 plan task 1b
处理。这样保证 1a/1c 提交后中间态可启动、pytest 全绿。

设计约束
--------

- **幂等可重跑**：每次执行覆盖 3 个 json 输出，但脚本不修改 yaml，可任意次重跑。
- **One-shot 性质**：迁移完成且 1b 跑完后，整个 ``configs/agent.yaml`` 物理删除，
  本脚本随之失去用途——可与 yaml 一起在 1b 末尾从仓库移除。
- **严格模式**：yaml 不存在 / 顶层非 dict / 期望字段缺失 → 抛 ``MigrationError``。
  不做静默兜底，避免错误的部分迁移让人误以为成功。

CLI 用法
--------

::

    python scripts/migrate_agent_yaml.py
    python scripts/migrate_agent_yaml.py --source configs/agent.yaml --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT / "configs" / "agent.yaml"
DEFAULT_TARGETS = {
    ("claude_code", "providers"): REPO_ROOT / "configs" / "claude_code" / "providers.json",
    ("auth", "openai_codex"): REPO_ROOT / "configs" / "codex" / "auth.json",
}
ENV_OVERRIDES_TARGET = REPO_ROOT / "configs" / "mcp" / "env_overrides.json"


class MigrationError(RuntimeError):
    """迁移过程中遇到的非预期 yaml 结构。"""


def _extract(config: dict[str, Any], path: tuple[str, ...]) -> Any:
    """按层级路径取出 yaml 中的子树，缺失字段直接报错。"""

    cursor: Any = config
    for key in path:
        if not isinstance(cursor, dict):
            raise MigrationError(
                f"yaml path {'.'.join(path)} expects dict at {key!r}, "
                f"got {type(cursor).__name__}"
            )
        if key not in cursor:
            raise MigrationError(f"yaml missing required key: {'.'.join(path)}")
        cursor = cursor[key]
    return cursor


def _extract_env_overrides(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    """从 ``mcp.servers[*]`` 抽 env keys 重组为 ``{server_id: env_dict}`` 形式。

    yaml 里的 ``mcp.servers`` 是 list，每个元素含 ``server_id`` 与 ``env``。
    转成 ``{server_id: env_dict}`` 形式存入 env_overrides.json，方便
    ``load_env_overrides(server_id)`` 快速查找。

    缺 server_id / env 不是 dict → 跳过该条；整段缺失 / 非 list → 抛错。
    """

    servers = _extract(config, ("mcp", "servers"))
    if not isinstance(servers, list):
        raise MigrationError(
            f"yaml mcp.servers must be a list, got {type(servers).__name__}"
        )
    overrides: dict[str, dict[str, str]] = {}
    for srv in servers:
        if not isinstance(srv, dict):
            continue
        sid = srv.get("server_id")
        env = srv.get("env")
        if not isinstance(sid, str) or not sid.strip():
            continue
        if not isinstance(env, dict):
            continue
        overrides[sid] = {str(k): str(v) for k, v in env.items()}
    return overrides


def _write_json(target: Path, payload: Any) -> None:
    """写 json，必要时创建父目录。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False, sort_keys=False)
        fp.write("\n")


def migrate(
    source: Path,
    targets: dict[tuple[str, ...], Path],
    env_overrides_target: Path,
    dry_run: bool = False,
) -> dict[Path, Any]:
    """主迁移流程，返回 ``{target_path: payload}`` 用于报告。"""

    if not source.exists():
        raise MigrationError(f"source yaml not found: {source}")
    with source.open("r", encoding="utf-8") as fp:
        config = yaml.safe_load(fp)
    if not isinstance(config, dict):
        raise MigrationError(
            f"yaml top-level must be a mapping, got {type(config).__name__}"
        )

    results: dict[Path, Any] = {}
    # 简单 path 抽取：providers / codex auth
    for path, target in targets.items():
        payload = _extract(config, path)
        results[target] = payload
        if not dry_run:
            _write_json(target, payload)
    # 特殊处理：mcp.servers → env_overrides.json（仅 env 子集）
    overrides = _extract_env_overrides(config)
    results[env_overrides_target] = overrides
    if not dry_run:
        _write_json(env_overrides_target, overrides)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="path to legacy configs/agent.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and validate but do not write json files",
    )
    args = parser.parse_args(argv)

    try:
        results = migrate(
            args.source,
            DEFAULT_TARGETS,
            ENV_OVERRIDES_TARGET,
            dry_run=args.dry_run,
        )
    except MigrationError as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1

    action = "would write" if args.dry_run else "wrote"
    for target, payload in results.items():
        rel = target.relative_to(REPO_ROOT)
        size = len(json.dumps(payload, ensure_ascii=False))
        print(f"{action} {rel} ({size} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
