"""一次性迁移脚本：把 configs/agent.yaml 拆成 3 个 json 注册表。

枢转后 ``configs/agent.yaml`` 只剩 3 段还是活的：

============================ ========================================
yaml 字段                    迁移目标
============================ ========================================
``claude_code.providers``    ``configs/claude_code/providers.json``
``mcp.servers``              ``configs/mcp/servers.json``
``auth.openai_codex``        ``configs/codex/auth.json``
============================ ========================================

其它 90% 字段在 ``src/`` 里 0 引用（旧 in-process 研究/实验/审查循环、旧 RAG
索引器、旧检索栈），yaml 整体随 1b 物理删除自然消失。

本脚本只做"读 yaml → 写 3 个 json"。**不动 yaml**，loader 切换在 plan task 1b
处理。这样保证 1a 提交后中间态可启动、pytest 全绿。

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
    ("mcp", "servers"): REPO_ROOT / "configs" / "mcp" / "servers.json",
    ("auth", "openai_codex"): REPO_ROOT / "configs" / "codex" / "auth.json",
}


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


def _write_json(target: Path, payload: Any) -> None:
    """写 json，必要时创建父目录。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False, sort_keys=False)
        fp.write("\n")


def migrate(source: Path, targets: dict[tuple[str, ...], Path], dry_run: bool = False) -> dict[Path, Any]:
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
    for path, target in targets.items():
        payload = _extract(config, path)
        results[target] = payload
        if not dry_run:
            _write_json(target, payload)
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
        results = migrate(args.source, DEFAULT_TARGETS, dry_run=args.dry_run)
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
